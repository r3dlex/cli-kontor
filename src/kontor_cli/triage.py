"""Email → Asana management-action triage.

Deterministic importance scoring, recall-biased body-fetch selection, and
idempotent task creation orchestration. Category classification is supplied by
the AGENT driving the skill (not a configured LLM): ``list_candidates`` surfaces
the qualifying emails + bodies for the agent to read, and ``create_task_for``
turns the agent's ``CategoryDecision`` into an idempotent Asana task. All
per-email Asana/date errors are caught inside ``create_task_for`` and turned
into ``outcome="skipped_error"`` — they never propagate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from . import himalaya
from .asana_client import AsanaClient, AsanaError
from .himalaya import list_emails, read_message_body

if TYPE_CHECKING:
    from .config import Config
    from .himalaya import Email
    from .pipeline import Pipeline

logger = logging.getLogger(__name__)

# Sender-tier weights for the deterministic importance component.
TIER_WEIGHTS: dict[str, float] = {
    "extremely_important": 1.0,
    "very_important": 0.8,
    "also_important": 0.5,
}

# Broad subject-keyword pre-scan for the unlisted/non-customer remainder.
# Over-fetch biased (recall over precision); the agent is the precision filter.
_CONTENT_KEYWORDS: tuple[str, ...] = (
    "escalation",
    "escalate",
    "urgent",
    "asap",
    "decision",
    "decide",
    "approve",
    "approval",
    "blocker",
    "blocked",
    "can you",
    "could you",
    "please advise",
    "please review",
    "deadline",
    "go-live",
    "go live",
    "hypercare",
    "critical",
    "priority",
    "action required",
)

# Category rubric → standard text + definition-of-done, encoded VERBATIM.
CATEGORY_TEMPLATES: dict[str, dict[str, str]] = {
    "information_gathering": {
        "standard_text": (
            "Observe & collect: {what data/signal}. Source: {email link}. "
            "Watching for: {pattern}. No direction change yet."
        ),
        "done_when": (
            "Data reviewed and a note recorded — either 'warrants action → "
            "follow-up spawned' or 'no action needed' — then closed."
        ),
    },
    "nudging": {
        "standard_text": (
            "Nudge {who} toward {better outcome} via {subtle mechanism — link / "
            "open question / framing}. Preserve their autonomy."
        ),
        "done_when": (
            "Nudge delivered (message/question/resource sent) and you noted "
            "whether it landed."
        ),
    },
    "being_the_example": {
        "standard_text": (
            "Model {habit / standard / boundary} in {context}. Demonstrate, "
            "don't instruct."
        ),
        "done_when": (
            "A visible artifact exists (doc written, PR comment left, boundary "
            "set) that others can see."
        ),
    },
    "taking_decision": {
        "standard_text": (
            "Decide: {question}. Options: {A / B}. Constraint/deadline: {date}. "
            "Communicate to: {stakeholders}."
        ),
        "done_when": (
            "Decision made, communicated to stakeholders, recorded; deadlock resolved."
        ),
    },
}

_VALID_CATEGORIES: frozenset[str] = frozenset(CATEGORY_TEMPLATES)


@dataclass
class ImportanceScore:
    """Result of the deterministic importance evaluation."""

    sender_component: float
    content_component: float
    customer_boost: bool
    escalation_boost: bool
    decisive_prior: bool
    qualifies: bool
    reason: str


@dataclass
class CategoryDecision:
    """Agent-supplied judgment of category + (optional) deadline for an email."""

    category: str
    deadline: date | None
    rationale: str


@dataclass
class TriageCandidate:
    """A qualifying email surfaced for the agent to classify.

    Carries the fetched body so the agent can read the full message and decide
    on a category + deadline without a second round-trip.
    """

    email_id: str
    from_name: str
    from_addr: str
    subject: str
    body: str
    reason: str
    decisive_prior: bool
    # Canonical taxonomy folder from the deterministic rules engine (e.g.
    # "2_Projects/PRJ_Willemen"), or None when rules don't match. Gives the
    # agent the email's canonical placement as context for category judgment.
    canonical_folder: str | None = None


@dataclass
class TriageDecision:
    """Per-email triage outcome (preview-safe; no side effects implied)."""

    email_id: str
    qualifies: bool
    reason: str
    category: str | None
    target_date: str | None
    task_name: str | None
    task_notes: str | None
    outcome: str  # preview | created | skipped_dedup | skipped_error | not_qualified


class Triage:
    """Composed, deterministic-core email → Asana triage engine."""

    def __init__(self, config: Config, cwd: Path | None = None) -> None:
        self.config = config
        self.cwd = cwd
        # Lazy Asana client: only when a PAT is configured.
        self.asana: AsanaClient | None = None
        if config.asana_pat and config.asana_workspace_gid:
            self.asana = AsanaClient(
                config.asana_pat,
                config.asana_workspace_gid,
                config.asana_project_gids,
            )
        # The Pipeline owns deterministic rule classification. Build it lazily
        # so create_task_for never loads rule files or the LLM classifier.
        self._pipeline: Pipeline | None = None
        self._pipeline_init = False
        self.tiers = config.triage_sender_tiers
        self.internal_domain = config.triage_internal_domain
        self.content_high_threshold = config.triage_content_high_threshold
        # Whose input/action a task must require (precision rule applied by the
        # agent during classification — sender importance alone is insufficient).
        self.owner_email = config.triage_owner_email
        # Config-driven exclusion list (substring match on name/address),
        # in addition to the is_automated() heuristic.
        self.exclude_senders: list[str] = [
            e.lower().strip() for e in config.triage_exclude_senders if e.strip()
        ]
        # Decisive senders surface a soft hint to the agent (not forced).
        self.decisive: list[str] = list(self.tiers.get("very_important", []))

    # ------------------------------------------------------------------ #
    # Step 3 — deterministic scoring + eligibility gate
    # ------------------------------------------------------------------ #
    @staticmethod
    def _matches_member(from_addr: str, from_name: str, member: str) -> bool:
        """Match an email's from-field against a tier member string.

        Matches by case-insensitive substring on either the display name or
        the address — seeded tier entries may be a display name (e.g. "Rolf
        Helmes") or an address (e.g. "rolf.helmes@rib-software.com"). Both the
        envelope ``from_name`` and ``from_addr`` are searched.
        """
        needle = member.lower().strip()
        if not needle:
            return False
        haystack = f"{from_name}\n{from_addr}".lower()
        return needle in haystack

    def score_sender(self, email: Email) -> tuple[float, bool, bool]:
        """Return ``(weight, decisive_prior, in_any_tier)`` for the sender.

        Highest matching tier wins. ``decisive_prior`` is True iff the sender
        is in the ``very_important`` tier.
        """
        weight = 0.0
        in_any_tier = False
        decisive_prior = False
        for tier, members in self.tiers.items():
            for member in members:
                if self._matches_member(email.from_addr, email.from_name, member):
                    in_any_tier = True
                    tier_weight = TIER_WEIGHTS.get(tier, 0.0)
                    if tier_weight > weight:
                        weight = tier_weight
                    if tier == "very_important":
                        decisive_prior = True
        return weight, decisive_prior, in_any_tier

    def is_customer(self, from_addr: str) -> bool:
        """True when the sender's domain is external (not the internal domain)."""
        if "@" not in from_addr:
            return False
        domain = from_addr.rsplit("@", 1)[-1].strip().lower().strip("<>")
        if not domain:
            return False
        return domain != self.internal_domain.lower()

    @staticmethod
    def is_automated(from_addr: str, from_name: str = "") -> bool:
        """True for non-human automated/system senders (no-reply, notifications,
        digests, platform alerts) that should never become an action item.

        Matched on address local-part + domain markers, so real people at
        external customer domains are NOT flagged.
        """
        addr = from_addr.strip().lower().strip("<>")
        local, _, domain = addr.partition("@")
        local_markers = (
            "no-reply",
            "noreply",
            "no_reply",
            "donotreply",
            "do-not-reply",
            "notification",  # covers notifications/notifications_*
            "notify",
            "mailer-daemon",
            "postmaster",
            "mailer",
            "automated",
            "alerts",
            "newsletter",
            "digest",
            "bounce",
            "-report",
            "reports",
            "office365reports",
        )
        if any(m in local for m in local_markers):
            return True
        domain_markers = (
            "mail.microsoft",
            "engage.mail",
            "updates.",
            "mailing.",
            "mailchimp",
            "sendgrid",
            "amazonses",
            "bounce",
        )
        return any(m in domain for m in domain_markers)

    def is_excluded(self, email: Email) -> bool:
        """True when the sender is automated OR matches a configured
        ``triage.exclude_senders`` substring (name or address)."""
        if self.is_automated(email.from_addr, email.from_name):
            return True
        haystack = f"{email.from_name}\n{email.from_addr}".lower()
        return any(token in haystack for token in self.exclude_senders)

    def score_content(self, subject: str, body: str) -> float:
        """Deterministic 0..1 content-signal heuristic.

        Scales with the number of distinct signal keywords present across the
        subject + body. Transparent and testable.
        """
        haystack = f"{subject}\n{body}".lower()
        hits = sum(1 for kw in _CONTENT_KEYWORDS if kw in haystack)
        if hits == 0:
            return 0.0
        # Two distinct signals saturates to HIGH; one signal lands mid-band.
        return min(1.0, 0.35 + 0.35 * hits)

    def evaluate(self, email: Email, body: str) -> ImportanceScore:
        """Deterministic eligibility gate.

        Qualifies when ANY of:
          - sender in extremely/very tier AND content is actionable (>0)
          - sender in also tier AND content is strong (>= threshold)
          - sender is a customer (external)
          - content is a HIGH escalation signal (>= threshold)
        """
        weight, decisive_prior, in_any_tier = self.score_sender(email)
        content = self.score_content(email.subject, body)
        excluded = self.is_excluded(email)
        customer = self.is_customer(email.from_addr) and not excluded
        escalation = content >= self.content_high_threshold

        high_tier = weight >= TIER_WEIGHTS["very_important"]
        also_tier = in_any_tier and not high_tier

        # Automated/excluded senders (notifications, daily digests, Google,
        # Miro, Office365 reports, …) never auto-qualify: a real customer must
        # carry content signal, and machine escalations are not human asks.
        qualifies = (
            (high_tier and content > 0.0)
            or (also_tier and content >= self.content_high_threshold)
            or (customer and content > 0.0)
            or (escalation and not excluded)
        )

        reasons: list[str] = []
        if high_tier and content > 0.0:
            reasons.append("high-tier sender with actionable content")
        if also_tier and content >= self.content_high_threshold:
            reasons.append("also-important sender with strong content")
        if customer and content > 0.0:
            reasons.append("external customer sender with content signal")
        if escalation and not excluded:
            reasons.append("high-signal escalation/decision content")
        if not reasons:
            if excluded:
                reasons.append("excluded automated/notification sender")
            else:
                reasons.append("no qualifying signal (low importance)")

        return ImportanceScore(
            sender_component=weight,
            content_component=content,
            customer_boost=customer,
            escalation_boost=escalation,
            decisive_prior=decisive_prior,
            qualifies=qualifies,
            reason="; ".join(reasons),
        )

    # ------------------------------------------------------------------ #
    # Step 4 — recall-biased body-fetch selector
    # ------------------------------------------------------------------ #
    def should_fetch_body(self, email: Email) -> bool:
        """Decide whether to fetch the body for an email.

        Always fetch for any listed sender or any customer (no subject gate).
        Otherwise apply a broad over-fetch-biased subject pre-scan. A declined
        fetch emits a DEBUG log naming the email id.
        """
        _, _, in_any_tier = self.score_sender(email)
        if in_any_tier:
            return True
        if self.is_excluded(email):
            logger.debug("triage pre-filter declined %s: excluded sender", email.id)
            return False
        if self.is_customer(email.from_addr):
            return True
        if self.score_content(email.subject, "") > 0.0:
            return True
        logger.debug("triage pre-filter declined %s: subject had no signal", email.id)
        return False

    # ------------------------------------------------------------------ #
    # Candidate surfacing — what the agent consumes to classify
    # ------------------------------------------------------------------ #
    def _canonical_folder(self, email: Email) -> str | None:
        """Best-effort canonical taxonomy folder via the Pipeline's inline
        rules classifier (lazily built). Returns None if rules don't match or are
        unavailable — it is advisory context, never a hard dependency."""
        if not self._pipeline_init:
            self._pipeline_init = True
            try:
                from .pipeline import Pipeline

                self._pipeline = Pipeline(self.config, self.cwd)
            except Exception as exc:  # noqa: BLE001 — canonical hint is optional
                logger.debug("rules pipeline unavailable for triage context: %s", exc)
                self._pipeline = None
        if self._pipeline is None:
            return None
        try:
            return self._pipeline.classify_with_rules(email)
        except Exception as exc:  # noqa: BLE001 — canonical hint is best-effort
            logger.debug("canonical classify failed for %s: %s", email.id, exc)
            return None

    def list_candidates(self, folder: str = "INBOX") -> list[TriageCandidate]:
        """List qualifying emails (with bodies) for the agent to classify.

        Lists the folder, applies the recall-biased body-fetch selector +
        deterministic gate, and returns ONLY the qualifying emails together
        with their fetched body. Per-email body-fetch errors are caught and
        logged; the email is then skipped (no body to classify against).
        """
        candidates: list[TriageCandidate] = []
        for email in list_emails(folder, cwd=self.cwd):
            if self.should_fetch_body(email):
                try:
                    body = read_message_body(email.id, email.folder, cwd=self.cwd)
                except Exception as exc:  # noqa: BLE001 — per-email skip-and-log
                    logger.warning("triage body fetch failed for %s: %s", email.id, exc)
                    continue
            else:
                body = ""

            score = self.evaluate(email, body)
            if not score.qualifies:
                continue

            canonical_folder = self._canonical_folder(email)

            candidates.append(
                TriageCandidate(
                    email_id=email.id,
                    from_name=email.from_name,
                    from_addr=email.from_addr,
                    subject=email.subject,
                    body=body,
                    reason=score.reason,
                    decisive_prior=score.decisive_prior,
                    canonical_folder=canonical_folder,
                )
            )
        return candidates

    # ------------------------------------------------------------------ #
    # Date resolution
    # ------------------------------------------------------------------ #
    def resolve_target_date(self, decision: CategoryDecision, email: Email) -> str:
        """Resolve a concrete 'YYYY-MM-DD' due date.

        Uses the decision's deadline when present; else falls back to the
        email's date. Raises ValueError when neither is usable.
        """
        if decision.deadline is not None:
            return decision.deadline.isoformat()
        if email.date is not None:
            return email.date.date().isoformat()
        raise ValueError("no usable deadline and email.date is missing")

    # ------------------------------------------------------------------ #
    # Task assembly + orchestration
    # ------------------------------------------------------------------ #
    def _resolve_marker(self, email: Email) -> str:
        """Stable dedup marker: Message-ID preferred, UID fallback."""
        message_id: str | None = None
        try:
            message_id = himalaya.read_message_id(email.id, email.folder, self.cwd)
        except Exception as exc:  # noqa: BLE001 — fall back to UID on any error
            logger.debug("read_message_id failed for %s: %s", email.id, exc)
        key = message_id or email.id
        return f"kontor-id:{key}"

    def _build_notes(
        self,
        email: Email,
        decision: CategoryDecision,
        marker: str,
    ) -> str:
        template = CATEGORY_TEMPLATES[decision.category]
        return (
            f"Sender: {email.from_addr}\n"
            f"Date: {email.date.isoformat()}\n"
            f"Email reference: {email.folder}/{email.id}\n"
            f"Rationale: {decision.rationale}\n\n"
            f"{template['standard_text']}\n\n"
            f"Done when: {template['done_when']}\n\n"
            f"<!-- {marker} -->"
        )

    def create_task_for(
        self,
        email: Email,
        decision: CategoryDecision,
        dry_run: bool,
    ) -> TriageDecision:
        """Orchestrate one agent-classified email → at-most-one Asana task.

        The agent has already gated + classified the email; this validates the
        supplied category, resolves the due date, assembles the task, and (when
        not a dry run) idempotently creates it. All date/Asana errors are caught
        here and converted into ``outcome="skipped_error"``; they never
        propagate.
        """
        # 1. Validate the agent-supplied category.
        if decision.category not in _VALID_CATEGORIES:
            logger.warning(
                "triage rejected invalid category %r for %s",
                decision.category,
                email.id,
            )
            return TriageDecision(
                email_id=email.id,
                qualifies=True,
                reason="agent-supplied",
                category=None,
                target_date=None,
                task_name=None,
                task_notes=None,
                outcome="skipped_error",
            )

        # 2. Deterministic date.
        try:
            target_date = self.resolve_target_date(decision, email)
        except ValueError as exc:
            logger.warning("triage date resolution failed for %s: %s", email.id, exc)
            return TriageDecision(
                email_id=email.id,
                qualifies=True,
                reason="agent-supplied",
                category=decision.category,
                target_date=None,
                task_name=None,
                task_notes=None,
                outcome="skipped_error",
            )

        # 3. Stable marker.
        marker = self._resolve_marker(email)

        # 4. Assemble name + notes.
        category_title = decision.category.replace("_", " ").title()
        task_name = f"[{category_title}] {email.subject}"
        task_notes = self._build_notes(email, decision, marker)

        # 5. Dry-run preview — no Asana calls.
        if dry_run:
            return TriageDecision(
                email_id=email.id,
                qualifies=True,
                reason="agent-supplied",
                category=decision.category,
                target_date=target_date,
                task_name=task_name,
                task_notes=task_notes,
                outcome="preview",
            )

        # 6. Dedup scoped to the ONE target project.
        target_project_gid = self.config.asana_project_gids[decision.category]
        try:
            if self.asana is None:
                raise AsanaError("Asana client not configured")
            if self.asana.find_task_by_marker(target_project_gid, marker):
                return TriageDecision(
                    email_id=email.id,
                    qualifies=True,
                    reason="agent-supplied",
                    category=decision.category,
                    target_date=target_date,
                    task_name=task_name,
                    task_notes=task_notes,
                    outcome="skipped_dedup",
                )
            # 7. Create.
            self.asana.create_task(
                target_project_gid, task_name, task_notes, target_date
            )
        except AsanaError as exc:
            logger.warning("triage Asana call failed for %s: %s", email.id, exc)
            return TriageDecision(
                email_id=email.id,
                qualifies=True,
                reason="agent-supplied",
                category=decision.category,
                target_date=target_date,
                task_name=task_name,
                task_notes=task_notes,
                outcome="skipped_error",
            )

        return TriageDecision(
            email_id=email.id,
            qualifies=True,
            reason="agent-supplied",
            category=decision.category,
            target_date=target_date,
            task_name=task_name,
            task_notes=task_notes,
            outcome="created",
        )
