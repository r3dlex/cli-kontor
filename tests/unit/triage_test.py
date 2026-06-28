"""Unit tests for kontor_cli.triage."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from unittest import mock

import pytest

from kontor_cli.asana_client import AsanaError
from kontor_cli.config import Config
from kontor_cli.himalaya import Email
from kontor_cli.triage import (
    CATEGORY_TEMPLATES,
    CategoryDecision,
    Triage,
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
    cfg.triage_sender_tiers = {
        "extremely_important": ["ceo@rib-software.com", "Big Boss"],
        "very_important": ["vp@rib-software.com", "Decisive Dan"],
        "also_important": ["lead@rib-software.com"],
    }
    cfg.llm_base_url = "https://llm.test/v1"
    cfg.llm_api_key = "sk-test"
    cfg.llm_model = "test-model"
    cfg.llm_temperature = 0.0
    cfg.llm_timeout = 30
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


def _llm_response(category: str, deadline: object, rationale: str = "r") -> mock.Mock:
    payload = {"category": category, "deadline": deadline, "rationale": rationale}
    result = mock.MagicMock()
    result.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }
    result.raise_for_status = mock.MagicMock()
    return result


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
        score = t.evaluate(email, "hi")
        assert score.qualifies
        assert score.customer_boost is True

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
        # customer alone
        assert t.evaluate(_make_email(from_addr="a@customer.com"), "").qualifies
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
# Step 6 — LLM judgment + date
# --------------------------------------------------------------------------- #
class TestLLMJudgment:
    def test_llm_assigns_exactly_one_of_4_categories(self) -> None:
        t = _make_triage()
        email = _make_email()
        with mock.patch("httpx.post", return_value=_llm_response("nudging", None)):
            decision = t.judge_category(email, "body", decisive_prior=False)
        assert decision is not None
        assert decision.category == "nudging"
        assert decision.category in CATEGORY_TEMPLATES

    def test_decisive_prior_biases_toward_taking_decision(self) -> None:
        t = _make_triage()
        email = _make_email()
        with mock.patch(
            "httpx.post", return_value=_llm_response("taking_decision", None)
        ) as post:
            t.judge_category(email, "body", decisive_prior=True)
        sent = post.call_args.kwargs["json"]["messages"][0]["content"]
        assert "taking_decision" in sent
        assert "decisive" in sent.lower()

    def test_llm_failure_returns_none(self) -> None:
        import httpx

        t = _make_triage()
        with mock.patch("httpx.post", side_effect=httpx.RequestError("boom")):
            assert t.judge_category(_make_email(), "b", False) is None

    def test_llm_invalid_json_returns_none(self) -> None:
        t = _make_triage()
        bad = mock.MagicMock()
        bad.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
        bad.raise_for_status = mock.MagicMock()
        with mock.patch("httpx.post", return_value=bad):
            assert t.judge_category(_make_email(), "b", False) is None

    def test_llm_category_not_in_4_returns_none(self) -> None:
        t = _make_triage()
        with mock.patch("httpx.post", return_value=_llm_response("nonsense", None)):
            assert t.judge_category(_make_email(), "b", False) is None

    def test_date_llm_absolute_deadline_used(self) -> None:
        t = _make_triage()
        email = _make_email(date=datetime(2026, 6, 28))
        with mock.patch(
            "httpx.post", return_value=_llm_response("nudging", "2026-07-15")
        ):
            decision = t.judge_category(email, "b", False)
        assert decision is not None
        assert t.resolve_target_date(decision, email) == "2026-07-15"

    def test_date_no_deadline_falls_back_to_email_date(self) -> None:
        t = _make_triage()
        email = _make_email(date=datetime(2026, 6, 28, 14, 0))
        decision = CategoryDecision(category="nudging", deadline=None, rationale="r")
        assert t.resolve_target_date(decision, email) == "2026-06-28"

    def test_date_relative_phrase_parsed_via_dateutil_anchored_on_email_date(
        self,
    ) -> None:
        t = _make_triage()
        # email dated Sunday 2026-06-28; "Friday" anchored on that date.
        email = _make_email(date=datetime(2026, 6, 28))
        with mock.patch(
            "httpx.post", return_value=_llm_response("taking_decision", "Friday")
        ):
            decision = t.judge_category(email, "b", False)
        assert decision is not None
        assert decision.deadline is not None
        # dateutil resolves "Friday" anchored on 2026-06-28 → 2026-07-03.
        resolved = t.resolve_target_date(decision, email)
        assert resolved == "2026-07-03"

    def test_date_unparseable_or_missing_email_date_raises(self) -> None:
        t = _make_triage()
        email = _make_email()
        email.date = None  # type: ignore[assignment]
        decision = CategoryDecision(category="nudging", deadline=None, rationale="r")
        with pytest.raises(ValueError):
            t.resolve_target_date(decision, email)


# --------------------------------------------------------------------------- #
# Step 7 — orchestration
# --------------------------------------------------------------------------- #
class TestOrchestration:
    def test_maybe_create_task_dry_run_returns_preview_no_write(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        email = _make_email(from_addr="ceo@rib-software.com", subject="please approve")
        with mock.patch("httpx.post", return_value=_llm_response("nudging", None)):
            result = t.maybe_create_task(email, lambda e: "body decide", dry_run=True)
        assert result.outcome == "preview"
        t.asana.create_task.assert_not_called()
        assert result.task_name is not None

    def test_maybe_create_task_skips_when_not_qualified(self) -> None:
        cfg = _make_config()
        cfg.triage_internal_domain = "example.com"
        t = _make_triage(cfg)
        email = _make_email(from_addr="rand@example.com", subject="lunch")
        result = t.maybe_create_task(email, lambda e: "let's eat", dry_run=False)
        assert result.outcome == "not_qualified"

    def test_dedup_hit_returns_skipped_dedup(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        t.asana.find_task_by_marker.return_value = True
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve please")
        with (
            mock.patch("httpx.post", return_value=_llm_response("nudging", None)),
            mock.patch(
                "kontor_cli.triage.himalaya.read_message_id", return_value="mid-1"
            ),
        ):
            result = t.maybe_create_task(email, lambda e: "body", dry_run=False)
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
        with (
            mock.patch(
                "httpx.post",
                return_value=_llm_response("nudging", None, rationale="needs a nudge"),
            ),
            mock.patch("kontor_cli.triage.himalaya.read_message_id", return_value="m1"),
        ):
            t.maybe_create_task(email, lambda e: "please approve", dry_run=False)
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
        with (
            mock.patch(
                "httpx.post", return_value=_llm_response("taking_decision", None)
            ),
            mock.patch("kontor_cli.triage.himalaya.read_message_id", return_value="m1"),
        ):
            result = t.maybe_create_task(email, lambda e: "decide", dry_run=False)
        assert result.task_name == "[Taking Decision] Quarterly sync"
        assert result.outcome == "created"

    def test_asana_error_returns_skipped_error(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        t.asana.find_task_by_marker.return_value = False
        t.asana.create_task.side_effect = AsanaError("500")
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve")
        with (
            mock.patch("httpx.post", return_value=_llm_response("nudging", None)),
            mock.patch("kontor_cli.triage.himalaya.read_message_id", return_value="m1"),
        ):
            result = t.maybe_create_task(email, lambda e: "b", dry_run=False)
        assert result.outcome == "skipped_error"

    def test_llm_none_returns_skipped_error(self) -> None:
        import httpx

        t = _make_triage()
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve")
        with mock.patch("httpx.post", side_effect=httpx.RequestError("x")):
            result = t.maybe_create_task(email, lambda e: "b", dry_run=False)
        assert result.outcome == "skipped_error"
        assert result.category is None

    def test_body_fetch_fail_returns_skipped_error(self) -> None:
        t = _make_triage()
        email = _make_email(from_addr="ceo@rib-software.com")

        def boom(_e: Email) -> str:
            raise RuntimeError("fetch failed")

        result = t.maybe_create_task(email, boom, dry_run=False)
        assert result.outcome == "skipped_error"

    def test_partial_run_resume_skips_already_created_via_marker(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        t.asana.find_task_by_marker.return_value = True
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve")
        with (
            mock.patch("httpx.post", return_value=_llm_response("nudging", None)),
            mock.patch("kontor_cli.triage.himalaya.read_message_id", return_value="m1"),
        ):
            result = t.maybe_create_task(email, lambda e: "b", dry_run=False)
        assert result.outcome == "skipped_dedup"
        t.asana.create_task.assert_not_called()

    def test_date_resolution_failure_returns_skipped_error(self) -> None:
        t = _make_triage()
        t.asana = mock.MagicMock()
        email = _make_email(from_addr="ceo@rib-software.com", subject="approve")
        email.date = None  # type: ignore[assignment]
        with mock.patch("httpx.post", return_value=_llm_response("nudging", None)):
            result = t.maybe_create_task(email, lambda e: "b", dry_run=False)
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
