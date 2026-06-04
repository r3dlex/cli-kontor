"""LLM-based email classifier for kontor-cli."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from kontor_cli.config import Config
    from kontor_cli.himalaya import Email


logger = logging.getLogger("kontor_cli.classifier")


@dataclass
class ClassificationResult:
    """Result from LLM classification."""

    folder: str
    confidence: float
    action: str  # "adjust" | "create" | "none"


FOLDER_TAXONOMY = """
## Email Folder Taxonomy

Emails MUST be placed in exactly one of these folders:

- **0_Action** — Requires immediate action from you. Not a storage folder.
- **1_Management/MGT_<Topic>** — Management topics: reporting, HR, legal, compliance, meetings, 1:1s.
- **2_Projects/PRJ_<Domain>_<Initiative>_<Scope>** — Project work: specs, status updates, reviews, kickoffs.
- **3_External/EXT_<Company>_<Topic>** — External parties: vendors, partners, clients.
- **4_Info** — Informational only. Newsletters, announcements, system notifications.
- **9_System** — System emails: password resets, security alerts, CI/CD pipelines, infra.
- **Archive/<same path>** — Emails older than 6 months, or already-processed emails from any folder.

Folder naming rules:
- Sub-folders use "/" (e.g., "2_Projects/PRJ_Finance_ERP_Global")
- Archive mirrors the exact structure (e.g., "Archive/2_Projects/PRJ_Finance_ERP_Global")
- Never create folders outside this taxonomy.
"""


SYSTEM_PROMPT = """You are an email classifier for kontor-cli. Your job is to classify emails into the correct folder based on the folder taxonomy.

For each email, you MUST respond with ONLY valid JSON:
{
  "folder": "<folder_name>",
  "confidence": <0.0 to 1.0>,
  "action": "adjust" | "create" | "none",
  "reasoning": "<brief explanation>"
}

- folder: Must match the taxonomy exactly. Default to "4_Info" if uncertain.
- confidence: 1.0 = certain, 0.5 = uncertain. Below 0.7 should default to "4_Info".
- action: "adjust" = modify an existing rule, "create" = write a new rule, "none" = one-off decision.
- reasoning: One sentence explaining why this folder was chosen.
"""


def build_prompt(
    email: Email, taxonomy: str, rules_context: str, yaml_rules: str = ""
) -> str:
    """Build the classification prompt for the LLM."""
    return f"""{SYSTEM_PROMPT}

{taxonomy}

## Current Rules (YAML DSL)
{yaml_rules if yaml_rules else "(No YAML DSL rules defined yet.)"}

## Natural-Language Rules
{rules_context}

## Email to Classify
- **From:** {email.from_addr}
- **Subject:** {email.subject}
- **Date:** {email.date.isoformat()}
"""


class ClassifierError(Exception):
    """Raised when classification fails."""


def _derive_max_output_tokens(model: str) -> int:
    """Return a safe max_output_tokens for the given model."""
    model_lower = model.lower()
    if "gpt" in model_lower and any(
        m in model_lower for m in ("4o", "4-turbo", "4.5", "4-32k", "gpt-5")
    ):
        # GPT-4/4o models support up to 16K output
        return 4096
    if "gpt" in model_lower:
        # GPT-3.5 / older GPT-4 — 4K output is plenty for a short JSON reply
        return 1024
    if "minimax" in model_lower or "abab" in model_lower:
        # MiniMax: conservative 1K output; the response is a few fields of JSON
        return 1024
    if "claude" in model_lower:
        # Claude: 8K output should cover any reply
        return 8192
    # Default: 1K — safe for short JSON responses
    return 1024


def _truncate_prompt(prompt: str, model: str, overhead_chars: int = 500) -> str:
    """Truncate prompt to fit within the model's context headroom.

    Uses a conservative heuristic based on the model's known context size.
    For unknown models, returns the prompt unchanged (fail-open).
    """
    model_lower = model.lower()
    # Target prompt length = 75% of max context, minus overhead.
    if "minimax" in model_lower or "abab" in model_lower:
        # MiniMax: 200K token context, use 150K chars as the target
        target_chars = int(200_000 * 0.75) - overhead_chars
    elif "gpt-5" in model_lower:
        # GPT-5: assume 200K context
        target_chars = int(200_000 * 0.75) - overhead_chars
    elif "gpt-4o" in model_lower or "gpt-4-turbo" in model_lower:
        # 128K context models
        target_chars = int(128_000 * 0.75) - overhead_chars
    elif "gpt-4" in model_lower or "gpt-4-32k" in model_lower:
        # 32K context
        target_chars = int(32_000 * 0.75) - overhead_chars
    elif "claude" in model_lower:
        # Claude 3: 200K context
        target_chars = int(200_000 * 0.75) - overhead_chars
    else:
        # Unknown model: fail open and return unchanged
        return prompt

    if len(prompt) <= target_chars:
        return prompt

    # Truncate from the bottom — keep the email section visible
    # by dropping from the middle of the NL/rules context.
    return prompt[:target_chars] + "\n\n[... prompt truncated ...]"


class Classifier:
    """OpenAI-compatible LLM classifier."""

    def __init__(self, config: Config) -> None:
        self.base_url = config.llm_base_url
        self.api_key = config.llm_api_key
        self.model = config.llm_model
        self.temperature = config.llm_temperature
        self.timeout = config.llm_timeout
        self.confidence_threshold = config.pipeline_confidence_threshold

    def classify(
        self,
        email: Email,
        rules_context: str = "",
        yaml_rules: str = "",
    ) -> ClassificationResult | None:
        """Classify a single email using the LLM. Returns None on failure."""
        prompt = build_prompt(email, FOLDER_TAXONOMY, rules_context, yaml_rules)

        # Derive a safe max_output_tokens for the model.
        max_output_tokens = _derive_max_output_tokens(self.model)
        # Truncate the prompt to leave headroom for system + output.
        # Using a conservative 75% of the model's max context for the prompt.
        # This is a best-effort guard; a proper fix would count actual tokens,
        # but that would add a dependency (tiktoken). The heuristic works for
        # MiniMax (200K) and most OpenAI-compatible models.
        prompt = _truncate_prompt(prompt, model=self.model, overhead_chars=500)

        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": max_output_tokens,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                f"LLM API returned {exc.response.status_code}: {exc.response.text[:200]}"
            )
            return None
        except httpx.RequestError as exc:
            logger.error(f"LLM API request failed: {exc}")
            return None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            # Strip markdown code fences if present
            if content.strip().startswith("```"):
                content = content.strip()[content.strip().find("\n") + 1 :]
                if content.endswith("```"):
                    content = content[:-3].strip()
            result: dict[str, Any] = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            snippet = content[:200] if "content" in locals() else "<unparsed>"
            logger.error(f"Failed to parse LLM response: {exc!r} — content: {snippet}")
            return None

        folder = result.get("folder", "4_Info")
        confidence = float(result.get("confidence", 0.0))
        action = result.get("action", "none")

        # Low confidence → default to 4_Info
        if confidence < self.confidence_threshold:
            logger.warning(
                f"Low confidence ({confidence:.2f}), defaulting to 4_Info",
                extra={"email_id": email.id, "llm_folder": folder},
            )
            folder = "4_Info"

        logger.info(
            "LLM classified email",
            extra={
                "email_id": email.id,
                "folder": folder,
                "confidence": confidence,
                "llm_action": action,
            },
        )
        return ClassificationResult(folder=folder, confidence=confidence, action=action)
