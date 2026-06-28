"""Email → Asana management-action triage.

Deterministic importance scoring, recall-biased body-fetch selection, one
mocked LLM boundary for category + deadline judgment, and idempotent task
creation orchestration. All per-email LLM/Asana/date/body errors are caught
inside ``maybe_create_task`` and turned into ``outcome="skipped_error"`` — they
never propagate.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from dateutil import parser as date_parser

from . import himalaya
from .asana_client import AsanaClient, AsanaError

if TYPE_CHECKING:
    from .config import Config
    from .himalaya import Email

logger = logging.getLogger(__name__)

# Sender-tier weights for the deterministic importance component.
TIER_WEIGHTS: dict[str, float] = {
    "extremely_important": 1.0,
    "very_important": 0.8,
    "also_important": 0.5,
}

# Broad subject-keyword pre-scan for the unlisted/non-customer remainder.
# Over-fetch biased (recall over precision); the LLM is the precision filter.
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
    """LLM judgment of category + (optional) deadline for a qualifying email."""

    category: str
    deadline: date | None
    rationale: str


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
        self.tiers = config.triage_sender_tiers
        self.internal_domain = config.triage_internal_domain
        self.content_high_threshold = config.triage_content_high_threshold
        # Decisive senders bias the LLM toward taking_decision (soft, not forced).
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
        customer = self.is_customer(email.from_addr)
        escalation = content >= self.content_high_threshold

        high_tier = weight >= TIER_WEIGHTS["very_important"]
        also_tier = in_any_tier and not high_tier

        qualifies = (
            (high_tier and content > 0.0)
            or (also_tier and content >= self.content_high_threshold)
            or customer
            or escalation
        )

        reasons: list[str] = []
        if high_tier and content > 0.0:
            reasons.append("high-tier sender with actionable content")
        if also_tier and content >= self.content_high_threshold:
            reasons.append("also-important sender with strong content")
        if customer:
            reasons.append("external customer sender")
        if escalation:
            reasons.append("high-signal escalation/decision content")
        if not reasons:
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
        if in_any_tier or self.is_customer(email.from_addr):
            return True
        if self.score_content(email.subject, "") > 0.0:
            return True
        logger.debug("triage pre-filter declined %s: subject had no signal", email.id)
        return False

    # ------------------------------------------------------------------ #
    # Step 6 — LLM category + deadline judgment + deterministic date
    # ------------------------------------------------------------------ #
    def judge_category(
        self, email: Email, body: str, decisive_prior: bool
    ) -> CategoryDecision | None:
        """One LLM call returning ``{category, deadline, rationale}``.

        Returns None on any HTTP/parse/validation error (e.g. category not in
        the 4 slugs).
        """
        bias = ""
        if decisive_prior:
            bias = (
                " The sender is a decisive stakeholder; softly favor "
                "'taking_decision' when the content is genuinely a decision, "
                "but do not force it."
            )
        rubric = (
            "Categorize this email into exactly ONE management-action slug:\n"
            "- information_gathering: observe & collect a signal, no action yet.\n"
            "- nudging: subtly steer someone toward a better outcome.\n"
            "- being_the_example: model a habit/standard/boundary visibly.\n"
            "- taking_decision: a decision is required of the reader." + bias
        )
        date_str = email.date.isoformat() if email.date is not None else "unknown"
        user_prompt = (
            f"{rubric}\n\n"
            f"From: {email.from_addr}\n"
            f"Subject: {email.subject}\n"
            f"Date: {date_str}\n\n"
            f"Body:\n{body}\n\n"
            "Respond with STRICT JSON only: "
            '{"category": "<one of the 4 slugs>", '
            '"deadline": "<ISO date or relative phrase or null>", '
            '"rationale": "<short reason>"}'
        )

        try:
            response = httpx.post(
                f"{self.config.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.llm_model,
                    "messages": [
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": self.config.llm_temperature,
                },
                timeout=self.config.llm_timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "triage LLM returned %s for %s",
                exc.response.status_code,
                email.id,
            )
            return None
        except httpx.RequestError as exc:
            logger.error("triage LLM request failed for %s: %s", email.id, exc)
            return None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if content.strip().startswith("```"):
                content = content.strip()[content.strip().find("\n") + 1 :]
                if content.endswith("```"):
                    content = content[:-3].strip()
            parsed: dict[str, Any] = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.error("triage LLM parse failed for %s: %r", email.id, exc)
            return None

        category = parsed.get("category")
        if category not in _VALID_CATEGORIES:
            logger.error(
                "triage LLM returned invalid category %r for %s", category, email.id
            )
            return None

        deadline_raw = parsed.get("deadline")
        deadline: date | None = None
        if deadline_raw:
            try:
                anchor = email.date if email.date is not None else None
                deadline = (
                    date_parser.parse(str(deadline_raw), default=anchor).date()
                    if anchor is not None
                    else date_parser.parse(str(deadline_raw)).date()
                )
            except (ValueError, OverflowError, TypeError):
                # Keep the raw phrase out; resolve_target_date falls back.
                deadline = None

        return CategoryDecision(
            category=str(category),
            deadline=deadline,
            rationale=str(parsed.get("rationale", "")),
        )

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
    # Step 7 — task assembly + orchestration
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

    def maybe_create_task(
        self,
        email: Email,
        body_fetcher: Callable[[Email], str],
        dry_run: bool,
    ) -> TriageDecision:
        """Orchestrate one email → at-most-one idempotent Asana task.

        All LLM/Asana/date/body errors are caught here and converted into
        ``outcome="skipped_error"``; they never propagate.
        """
        # 1. Body (recall-biased selector).
        if self.should_fetch_body(email):
            try:
                body = body_fetcher(email)
            except Exception as exc:  # noqa: BLE001 — per-email skip-and-log
                logger.warning("triage body fetch failed for %s: %s", email.id, exc)
                return TriageDecision(
                    email_id=email.id,
                    qualifies=False,
                    reason="body fetch failed",
                    category=None,
                    target_date=None,
                    task_name=None,
                    task_notes=None,
                    outcome="skipped_error",
                )
        else:
            body = ""

        # 2. Deterministic gate.
        score = self.evaluate(email, body)
        if not score.qualifies:
            return TriageDecision(
                email_id=email.id,
                qualifies=False,
                reason=score.reason,
                category=None,
                target_date=None,
                task_name=None,
                task_notes=None,
                outcome="not_qualified",
            )

        # 3. LLM category judgment.
        decision = self.judge_category(email, body, score.decisive_prior)
        if decision is None:
            logger.warning("triage LLM produced no decision for %s", email.id)
            return TriageDecision(
                email_id=email.id,
                qualifies=True,
                reason=score.reason,
                category=None,
                target_date=None,
                task_name=None,
                task_notes=None,
                outcome="skipped_error",
            )

        # 4. Deterministic date.
        try:
            target_date = self.resolve_target_date(decision, email)
        except ValueError as exc:
            logger.warning("triage date resolution failed for %s: %s", email.id, exc)
            return TriageDecision(
                email_id=email.id,
                qualifies=True,
                reason=score.reason,
                category=decision.category,
                target_date=None,
                task_name=None,
                task_notes=None,
                outcome="skipped_error",
            )

        # 5. Stable marker.
        marker = self._resolve_marker(email)

        # 6. Assemble name + notes.
        category_title = decision.category.replace("_", " ").title()
        task_name = f"[{category_title}] {email.subject}"
        task_notes = self._build_notes(email, decision, marker)

        # 7. Dry-run preview — no Asana calls.
        if dry_run:
            return TriageDecision(
                email_id=email.id,
                qualifies=True,
                reason=score.reason,
                category=decision.category,
                target_date=target_date,
                task_name=task_name,
                task_notes=task_notes,
                outcome="preview",
            )

        # 8. Dedup scoped to the ONE target project.
        target_project_gid = self.config.asana_project_gids[decision.category]
        try:
            if self.asana is None:
                raise AsanaError("Asana client not configured")
            if self.asana.find_task_by_marker(target_project_gid, marker):
                return TriageDecision(
                    email_id=email.id,
                    qualifies=True,
                    reason=score.reason,
                    category=decision.category,
                    target_date=target_date,
                    task_name=task_name,
                    task_notes=task_notes,
                    outcome="skipped_dedup",
                )
            # 9. Create.
            self.asana.create_task(
                target_project_gid, task_name, task_notes, target_date
            )
        except AsanaError as exc:
            logger.warning("triage Asana call failed for %s: %s", email.id, exc)
            return TriageDecision(
                email_id=email.id,
                qualifies=True,
                reason=score.reason,
                category=decision.category,
                target_date=target_date,
                task_name=task_name,
                task_notes=task_notes,
                outcome="skipped_error",
            )

        return TriageDecision(
            email_id=email.id,
            qualifies=True,
            reason=score.reason,
            category=decision.category,
            target_date=target_date,
            task_name=task_name,
            task_notes=task_notes,
            outcome="created",
        )
