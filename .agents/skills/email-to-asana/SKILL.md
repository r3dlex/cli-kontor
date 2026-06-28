---
name: email-to-asana
description: Filter important RIB emails and create Asana action items classified into the 4 Stanier management-action categories (Information Gathering, Nudging, Being the Example, Taking Decision).
---

# Email-to-Asana Triage Skill

## Purpose

**email-to-asana** automatically triages incoming emails into one of four management-action categories, creates idempotent Asana tasks, and extracts target dates from email context. The triage engine combines deterministic importance scoring (sender tiers + customer status + content signals) with a single LLM call to categorize each email and identify deadlines.

The skill:
1. Scores each email's importance via sender membership, customer domain checks, and escalation-signal keywords
2. Fetches email bodies for qualifying messages (recall-biased: always fetch for listed senders or customers, over-fetch the rest)
3. Passes qualifying emails to an LLM for category classification + deadline extraction
4. Creates one Asana task per email (idempotent, dedup-scoped to the target project)
5. Reports preview decisions (dry-run) or committed task creation (with full error handling)

All per-email errors (LLM timeouts, Asana API failures, date parsing) are caught and logged; they do not propagate and do not prevent processing of subsequent emails.

## The 4 Categories & Their Asana Projects

| Category | Project Key | Definition (Stanier) |
|----------|-------------|----------------------|
| **Information Gathering** | `information_gathering` | Observe & collect a signal. No direction change yet; the data informs future action. |
| **Nudging** | `nudging` | Subtly steer someone toward a better outcome while preserving their autonomy. |
| **Being the Example** | `being_the_example` | Model a habit, standard, or boundary visibly so others learn by observing. |
| **Taking Decision** | `taking_decision` | A decision is required of the reader; deadlock or clarity gap blocks progress. |

## Category Templates

Each category has a **standard text template** (task description structure) and a **Done-when definition** (acceptance criteria). These are verbatim as stored in the triage engine:

### Information Gathering

**Standard text:**
```
Observe & collect: {what data/signal}. Source: {email link}. 
Watching for: {pattern}. No direction change yet.
```

**Done when:**
```
Data reviewed and a note recorded — either 'warrants action → 
follow-up spawned' or 'no action needed' — then closed.
```

### Nudging

**Standard text:**
```
Nudge {who} toward {better outcome} via {subtle mechanism — link / 
open question / framing}. Preserve their autonomy.
```

**Done when:**
```
Nudge delivered (message/question/resource sent) and you noted 
whether it landed.
```

### Being the Example

**Standard text:**
```
Model {habit / standard / boundary} in {context}. Demonstrate, 
don't instruct.
```

**Done when:**
```
A visible artifact exists (doc written, PR comment left, boundary 
set) that others can see.
```

### Taking Decision

**Standard text:**
```
Decide: {question}. Options: {A / B}. Constraint/deadline: {date}. 
Communicate to: {stakeholders}.
```

**Done when:**
```
Decision made, communicated to stakeholders, recorded; deadlock resolved.
```

## Importance & Eligibility Rubric

### Sender Tiers

The triage engine evaluates sender membership against three configured tiers, each with a weight:

- **extremely_important** (weight 1.0) — C-suite, founders, or equivalent decision-making authority
- **very_important** (weight 0.8) — Directors, heads of major functions, or strategic partners; triggers a soft bias toward `taking_decision`
- **also_important** (weight 0.5) — Team leads, senior individual contributors, or important collaborators

Tier members are matched by case-insensitive substring (name or email address).

### Boosts

- **Customer boost:** Any sender from an external domain (not `internal_domain`) is treated as a customer and always qualifies
- **Escalation boost:** Content containing 2+ signal keywords (urgency, decision, approval, blocker, deadline, etc.) elevates the email for review

### Eligibility Gate

An email qualifies for triage when **any** of the following are true:

1. Sender is in extremely/very tier **AND** content has actionable signal (score > 0)
2. Sender is in also tier **AND** content is strong (score >= content_high_threshold, default 0.6)
3. Sender is a customer (external domain)
4. Content has high-signal escalation keywords (score >= content_high_threshold)

### Body Fetch (Recall-Biased)

- **Always fetch** for: listed senders (any tier), customers
- **Over-fetch** the rest: broad subject pre-scan for signal keywords; declined fetches are logged at DEBUG level

### Decisive-Sender Bias

Senders in the `very_important` tier receive a soft bias (instruction to the LLM, not a hard rule) toward the `taking_decision` category when the email genuinely contains a decision point.

## Configuration

Triage is configured in `config.yaml` under two sections:

### `asana:` section (required when triage is enabled)

```yaml
asana:
  pat: "REPLACE_WITH_ASANA_PAT"                    # Personal Access Token
  workspace_gid: "REPLACE_WITH_WORKSPACE_GID"      # Workspace GUID
  project_gids:
    information_gathering: "REPLACE_WITH_PROJECT_GID"
    nudging: "REPLACE_WITH_PROJECT_GID"
    being_the_example: "REPLACE_WITH_PROJECT_GID"
    taking_decision: "REPLACE_WITH_PROJECT_GID"
```

**Notes:**
- The PAT is never committed; it lives in the gitignored `config.yaml`
- All four projects must already exist in Asana (validate-only; never auto-created)
- One task is created in exactly one project (the LLM-selected category)

### `triage:` section (optional, disabled by default)

```yaml
triage:
  enabled: false                                    # Enable/disable triage
  scan_rebuild: false                               # Opt-in rebuild-phase triage
  internal_domain: "rib-software.com"               # Internal domain (for customer check)
  content_high_threshold: 0.6                       # Escalation signal threshold (0..1)
  sender_tiers:
    extremely_important:
      - "Rolf Helmes"
      - "René Wolf"
      # ... more names or addresses ...
    very_important:
      - "Arthur Berganski"
      - "Sanket Khandare"
      # ... more names or addresses ...
    also_important:
      - "Helen Wiersma"
      - "Jaan Tasane"
      # ... more names or addresses ...
```

**Notes:**
- `scan_rebuild`: defaults to `false`; set to `true` to enable triage during the rebuild phase (scanning archive + old inbox)
- `sender_tiers`: each tier is a list of name or email substrings (case-insensitive match)
- `content_high_threshold`: tuned empirically; 0.6 is a reasonable starting point

## Operating Procedure

### Preview Decisions (Dry-Run)

Always preview before committing:

```bash
kontor-cli triage --dry-run
```

This outputs the LLM category decisions, target dates, and task names **without writing to Asana**. No email bodies are fetched or moved. No credentials are validated beyond syntax checks.

### Commit Decisions (Live)

When you are confident in the preview output:

```bash
kontor-cli process
```

With triage enabled in the config, the `process` command will:
- Triage realtime inbox messages (INBOX-only by default)
- Create Asana tasks for qualifying emails
- Log a summary: tasks created, deduplicated, or skipped due to error

### Rebuild-Phase Triage (Optional)

To triage archive and old inbox during the rebuild phase:

1. Set `triage.scan_rebuild: true` in config.yaml
2. Run: `kontor-cli process --phase rebuild`

This is opt-in because it can be slow (full mailbox scan) and may create many tasks retroactively.

## Failure Boundary

### Fast-Fail Errors (Prevent All Triage)

These errors block the entire triage run before processing any emails:

- Asana PAT is missing or invalid
- Workspace GID is missing
- One or more project GIDs are missing or invalid
- LLM API key or base URL is missing

### Per-Email Errors (Skip & Log)

These errors are caught inside `maybe_create_task`, logged at WARNING level, and converted to `outcome="skipped_error"`. Processing continues:

- Body fetch failure (himalaya read-failure)
- LLM request timeout or HTTP error
- LLM response parsing failure (invalid JSON, missing category)
- Date parsing failure (unparseable deadline string)
- Asana API error (network, quota, 403, 5xx)

The run summary reports:
- `triage_tasks_created`: count of tasks successfully written to Asana
- `triage_skipped_dedup`: count of emails already in the target project (marker found)
- `triage_skipped_errors`: count of per-email errors (body/LLM/date/Asana failures)

### Deduplication Marker

Tasks are idempotent via a stable marker stored in task notes:

```
<!-- kontor-id:<message-id-or-uid> -->
```

The marker is scoped to the **target project only** (the category's project GID). This allows the same email to appear in multiple projects if recategorized, but prevents duplicate tasks within a single category.

- **Message-ID** is preferred (stable across moves)
- **UID fallback** if Message-ID extraction fails

### Mailbox Immutability

The triage engine **never mutates** the mailbox:
- Emails are read via `himalaya --preview` (preview mode only)
- No moves, no deletes, no flag changes
- The mailbox is read-only from triage's perspective

## LLM Categorization

The LLM receives:

- The 4 category definitions (information_gathering, nudging, being_the_example, taking_decision)
- A soft bias toward `taking_decision` if the sender is in the `very_important` tier (does not override genuine content judgment)
- The email's From, Subject, Date, and (conditionally) Body

The LLM responds with strict JSON:

```json
{
  "category": "<one of the 4 slugs>",
  "deadline": "<ISO date or relative phrase or null>",
  "rationale": "<short reason>"
}
```

- **deadline** is parsed (if present) relative to the email's date; if parsing fails, falls back to the email's date as target date
- **rationale** is included in task notes for transparency
- Any invalid category or parse failure is logged and the email is skipped

---

**Version:** 1.0  
**Last updated:** 2026-06-28
