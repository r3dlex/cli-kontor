"""Pipeline orchestrator — Rebuild, Realtime, and Heal phases."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kontor_cli.classifier import ClassificationResult, Classifier
from kontor_cli.config import Config
from kontor_cli.folders import (
    FolderPolicy,
    is_valid_folder,
)
from kontor_cli.himalaya import (
    Email,
    HimalayaError,
    create_folder,
    list_emails,
    move_email,
    read_message_body,
)
from kontor_cli.rules import nl_rules, python_rules, yaml_dsl
from kontor_cli.triage import Triage

logger = logging.getLogger("kontor_cli.pipeline")

# Scan scope for the Rebuild and Heal phases: every live taxonomy folder
# plus legacy folders that still hold unprocessed emails.
SCAN_FOLDERS = (
    "INBOX",
    "0_Action",
    "1_Management",
    "1_Management/1on1",
    "1_Management/HR",
    "1_Management/Leadership",
    "2_Projects",
    "2_Projects/Internal",
    "2_Projects/Willemen",
    "2_Projects/Eiffage",
    "2_Projects/Vinci",
    "2_Projects/Budimex",
    "2_Projects/Releases",
    "2_Projects/RIB-4.0/AI",
    "2_Projects/Augment",
    "2_Projects/AzureSigning",
    "2_Projects/Development",
    "2_Projects/China",
    "2_Projects/Trivium",
    "2_Projects/Sales_BoQ_Estimate_Procurement",
    "2_Projects/Security",
    "2_Projects/Finance",
    "2_Projects/Infrastructure",
    "3_External",
    "3_External/Trivium",
    "3_External/Miro",
    "3_External/GitHub",
    "3_External/Mitarbeiterangebote",
    "3_External/Reportlinker",
    "3_External/CoachHub",
    "3_External/Viseo",
    "3_External/HeroDevs",
    "3_External/Microsoft",
    "4_Info",
    "9_System",
    # Legacy folders (still have unprocessed emails)
    "Projects",
    "Executive",
    "Admin",
    "Finance",
    "HR",
    "Releases",
    "Security",
    "Travel",
    "Newsletters",
    "Logs",
    "Review",
    "Communication",
)


class Pipeline:
    """Base pipeline with shared infrastructure."""

    def __init__(self, config: Config, cwd: Path | None = None) -> None:
        self.config = config
        self.cwd = cwd
        # Rule sources, evaluated in priority order by classify_with_rules().
        self.yaml_rules = yaml_dsl.load_rules_from_dir(config.rules_yaml_dir)
        self.python_rules_ns = python_rules.load_python_rules(config.rules_python_file)
        self.nl_rules = nl_rules.load_nl_rules(config.rules_nl_dir)
        self.classifier = Classifier(config)
        self.folder_policy = FolderPolicy(config.pipeline_archive_months)
        self.move_history: set[tuple[str, str]] = set()  # (email_id, folder)
        self.moves_made = 0
        self.skipped_already_correct = 0
        self.skipped_loop = 0
        self.llm_failures = 0
        self._created_folders: set[str] = set()  # cache of folders already created

        # Email → Asana triage (Step 8). Only constructed when enabled.
        self.triage = Triage(config, cwd) if config.triage_enabled else None
        self.triage_tasks_created = 0
        self.triage_skipped_dedup = 0
        self.triage_skipped_errors = 0
        self._triage_validated = False  # validate_projects() runs at most once

    def _validate_triage_projects(self, dry_run: bool, triage_scope: bool) -> None:
        """Validate Asana projects once, up-front, before processing emails.

        Loud fail-fast: an AsanaError here aborts the whole run. Skipped in
        dry-run, when triage is disabled/out-of-scope, or when already run.
        """
        if self.triage is None or not triage_scope or dry_run:
            return
        if self._triage_validated:
            return
        self._triage_validated = True
        if self.triage.asana is not None:
            self.triage.asana.validate_projects()

    def _ensure_folder(self, folder: str) -> None:
        """Ensure a folder exists. Creates it if valid and missing."""
        if folder in self._created_folders:
            return
        if not is_valid_folder(folder):
            logger.warning(f"Skipping invalid folder creation: {folder}")
            return
        try:
            create_folder(folder, cwd=self.cwd)
            self._created_folders.add(folder)
            logger.info(f"Created folder: {folder}")
        except HimalayaError:
            self._created_folders.add(folder)
            pass

    def classify_with_rules(self, email: Email) -> str | None:
        """Classify an email through all three rule sources.

        Priority: YAML DSL > Python module > NL rules (best-effort).
        NL rules return None — they require LLM context.
        """
        # 1. YAML DSL
        yaml_result: str | None = yaml_dsl.evaluate_yaml_rules(
            self.yaml_rules,
            email.from_addr,
            email.subject,
        )
        if yaml_result is not None:
            logger.info(
                "YAML rule matched",
                extra={
                    "email_id": email.id,
                    "rule_source": "yaml_dsl",
                    "folder": yaml_result,
                },
            )
            return yaml_result

        # 2. Python module
        py_result: str | None = python_rules.call_python_rules(
            self.python_rules_ns, email
        )
        if py_result is not None:
            logger.info(
                "Python rule matched",
                extra={
                    "email_id": email.id,
                    "rule_source": "python_rules",
                    "folder": py_result,
                },
            )
            return py_result

        # 3. NL rules — no direct match; requires LLM
        if self.nl_rules:
            logger.info(
                "No YAML or Python match; NL rules available for LLM context",
                extra={
                    "email_id": email.id,
                    "rule_source": "nl_rules",
                },
            )
        return None

    def _classify(self, email: Email) -> str | None:
        """Classify via the rules; fall back to the LLM when no rule matches."""
        classified = self.classify_with_rules(email)
        if classified is not None:
            return classified
        result = self._llm_classify(email)
        return result.folder if result else None

    def _process_email(
        self, email: Email, dry_run: bool = False, triage_scope: bool = False
    ) -> str | None:
        """Process a single email: classify → decide target folder → move.

        ``triage_scope`` enables content-driven email → Asana triage for this
        phase (realtime always; rebuild only when configured; heal never).
        """
        current_folder = email.folder

        # Step 1: classify (rules, then LLM fallback) and decide the target
        target = self.folder_policy.target_for(email.date, self._classify(email))

        # Step 1b: content-driven triage — fires on the classified email
        # regardless of the move outcome below (loop-skip / already-correct /
        # move failure all still triage). A triage bug must NEVER break the
        # move loop, so everything here is defensively contained.
        if self.triage is not None and triage_scope:
            try:
                decision = self.triage.maybe_create_task(
                    email,
                    body_fetcher=lambda e: read_message_body(
                        e.id, e.folder, cwd=self.cwd
                    ),
                    dry_run=dry_run,
                )
                if decision.outcome == "created":
                    self.triage_tasks_created += 1
                elif decision.outcome == "skipped_dedup":
                    self.triage_skipped_dedup += 1
                elif decision.outcome == "skipped_error":
                    self.triage_skipped_errors += 1
            except Exception:
                logger.exception(
                    f"Triage failed for email {email.id}",
                    extra={"email_id": email.id},
                )
                self.triage_skipped_errors += 1

        # Step 2: Loop prevention
        if (email.id, target) in self.move_history:
            self.skipped_loop += 1
            logger.info(
                f"Skipping email {email.id} — already scheduled for {target}",
                extra={"email_id": email.id},
            )
            return None
        self.move_history.add((email.id, target))

        # Step 3: Already in correct folder
        if current_folder == target:
            self.skipped_already_correct += 1
            logger.debug(
                f"Email {email.id} already in correct folder: {target}",
                extra={"email_id": email.id},
            )
            return target

        # Step 4: Dry run
        if dry_run:
            logger.info(
                f"[DRY-RUN] Would move email {email.id} from {current_folder} to {target}",
                extra={
                    "email_id": email.id,
                    "folder": target,
                    "moves_made": self.moves_made,
                },
            )
            return target

        # Step 5: Move the email
        try:
            self._ensure_folder(target)
            move_email(email.id, current_folder, target, cwd=self.cwd)
            self.moves_made += 1
            logger.info(
                f"Moved email {email.id} from {current_folder} to {target}",
                extra={
                    "email_id": email.id,
                    "folder": target,
                    "moves_made": self.moves_made,
                },
            )
        except HimalayaError as exc:
            if "not found" in str(exc).lower():
                # Target folder does not exist in Exchange — skip gracefully
                logger.warning(
                    f"Skipping email {email.id}: target folder '{target}' not found in Exchange",
                    extra={"email_id": email.id, "folder": target},
                )
            else:
                logger.error(
                    f"Failed to move email {email.id}: {exc}",
                    extra={"email_id": email.id},
                )

        return target

    def _llm_classify(self, email: Email) -> ClassificationResult | None:
        """Classify via LLM with retry and failure tracking."""
        nl_context = nl_rules.nl_rules_context(self.nl_rules)
        result = self.classifier.classify(email, rules_context=nl_context)
        if result is None:
            self.llm_failures += 1
            if self.llm_failures >= self.config.pipeline_llm_failure_alert:
                logger.warning(
                    f"LLM failure threshold reached: {self.llm_failures} consecutive failures",
                )
        else:
            self.llm_failures = 0
            self._handle_llm_decision(email, result)
        return result

    def _handle_llm_decision(self, email: Email, result: ClassificationResult) -> None:
        """Handle LLM action: adjust/create rule, or log."""
        evolved_dir = Path(self.config.rules_evolved_dir)
        evolved_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        log_file = evolved_dir / f"{timestamp}_rule_adjustments.json"

        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "email_id": email.id,
            "subject": email.subject,
            "from": email.from_addr,
            "folder": result.folder,
            "confidence": result.confidence,
            "action": result.action,
        }

        try:
            with open(log_file, "w") as fh:
                json.dump(entry, fh, indent=2)
            logger.info(
                f"Logged LLM rule decision to {log_file.name}",
                extra={
                    "email_id": email.id,
                    "llm_action": result.action,
                    "folder": result.folder,
                },
            )
        except OSError as exc:
            logger.error(f"Failed to write evolved rule log: {exc}")

    def _summary(self, phase: str, total: int) -> dict[str, int | str]:
        """Build the standard per-phase log summary.

        Shared by Rebuild and Realtime phases (Heal uses an inline dict with
        different fields — see `HealPipeline.run`).
        """
        s: dict[str, int | str] = {
            "phase": phase,
            "total_processed": total,
            "moves_made": self.moves_made,
            "skipped_already_correct": self.skipped_already_correct,
            "skipped_loop": self.skipped_loop,
            "llm_failures": self.llm_failures,
            "triage_tasks_created": self.triage_tasks_created,
            "triage_skipped_dedup": self.triage_skipped_dedup,
            "triage_skipped_errors": self.triage_skipped_errors,
        }
        logger.info(f"Phase {phase} complete", extra={**s, "phase": phase})
        return s


class RebuildPipeline(Pipeline):
    """Phase 1 — Historical Rebuild: process all emails in all non-Archive folders."""

    def run(self, dry_run: bool = False) -> dict[str, Any]:
        logger.info("Starting Historical Rebuild", extra={"phase": "rebuild"})
        triage_scope = self.config.triage_scan_rebuild
        self._validate_triage_projects(dry_run, triage_scope)
        total_processed = 0
        for folder in SCAN_FOLDERS:
            try:
                emails = list_emails(folder, cwd=self.cwd)
            except HimalayaError as exc:
                logger.warning(f"Could not list folder {folder}: {exc}")
                continue

            for email in emails:
                self._process_email(email, dry_run=dry_run, triage_scope=triage_scope)
                total_processed += 1

        return self._summary("rebuild", total_processed)


class RealtimePipeline(Pipeline):
    """Phase 2 — Real-Time Processing: process only Inbox emails."""

    def run(self, dry_run: bool = False) -> dict[str, Any]:
        logger.info("Starting Real-Time Processing", extra={"phase": "realtime"})
        self._validate_triage_projects(dry_run, triage_scope=True)
        try:
            emails = list_emails("INBOX", cwd=self.cwd)
        except HimalayaError as exc:
            logger.error(f"Could not list INBOX: {exc}")
            return {"phase": "realtime", "error": str(exc)}

        total = 0
        for email in emails:
            self._process_email(email, dry_run=dry_run, triage_scope=True)
            total += 1

        return self._summary("realtime", total)


class HealPipeline(Pipeline):
    """Phase 3 — Self-Healing Loop: scan all folders for invariant violations."""

    def run(self, dry_run: bool = False) -> dict[str, int | str]:
        logger.info("Starting Self-Healing Loop", extra={"phase": "heal"})
        total = 0
        violations_found = 0
        violations_fixed = 0

        for folder in SCAN_FOLDERS:
            try:
                emails = list_emails(folder, cwd=self.cwd)
            except HimalayaError:
                continue

            for email in emails:
                total += 1
                classified = self.classify_with_rules(email)
                target = self.folder_policy.target_for(email.date, classified)

                # Violation: email should be in Archive (too old) but isn't
                if target.startswith("Archive/"):
                    violations_found += 1
                    self._process_email(email, dry_run=dry_run)
                    if not dry_run:
                        violations_fixed += 1
                    continue

                # Violation: target is different from current folder (wrongly placed)
                if target != folder:
                    violations_found += 1
                    self._process_email(email, dry_run=dry_run)
                    if not dry_run:
                        violations_fixed += 1

        s: dict[str, int | str] = {
            "phase": "heal",
            "emails_scanned": total,
            "violations_found": violations_found,
            "violations_fixed": violations_fixed if not dry_run else 0,
            "moves_made": self.moves_made,
        }
        logger.info("Heal phase complete", extra={**s, "phase": "heal"})
        return s
