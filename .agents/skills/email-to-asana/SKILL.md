---
name: email-to-asana
description: Filter important RIB emails and create Asana action items classified into the 4 Stanier management-action categories (Information Gathering, Nudging, Being the Example, Taking Decision).
---

# Email-to-Asana Triage Skill

## Purpose

**email-to-asana** triages incoming emails into one of four management-action categories, creates idempotent Asana tasks, and extracts target dates from email context. The triage engine handles the deterministic importance scoring (sender tiers + customer status + content signals); **the agent (you) reads the qualifying emails and supplies the category + deadline**. No LLM API key is configured for triage.

The skill, in agent-in-the-loop form:
1. The CLI scores each email's importance via sender membership, customer domain checks, and escalation-signal keywords
2. The CLI fetches email bodies for qualifying messages (recall-biased: always fetch for listed senders or customers, over-fetch the rest) and surfaces them as candidates
3. **The agent reads each candidate's body and classifies it** into one of the four categories (+ optional deadline)
4. The CLI creates one Asana task per agent-classified email (idempotent, dedup-scoped to the target project)
5. The CLI reports a preview decision (dry-run) or committed task creation (with full error handling)

All per-email Asana/date errors are caught and logged; they do not propagate and do not prevent processing of subsequent emails.

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

- **Customer boost:** A sender from an external (non-`internal_domain`) domain is treated as a customer — but only qualifies **with content signal** (a bare external sender no longer auto-qualifies).
- **Escalation boost:** Content with high-signal keywords (urgency, decision, approval, blocker, deadline, etc.) elevates the email for review.

### Exclusion Rule (automated / notification senders)

Automated and notification senders **never** produce a task, even with signal words. Two layers:

- **`is_automated()` heuristic** — local-part markers (`no-reply`, `noreply`, `notifications`, `mailer`, `digest`, `*report*`, `office365reports`, …) and domain markers (`*.mail.microsoft`, `engage.mail`, `updates.*`, `mailchimp`, `sendgrid`, …).
- **`triage.exclude_senders`** config list — site-specific substrings (name or address): notifications, daily digests, Google, Miro, Office365 reports, Teams, Azure, etc.

### Eligibility Gate (recall)

The deterministic gate is a **recall net** — it surfaces *candidates*, it does not decide task creation. An email is a candidate when it is **not excluded** AND **any** of:

1. Sender in extremely/very tier **AND** content has actionable signal (score > 0)
2. Sender in also tier **AND** content is strong (score >= content_high_threshold, default 0.6)
3. Sender is a customer (external domain) **AND** content has signal (score > 0)
4. Content has high-signal escalation keywords (score >= content_high_threshold)

### Owner-Input Precision Rule (the agent's decision) — IMPORTANT

Being from an important sender is **NOT** sufficient to create a task. Create a task **only if the email genuinely requires the owner's (`triage.owner_email`, e.g. andre.burgstahler@rib-software.com) personal input or action** — a decision, review, approval, or answer that *they* must give.

- ✅ Create: "@Andre, could you review and approve…", "please advise/decide", a direct question to the owner, an approval/review the owner must perform.
- ❌ Skip (no task): FYI, CC-only, status updates, someone *else's* "approved"/"thanks" reply, completed actions, newsletters — even from extremely_important senders.

The deterministic gate cannot see this; **you must**. Read the body and decide before calling `triage-create`.

### Canonical-Structure Context

Each candidate carries `canonical_folder` — the email's placement in the canonical taxonomy from the deterministic rules engine (e.g. `2_Projects/PRJ_Willemen`, `1_Management/AI`). Use it as context when judging the category (e.g. a customer-project blocker needing sign-off → `taking_decision`).

### Body Fetch (Recall-Biased)

- **Always fetch** for: listed senders (any tier).
- **Excluded senders:** body fetch is skipped (logged at DEBUG).
- **Over-fetch** the rest: customers and broad subject pre-scan for signal keywords; declined fetches logged at DEBUG.

### Decisive-Sender Bias

Candidates from senders in the `very_important` tier carry `decisive_prior=True`. A soft hint (not a hard rule): favor `taking_decision` when the email genuinely contains a decision point — but still apply the Owner-Input Precision Rule first.

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
- One task is created in exactly one project (the agent-selected category)

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

## Operating Procedure (Agent-in-the-Loop)

### Step 1 — List qualifying candidates

```bash
kontor-cli triage [--folder INBOX]
```

This runs the deterministic eligibility gate and prints each qualifying email
(id, sender, subject, reason) **followed by its fetched body**. It is
read-only: no Asana writes, no mailbox mutation.

### Step 2 — Classify each candidate (the agent's job)

For each candidate, **read the body** and decide:

- the **category** — one of the four slugs:
  `information_gathering`, `nudging`, `being_the_example`, `taking_decision`
  (use the rubric below; favor `taking_decision` when `decisive_prior` is set
  and the email genuinely contains a decision point)
- an optional **deadline** (ISO `YYYY-MM-DD`) when the email implies one;
  otherwise the email's own date is used as the due date

### Step 3 — Create the Asana task

```bash
kontor-cli triage-create \
  --email-id <id> \
  --category <slug> \
  [--deadline 2026-07-15] \
  [--folder INBOX] \
  [--no-dry-run]
```

Defaults to `--dry-run` (preview only, no Asana writes). Pass `--no-dry-run`
to perform the real, idempotent create. The command prints the resulting
outcome, task name, and due date. Repeat per candidate.

## Failure Boundary

### Fast-Fail Errors

These errors block task creation:

- Asana PAT is missing or invalid
- Workspace GID is missing
- One or more project GIDs are missing or invalid

### Per-Candidate Errors (Skip & Log)

Body-fetch failures during `triage` candidate listing are caught, logged at
WARNING level, and the email is skipped (no body to classify).

Errors during `triage-create` are caught inside `create_task_for`, logged at
WARNING level, and converted to `outcome="skipped_error"`:

- Invalid agent-supplied category (not one of the four slugs)
- Date resolution failure (no usable deadline and missing email date)
- Asana API error (network, quota, 403, 5xx), or Asana client not configured

Each `triage-create` invocation prints its outcome:
- `created`: task successfully written to Asana
- `skipped_dedup`: an email with the same marker already exists in the target project
- `skipped_error`: a per-candidate error (category/date/Asana failure)
- `preview`: dry-run, no write performed

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

## Agent Categorization

The agent reads each candidate (From, Subject, Body, reason, `decisive_prior`)
surfaced by `kontor-cli triage` and supplies, per `triage-create` call:

- **category** — exactly one of the four slugs (`information_gathering`,
  `nudging`, `being_the_example`, `taking_decision`). An invalid slug is
  rejected by the CLI (`click.Choice`).
- **deadline** (optional) — an ISO `YYYY-MM-DD` date. When omitted, the
  email's own date is used as the target due date.

When `decisive_prior` is set on a candidate, softly favor `taking_decision` if
the email genuinely contains a decision point; do not force it. The fixed
`rationale` of "agent-supplied" is recorded in the task notes for traceability.

---

**Version:** 2.0  
**Last updated:** 2026-06-28
