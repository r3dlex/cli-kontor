/ This file defines archgate code quality rules for kontor-cli.
/ See https://github.com/r3dlex/ai-sdlc-init for schema documentation.

import { defineRules } from "ai-sdlc-rules";

export const rules = defineRules({
  backend: [
    {
      id: "no-delete-emails",
      severity: "error",
      description: "Emails must never be deleted; only moved to Archive.",
      pattern: "delete_email|DeleteEmail",
      message: "Email deletion is not permitted. Use move to Archive instead.",
    },
    {
      id: "himalaya-subprocess-check",
      severity: "error",
      description: "subprocess.run must always use check=True for himalaya commands.",
      pattern: "subprocess.run.*himalaya.*check\\s*=\\s*False",
      message: "himalaya subprocess calls must use check=True to catch failures early.",
    },
  ],
  frontend: [
    // No frontend rules — kontor-cli is a Python backend CLI with no UI.
  ],
  data: [
    // No data-domain rules — kontor-cli does not own a database.
  ],
  general: [
    {
      id: "no-silent-except",
      severity: "warn",
      description: "Bare except clauses must not pass silently.",
      pattern: "except:\\s*pass",
      message: "Use 'except SomeError:' with explicit handling, or log and re-raise.",
    },
    {
      id: "no-raw-credentials",
      severity: "error",
      description: "No hardcoded credentials or secrets in source code.",
      pattern: "(password|api_key|secret|token)\\s*=\\s*['\"][^'\"]{8,}['\"]",
      message: "Credentials must come from config.yaml or environment variables only.",
    },
  ],
  architecture: [
    {
      id: "classifier-requires-config",
      severity: "error",
      description: "Classifier must always be initialized with a validated Config object.",
      pattern: "Classifier\\(\\)",
      message: "Classifier must receive a Config instance, not be called with no arguments.",
    },
  ],
});
