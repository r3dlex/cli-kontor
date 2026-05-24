"""Pipeline orchestrator — Rebuild, Realtime, and Heal phases."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from kontor_cli.classifier import ClassificationResult, Classifier
from kontor_cli.config import Config
from kontor_cli.folders import (
    get_target_for_email,
    is_valid_folder,
)
from kontor_cli.himalaya import (
    Email,
    HimalayaError,
    create_folder,
    list_emails,
    move_email,
)
from kontor_cli.rules_engine import RulesEngine

logger = logging.getLogger("kontor_cli.pipeline")


class Pipeline:
    """Base pipeline with shared infrastructure."""

    def __init__(self, config: Config, cwd: Path | None = None) -> None:
        self.config = config
        self.cwd = cwd
        self.rules_engine = RulesEngine(config, cwd)
        self.classifier = Classifier(config)
        self.move_history: set[tuple[str, str]] = set()  # (email_id, folder)
        self.moves_made = 0
        self.skipped_already_correct = 0
        self.skipped_loop = 0
        self.llm_failures = 0
        self._created_folders: set[str] = set()  # cache of folders already created

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

    def _process_email(self, email: Email, dry_run: bool = False) -> str | None:
        """Process a single email: classify → enforce archive → move."""
        current_folder = email.folder

        # Step 1: rules engine classification
        classified = self.rules_engine.classify(email)
        target = get_target_for_email(
            email.date,
            classified,
            archive_age_months=self.config.pipeline_archive_months,
        )

        # Step 2: If no rule matched, fall back to LLM
        if classified is None:
            result = self._llm_classify(email)
            if result:
                target = get_target_for_email(
                    email.date,
                    result.folder,
                    archive_age_months=self.config.pipeline_archive_months,
                )
            else:
                target = "4_Info"

        # Step 3: Loop prevention
        if (email.id, target) in self.move_history:
            self.skipped_loop += 1
            logger.info(
                f"Skipping email {email.id} — already scheduled for {target}",
                extra={"email_id": email.id},
            )
            return None
        self.move_history.add((email.id, target))

        # Step 4: Already in correct folder
        if current_folder == target:
            self.skipped_already_correct += 1
            logger.debug(
                f"Email {email.id} already in correct folder: {target}",
                extra={"email_id": email.id},
            )
            return target  # type: ignore[no-any-return]

        # Step 5: Dry run
        if dry_run:
            logger.info(
                f"[DRY-RUN] Would move email {email.id} from {current_folder} to {target}",
                extra={
                    "email_id": email.id,
                    "folder": target,
                    "moves_made": self.moves_made,
                },
            )
            return target  # type: ignore[no-any-return]

        # Step 6: Move the email
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
            logger.error(
                f"Failed to move email {email.id}: {exc}", extra={"email_id": email.id}
            )

        return target  # type: ignore[no-any-return]

    def _llm_classify(self, email: Email) -> ClassificationResult | None:
        """Classify via LLM with retry and failure tracking."""
        nl_context = self.rules_engine.get_nl_context()
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


class RebuildPipeline(Pipeline):
    """Phase 1 — Historical Rebuild: process all emails in all non-Archive folders."""

    def run(self, dry_run: bool = False) -> dict:
        logger.info("Starting Historical Rebuild", extra={"phase": "rebuild"})
        total_processed = 0
        folders = [
            "INBOX",
            "0_Action",
            "1_Management",
            "2_Projects",
            "3_External",
            "4_Info",
            "9_System",
        ]

        for folder in folders:
            try:
                emails = list_emails(folder, cwd=self.cwd)
            except HimalayaError as exc:
                logger.warning(f"Could not list folder {folder}: {exc}")
                continue

            for email in emails:
                self._process_email(email, dry_run=dry_run)
                total_processed += 1

        return self._summary("rebuild", total_processed)

    def _summary(self, phase: str, total: int) -> dict:
        s = {
            "phase": phase,
            "total_processed": total,
            "moves_made": self.moves_made,
            "skipped_already_correct": self.skipped_already_correct,
            "skipped_loop": self.skipped_loop,
            "llm_failures": self.llm_failures,
        }
        logger.info(f"Phase {phase} complete", extra={**s, "phase": phase})
        return s


class RealtimePipeline(Pipeline):
    """Phase 2 — Real-Time Processing: process only Inbox emails."""

    def run(self, dry_run: bool = False) -> dict:
        logger.info("Starting Real-Time Processing", extra={"phase": "realtime"})
        try:
            emails = list_emails("INBOX", cwd=self.cwd)
        except HimalayaError as exc:
            logger.error(f"Could not list INBOX: {exc}")
            return {"phase": "realtime", "error": str(exc)}

        total = 0
        for email in emails:
            self._process_email(email, dry_run=dry_run)
            total += 1

        return self._summary("realtime", total)

    def _summary(self, phase: str, total: int) -> dict:
        s = {
            "phase": phase,
            "total_processed": total,
            "moves_made": self.moves_made,
            "skipped_already_correct": self.skipped_already_correct,
            "skipped_loop": self.skipped_loop,
            "llm_failures": self.llm_failures,
        }
        logger.info(f"Phase {phase} complete", extra={**s, "phase": phase})
        return s


class HealPipeline(Pipeline):
    """Phase 3 — Self-Healing Loop: scan all folders for invariant violations."""

    def run(self, dry_run: bool = False) -> dict:
        logger.info("Starting Self-Healing Loop", extra={"phase": "heal"})
        folders = [
            "INBOX",
            "0_Action",
            "1_Management",
            "2_Projects",
            "3_External",
            "4_Info",
            "9_System",
        ]

        total = 0
        violations_found = 0
        violations_fixed = 0

        for folder in folders:
            try:
                emails = list_emails(folder, cwd=self.cwd)
            except HimalayaError:
                continue

            for email in emails:
                total += 1
                classified = self.rules_engine.classify(email)
                target = get_target_for_email(
                    email.date,
                    classified,
                    archive_age_months=self.config.pipeline_archive_months,
                )

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

        s = {
            "phase": "heal",
            "emails_scanned": total,
            "violations_found": violations_found,
            "violations_fixed": violations_fixed if not dry_run else 0,
            "moves_made": self.moves_made,
        }
        logger.info("Heal phase complete", extra={**s, "phase": "heal"})
        return s
