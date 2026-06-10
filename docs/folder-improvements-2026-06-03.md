# Folder Structure Improvements — Observed 2026-06-03 Inbox Drain

Source data: 33 emails in `andre.burgstahler@rib-software.com` INBOX before drain.
Drain plan: `/tmp/drain_plan.txt` (G002 evidence).

## Gaps Identified

### Gap 1 — Calendar-response pattern missing (1:1 false-positive risk)

Observed: 9 of 33 emails (27 %) are calendar responses
(`Accepted:` / `Declined:` / `Tentative:` / `New Time Proposed:` / `Angenommen:` /
`Abgelehnt:` / `Re: Sync` / `Follow-up`).
Currently they only match via the 1:1 subject regex in
`rules.d/00-global.yaml` (priority 89), which is order-dependent and will
misclassify a `Re: Sync` on a project topic as 1_Management/1on1.

**Proposed fix** — add a high-priority explicit calendar-response rule that
fires before generic 1:1 matching:

```yaml
# rules.d/00-global.yaml — insert at priority 95 (before 1:1 match)
- pattern: "^(Accepted|Declined|Tentative|New Time Proposed|Cancelled):"
  folder: "1_Management/1on1"
  priority: 95

- pattern: "^(Angenommen|Abgelehnt|Zugesagt|Unsicher):"
  folder: "1_Management/1on1"
  priority: 95
```

TDD: extend `tests/unit/rules_engine_test.py::TestYamlDsl` with two cases that
assert these patterns route to `1_Management/1on1` regardless of project
keywords in the subject.

### Gap 2 — External-domain 1:1 host mapping missing

Observed: Georg Heißenberger sends calendar responses from both
`g.heissenberger@saa.at` (his SAA alias) and
`georg.heissenberger@rib-software.com` (RIB alias). Currently
`g.heissenberger@saa.at` falls through to `4_Info` (no rule) because the
`@rib-software.com` subject-keyword match fails for the external domain.

**Proposed fix** — add `saa.at` (or a generic `.*@saa.at` rule) to
`rules.d/03-key-senders.yaml` so SAA-origin 1:1 traffic also lands in
`1_Management/1on1`:

```yaml
# rules.d/03-key-senders.yaml — add at priority 75
- from: ".*@saa\\.at"
  subject: ".*1:1.*|one on one|Accepted:|Declined:|Tentative:.*"
  folder: "1_Management/1on1"
  priority: 75
```

### Gap 3 — `2_Projects/AI` vs `2_Projects/RIB-4.0/AI` mismatch

Observed: One email
(`Re: Augment code and github copilot account for new team member`)
was routed to `2_Projects/AI` by the Python rules (`rules.py` line
`if "ai" in subject`). The actual existing folder structure has only
`2_Projects/AI` (not `2_Projects/RIB-4.0/AI`), and the folder description
in `5b64e95` says "Create 2_Projects/India, expand AI rules, add folder
descriptions" — so `2_Projects/AI` is the canonical target.

**Status:** The Python `rules.py` still references `2_Projects/RIB-4.0/AI`
(line 73) which is a stale comment-only mismatch. The Python subject-keyword
chain is the only thing that actually fires for that subject line; YAML
priority 75-89 rules do not match AI subjects. Either:
- (a) move all AI/incubator traffic to `2_Projects/AI` (current de-facto state), or
- (b) re-create `2_Projects/RIB-4.0/AI` if hierarchical scoping is desired.

Recommendation: **adopt (a)** — fix `rules.py` to return `2_Projects/AI` and
remove the `2_Projects/RIB-4.0/AI` reference.

### Gap 4 — `2_Projects/Sales` vs `2_Projects/Sales_BoQ_Estimate_Procurement` ambiguity

Both folders exist. The most recent commit `de7229c` renamed
`Sales` → `Sales_BoQ_Estimate_Procurement`. The catch-all
`99-catchall.yaml` still routes unknown internal to `2_Projects/Internal`,
which is fine, but the rules in `01-internal-topics.yaml` priority 90 use
the new name. No change needed; just verify YAML rule priority 90 still fires
before catch-all 10.

## Non-Improvements (Verified Working)

- 4_Info routing for Teams digests, Mentimeter, Miro notifications, weekly digest
  all worked correctly.
- 2_Projects/Security routed the Rhomberg ISO incident correctly.
- 2_Projects/Willemen caught both `TR: Collaborative Team Coaching` and
  `Urgent - RIB AI SDLC - Fast Runners - Workshop 2 - Copenhagen` from
  Julien Seroi via the key-sender rule.
- 2_Projects/India routed Arthur's "Change of Reporting Line | India" via
  the priority 89 India rule.

## Test Coverage Additions (TDD before edits)

Before applying any of the above, add the following to
`tests/unit/rules_engine_test.py`:

```python
def test_calendar_response_routes_to_1on1(tmp_path: Path) -> None:
    rules = [
        {"pattern": "^(Accepted|Declined|Tentative|New Time Proposed):",
         "folder": "1_Management/1on1", "priority": 95},
        {"from": ".*rib-software\\.com", "subject": ".*1:1.*",
         "folder": "1_Management/1on1", "priority": 89},
    ]
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(yaml.safe_dump(rules))
    loaded = yaml_dsl.load_rules_from_dir(tmp_path)
    assert yaml_dsl.evaluate_yaml_rules(
        loaded, "anyone@anywhere.com",
        "Accepted: 1:1 Andre X"
    ) == "1_Management/1on1"

def test_external_saa_at_1on1(tmp_path: Path) -> None:
    rules = [
        {"from": ".*@saa\\.at",
         "subject": ".*Accepted:.*|.*Declined:.*",
         "folder": "1_Management/1on1", "priority": 75},
    ]
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(yaml.safe_dump(rules))
    loaded = yaml_dsl.load_rules_from_dir(tmp_path)
    assert yaml_dsl.evaluate_yaml_rules(
        loaded, "g.heissenberger@saa.at",
        "Accepted: One on One: Georg Heißenberger"
    ) == "1_Management/1on1"
```

Then apply the YAML changes, run `uv run pytest tests/unit/ -q`, and
re-run the drain.
