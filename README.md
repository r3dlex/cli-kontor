# kontor-cli

Autonomous email management CLI for a work mailbox using **himalaya** + **DavMail** (EWS bridge) + **LLM classifier**.

## Prerequisites

- [himalaya](https://github.com/tobiassjosten/himalaya) — `brew install himalaya`
- [DavMail](http://davmail.sourceforge.net/) — EWS-to-IMAP bridge running locally:
  - IMAP: `localhost:1110`
  - SMTP: `localhost:1025`
  - HTTP proxy: `localhost:3128`
- Python 3.12+ and [UV](https://github.com/astral-sh/uv)

## Setup

```bash
git clone git@github.com:r3dlex/kontor-cli.git
cd kontor-cli
cp config.example.yaml config.yaml
# Edit config.yaml with your email, DavMail settings, and LLM API key
uv sync
```

## Usage

```bash
uv run kontor-cli check-config               # Validate config + prerequisites
uv run kontor-cli classify --email-id <id>    # Print target folder for an email
uv run kontor-cli process --phase rebuild    # Process all historical emails
uv run kontor-cli process --phase realtime   # Process inbox only
uv run kontor-cli process --phase heal      # Fix invariant violations
uv run kontor-cli dry-run --phase rebuild    # Preview without changes
uv run kontor-cli process --phase heal --rules-freeze  # Snapshot rules before heal
```

## Folder Taxonomy

```
INBOX
 ├─ 0_Action           ← Requires your action
 ├─ 1_Management/MGT_<Topic>
 ├─ 2_Projects/PRJ_<Domain>_<Initiative>_<Scope>
 ├─ 3_External/EXT_<Company>_<Topic>
 ├─ 4_Info            ← Newsletters, announcements
 ├─ 9_System          ← CI/CD, security alerts
 └─ Archive/          ← Emails >6 months old (mirrors structure)
```

## Rules Engine

Three formats, evaluated in priority order:

1. **YAML DSL** — `rules/rules.d/*.yaml`:
   ```yaml
   - from: "@vendor\\.com"
     subject: "invoice"
     folder: "1_Management/MGT_Finance"
   ```
2. **Python module** — `rules/rules.py`:
   ```python
   def classify(email):
       if "budget" in email.subject.lower():
           return "1_Management/MGT_Finance"
   ```
3. **Natural-language rules** — `rules/*.rules.txt`

## Development

```bash
uv sync
uv run pytest tests/unit/     # Run unit tests
uv run kontor-cli --help      # CLI reference
```
