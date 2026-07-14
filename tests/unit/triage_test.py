"""Unit tests for kontor_cli.triage."""

from __future__ import annotations

import logging
from datetime import date, datetime
from unittest import mock

import pytest

from kontor_cli.asana_client import AsanaError
from kontor_cli.config import Config
from kontor_cli.himalaya import Email
from kontor_cli.triage import (
    CATEGORY_TEMPLATES,
    CategoryDecision,
    Triage,
    TriageCandidate,
    TriageDecision,
)

INTERNAL = "rib-software.com"


def _make_config() -> Config:
    cfg = mock.MagicMock(spec=Config)
    cfg.asana_pat = "pat-test"
    cfg.asana_workspace_gid = "ws-1"
    cfg.asana_project_gids = {
        "information_gathering": "gid-info",
        "nudging": "gid-nudge",
        "being_the_example": "gid-example",
        "taking_decision": "gid-decide",
    }
    cfg.triage_internal_domain = INTERNAL
    cfg.triage_content_high_threshold = 0.6
    cfg.triage_exclude_senders = []
    cfg.triage_owner_email = "owner@rib-software.com"
    cfg.triage_sender_tiers = {
        "extremely_important": ["ceo@rib-software.com", "Big Boss"],
        "very_important": ["vp@rib-software.com", "Decisive Dan"],
        "also_important": ["lead@rib-software.com"],
    }
    return cfg


def _make_email(
    email_id: str = "42",
    from_addr: str = "someone@example.com",
    subject: str = "Hello there",
    date: datetime | None = None,
    folder: str = "INBOX",
    from_name: str = "",
) -> Email:
    return Email(
        id=email_id,
        from_addr=from_addr,
        from_name=from_name,
        subject=subject,
        date=date or datetime(2026, 6, 28, 9, 0, 0),
        flags={},
        folder=folder,
    )


def _make_triage(cfg: Config | None = None) -> Triage:
    return Triage(cfg or _make_config())


# --------------------------------------------------------------------------- #
# Step 3 — scoring + gate
# --------------------------------------------------------------------------- #
class TestScoringGate:
    def test_extremely_important_qualifies_on_actionable_content(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="ceo@rib-software.com", subject="urgent thing")
        score = t.evaluate(email, "please decide soon")
        assert score.qualifies
        assert score.sender_component == 1.0

    def test_very_important_sets_cat4_decisive_prior(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="vp@rib-software.com")
        weight, decisive, in_tier = t.score_sender(email)
        assert weight == 0.8
        assert decisive is True
        assert in_tier is True

    def test_also_important_needs_strong_content(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="lead@rib-software.com", subject="fyi update")
        weak = t.evaluate(email, "just a note")
        assert not weak.qualifies
        strong = t.evaluate(email, "urgent decision needed, please approve")
        assert strong.qualifies

    def test_unlisted_lowsignal_does_not_qualify(self) -> None:
        cfg = _make_config()
        cfg.triage_internal_domain = "example.com"  # make sender internal
        t = _make_triage(cfg)
        email = _make_email(from_addr="random@example.com", subject="lunch?")
        score = t.evaluate(email, "want to grab lunch tomorrow")
        assert not score.qualifies

    def test_external_domain_boosted(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="client@customer.com")
        # Real customer with content signal qualifies and is flagged a customer.
        score = t.evaluate(email, "please approve the contract")
        assert score.qualifies
        assert score.customer_boost is True
        # Bare external sender with no content signal does not qualify.
        assert not t.evaluate(email, "hi").qualifies

    def test_automated_external_sender_excluded(self) -> None:
        t = _make_triage()
        # Notification/automated senders never qualify, even with signal words.
        noreply = _make_email(
            from_addr="no-reply@teams.mail.microsoft", from_name="Teams"
        )
        score = t.evaluate(noreply, "urgent: please approve this escalation now")
        assert not score.qualifies
        assert t.is_excluded(noreply) is True

    def test_internal_domain_not_auto_boosted(self) -> None:
        t = _make_triage()
        assert t.is_customer("colleague@rib-software.com") is False
        assert t.is_customer("client@customer.com") is True

    def test_internal_colleague_asking_of_me_boosts(self) -> None:
        cfg = _make_config()
        t = _make_triage(cfg)
        email = _make_email(from_addr="peer@rib-software.com")
        # Internal sender, not in tiers — only content escalation can qualify.
        score = t.evaluate(email, "Can you please advise on this blocker? urgent")
        assert score.qualifies
        assert score.escalation_boost is True

    def test_escalation_keyword_qualifies_regardless_of_tier(self) -> None:
        cfg = _make_config()
        t = _make_triage(cfg)
        email = _make_email(from_addr="nobody@rib-software.com")
        score = t.evaluate(email, "ESCALATION: hypercare go-live blocker")
        assert score.qualifies
        assert score.escalation_boost is True

    def test_qualifies_when_listed_OR_customer_OR_high_content(self) -> None:  # noqa: N802
        t = _make_triage()
        # real customer WITH content signal qualifies
        assert t.evaluate(
            _make_email(from_addr="a@customer.com"), "please approve this"
        ).qualifies
        # bare external customer with NO content signal no longer qualifies
        assert not t.evaluate(_make_email(from_addr="a@customer.com"), "").qualifies
        # listed + content
        assert t.evaluate(
            _make_email(from_addr="ceo@rib-software.com"), "please approve"
        ).qualifies

    def test_name_and_address_matching(self) -> None:
        t = _make_triage()
        # Production shape: bare address in from_addr, display name in from_name.
        # Match by display name (address does not contain the name).
        by_name = _make_email(
            from_addr="unknown.person@rib-software.com", from_name="Big Boss"
        )
        _, _, in_tier_name = t.score_sender(by_name)
        assert in_tier_name is True
        # Match by address (no display name present at all).
        by_addr = _make_email(from_addr="ceo@rib-software.com", from_name="")
        weight, _, _ = t.score_sender(by_addr)
        assert weight == 1.0

    def test_named_sender_qualifies_extremely_important_tier(self) -> None:
        # Regression: a listed sender configured by DISPLAY NAME must match the
        # real envelope shape (bare address + separate display name) and land in
        # the extremely_important tier (weight 1.0) end-to-end.
        cfg = _make_config()
        cfg.triage_sender_tiers = {
            "extremely_important": ["Rolf Helmes"],
            "very_important": [],
            "also_important": [],
        }
        t = _make_triage(cfg)
        email = _make_email(
            from_addr="rolf.helmes@rib-software.com",
            from_name="Rolf Helmes",
            subject="please decide",
        )
        weight, decisive, in_tier = t.score_sender(email)
        assert in_tier is True
        assert weight == 1.0
        assert decisive is False
        score = t.evaluate(email, "please approve this decision")
        assert score.qualifies
        assert score.sender_component == 1.0


# --------------------------------------------------------------------------- #
# Step 4 — fetch selector
# --------------------------------------------------------------------------- #
class TestFetchSelector:
    def test_listed_sender_bypasses_subject_gate(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="ceo@rib-software.com", subject="nothing here")
        assert t.should_fetch_body(email) is True

    def test_customer_bypasses_subject_gate(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="x@customer.com", subject="nothing here")
        assert t.should_fetch_body(email) is True

    def test_unlisted_noncustomer_with_signal_subject_fetches(self) -> None:
        cfg = _make_config()
        t = _make_triage(cfg)
        email = _make_email(
            from_addr="peer@rib-software.com", subject="URGENT decision needed"
        )
        assert t.should_fetch_body(email) is True

    def test_unlisted_noncustomer_lowsignal_declines_and_logs_debug(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cfg = _make_config()
        t = _make_triage(cfg)
        email = _make_email(
            email_id="99", from_addr="peer@rib-software.com", subject="lunch plans"
        )
        # The "kontor_cli" parent logger may have propagate=False set by another
        # test's configure_logging(); attach caplog's handler to the triage
        # logger directly so capture is independent of parent state.
        triage_logger = logging.getLogger("kontor_cli.triage")
        triage_logger.addHandler(caplog.handler)
        prev_level = triage_logger.level
        triage_logger.setLevel(logging.DEBUG)
        try:
            with caplog.at_level(logging.DEBUG, logger="kontor_cli.triage"):
                assert t.should_fetch_body(email) is False
        finally:
            triage_logger.removeHandler(caplog.handler)
            triage_logger.setLevel(prev_level)
        assert "declined 99" in caplog.text


# --------------------------------------------------------------------------- #
# Candidate surfacing — what the agent consumes to classify
# --------------------------------------------------------------------------- #
class TestListCandidates:
    def test_only_qualifying_emails_returned_with_body(self) -> None:
        cfg = _make_config()
        cfg.triage_internal_domain = "example.com"
        t = _make_triage(cfg)
        qualifying = _make_email(
            email_id="1", from_addr="ceo@rib-software.com", subject="please approve"
        )
        skipped = _make_email(
            email_id="2", from_addr="rand@example.com", subject="lunch"
        )
        with (
            mock.patch(
                "kontor_cli.triage.list_emails", return_value=[qualifying, skipped]
            ),
            mock.patch(
                "kontor_cli.triage.read_message_body", return_value="please decide"
            ),
        ):
            candidates = t.list_candidates("INBOX")
        assert len(candidates) == 1
        c = candidates[0]
        assert isinstance(c, TriageCandidate)
        assert c.email_id == "1"
        assert c.body == "please decide"
        assert c.reason

    def test_body_fetch_error_skips_email_gracefully(self) -> None:
        t = _make_triage()
        email = _make_email(email_id="7", from_addr="ceo@rib-software.com")

        def boom(*_a: object, **_k: object) -> str:
            raise RuntimeError("fetch failed")

        with (
            mock.patch("kontor_cli.triage.list_emails", return_value=[email]),
            mock.patch("kontor_cli.triage.read_message_body", side_effect=boom),
        ):
            candidates = t.list_candidates("INBOX")
        assert candidates == []

    def test_decisive_prior_surfaced_on_candidate(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="vp@rib-software.com", subject="please decide")
        with (
            mock.patch("kontor_cli.triage.list_emails", return_value=[email]),
            mock.patch(
                "kontor_cli.triage.read_message_body", return_value="urgent decision"
            ),
        ):
            candidates = t.list_candidates("INBOX")
        assert len(candidates) == 1
        assert candidates[0].decisive_prior is True

    def test_canonical_folder_surfaced_on_candidate(self) -> None:
        t = _make_triage()
        # Inject a stub pipeline so the candidate carries the canonical
        # taxonomy folder as context for the agent's category judgment.
        t._pipeline_init = True
        t._pipeline = mock.MagicMock()
        t._pipeline.classify_with_rules.return_value = "2_Projects/PRJ_Willemen"
        email = _make_email(from_addr="vp@rib-software.com", subject="please decide")
        with (
            mock.patch("kontor_cli.triage.list_emails", return_value=[email]),
            mock.patch(
                "kontor_cli.triage.read_message_body", return_value="urgent decision"
            ),
        ):
            candidates = t.list_candidates("INBOX")
        assert len(candidates) == 1
        assert candidates[0].canonical_folder == "2_Projects/PRJ_Willemen"

    def test_canonical_folder_none_when_rules_unavailable(self) -> None:
        t = _make_triage()
        # Unavailable rule pipeline → canonical hint is best-effort, stays None.
        t._pipeline_init = True
        t._pipeline = None
        email = _make_email(from_addr="vp@rib-software.com", subject="please decide")
        with (
            mock.patch("kontor_cli.triage.list_emails", return_value=[email]),
            mock.patch(
                "kontor_cli.triage.read_message_body", return_value="urgent decision"
            ),
        ):
            candidates = t.list_candidates("INBOX")
        assert candidates[0].canonical_folder is None

    def test_canonical_folder_uses_inline_pipeline_classifier(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="vp@rib-software.com")
        pipeline = mock.MagicMock()
        pipeline.classify_with_rules.return_value = "2_Projects/PRJ_Willemen"

        with mock.patch("kontor_cli.pipeline.Pipeline", return_value=pipeline) as cls:
            assert t._canonical_folder(email) == "2_Projects/PRJ_Willemen"

        cls.assert_called_once_with(t.config, t.cwd)
        pipeline.classify_with_rules.assert_called_once_with(email)


# --------------------------------------------------------------------------- #
# Date resolution
# --------------------------------------------------------------------------- #
class TestDateResolution:
    def test_absolute_deadline_used(self) -> None:
        t = _make_triage()
        email = _make_email(date=datetime(2026, 6, 28))
        decision = CategoryDecision(
            category="nudging", deadline=date(2026, 7, 15), rationale="r"
        )
        assert t.resolve_target_date(decision, email) == "2026-07-15"

    def test_no_deadline_falls_back_to_email_date(self) -> None:
        t = _make_triage()
        email = _make_email(date=datetime(2026, 6, 28, 14, 0))
        decision = CategoryDecision(category="nudging", deadline=None, rationale="r")
        assert t.resolve_target_date(decision, email) == "2026-06-28"

    def test_unparseable_or_missing_email_date_raises(self) -> None:
        t = _make_triage()
        email = _make_email()
        email.date = None  # type: ignore[assignment]
        decision = CategoryDecision(category="nudging", deadline=None, rationale="r")
        with pytest.raises(ValueError):
            t.resolve_target_date(decision, email)


# --------------------------------------------------------------------------- #
# Orchestration — agent-supplied decision → Asana task
# --------------------------------------------------------------------------- #
class TestOrchestration:
    def _decision(
        self, category: str = "nudging", deadline: date | None = None
    ) -> CategoryDecision:
        return CategoryDecision(
            category=category, deadline=deadline, rationale="agent-supplied"
        )

    def test_create_task_for_dry_run_returns_preview_no_write(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        email = _make_email(from_addr="ceo@rib-software.com", subject="please approve")
        result = t.create_task_for(email, self._decision(), dry_run=True)
        assert result.outcome == "preview"
        t.asana.create_task.assert_not_called()
        assert result.task_name is not None

    def test_create_task_for_invalid_category_returns_skipped_error(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve")
        result = t.create_task_for(
            email, self._decision(category="nonsense"), dry_run=True
        )
        assert result.outcome == "skipped_error"
        assert result.category is None

    def test_dedup_hit_returns_skipped_dedup(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        t.asana.find_task_by_marker.return_value = True
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve please")
        with mock.patch(
            "kontor_cli.triage.himalaya.read_message_id", return_value="mid-1"
        ):
            result = t.create_task_for(email, self._decision(), dry_run=False)
        assert result.outcome == "skipped_dedup"
        # scoped to the one target project gid
        t.asana.find_task_by_marker.assert_called_once_with(
            "gid-nudge", "kontor-id:mid-1"
        )
        t.asana.create_task.assert_not_called()

    def test_marker_prefers_message_id_falls_back_to_uid(self) -> None:
        t = _make_triage()
        email = _make_email(email_id="uid-7")
        with mock.patch(
            "kontor_cli.triage.himalaya.read_message_id", return_value="msg-abc"
        ):
            assert t._resolve_marker(email) == "kontor-id:msg-abc"
        with mock.patch(
            "kontor_cli.triage.himalaya.read_message_id", return_value=None
        ):
            assert t._resolve_marker(email) == "kontor-id:uid-7"
        with mock.patch(
            "kontor_cli.triage.himalaya.read_message_id",
            side_effect=RuntimeError("x"),
        ):
            assert t._resolve_marker(email) == "kontor-id:uid-7"

    def test_task_notes_contain_sender_date_rationale_standardtext_dod(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        t.asana.find_task_by_marker.return_value = False
        email = _make_email(
            from_addr="ceo@rib-software.com",
            subject="approve",
            date=datetime(2026, 6, 28),
        )
        decision = CategoryDecision(
            category="nudging", deadline=None, rationale="needs a nudge"
        )
        with mock.patch(
            "kontor_cli.triage.himalaya.read_message_id", return_value="m1"
        ):
            t.create_task_for(email, decision, dry_run=False)
        notes = t.asana.create_task.call_args.args[2]
        assert "ceo@rib-software.com" in notes
        assert "2026-06-28" in notes
        assert "needs a nudge" in notes
        assert CATEGORY_TEMPLATES["nudging"]["standard_text"] in notes
        assert CATEGORY_TEMPLATES["nudging"]["done_when"] in notes
        assert "kontor-id:m1" in notes

    def test_task_name_format_bracket_category(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        t.asana.find_task_by_marker.return_value = False
        email = _make_email(from_addr="ceo@rib-software.com", subject="Quarterly sync")
        with mock.patch(
            "kontor_cli.triage.himalaya.read_message_id", return_value="m1"
        ):
            result = t.create_task_for(
                email, self._decision(category="taking_decision"), dry_run=False
            )
        assert result.task_name == "[Taking Decision] Quarterly sync"
        assert result.outcome == "created"

    def test_asana_error_propagates_for_real_write(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        t.asana.find_task_by_marker.return_value = False
        t.asana.create_task.side_effect = AsanaError("500")
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve")
        with mock.patch(
            "kontor_cli.triage.himalaya.read_message_id", return_value="m1"
        ):
            with pytest.raises(AsanaError, match="500"):
                t.create_task_for(email, self._decision(), dry_run=False)

    def test_none_client_raises_for_real_write(self) -> None:
        t = _make_triage()
        t.asana = None
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve")
        with mock.patch(
            "kontor_cli.triage.himalaya.read_message_id", return_value="m1"
        ):
            with pytest.raises(AsanaError, match="not configured"):
                t.create_task_for(email, self._decision(), dry_run=False)

    def test_date_resolution_failure_returns_skipped_error(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve")
        email.date = None  # type: ignore[assignment]
        result = t.create_task_for(email, self._decision(), dry_run=False)
        assert result.outcome == "skipped_error"
        assert result.target_date is None


def test_triage_decision_dataclass_shape() -> None:
    d = TriageDecision(
        email_id="1",
        qualifies=True,
        reason="r",
        category="nudging",
        target_date="2026-06-28",
        task_name="[Nudging] x",
        task_notes="notes",
        outcome="created",
    )
    assert d.outcome == "created"
