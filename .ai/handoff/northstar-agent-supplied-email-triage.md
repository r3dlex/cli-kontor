# Northstar A→B Handoff: agent-supplied-email-triage

- Intake: `.ai/work-intake/agent-supplied-email-triage.md`
- Spec: `docs/specifications/ACTIVE/agent-supplied-email-triage.md`
- Sliced goal: one forward-port slice preserving explicit, preview-first
  agent triage and Pipeline-owned canonical classification.
- Manifest record: `optional_branches[id=northstar-handoff-agent-supplied-email-triage]`
  in `.ai/workflows/repo-workflow.json`.
- Traceability: `intake:kontor-cli:agent-supplied-email-triage` →
  `spec:kontor-cli:agent-supplied-email-triage` →
  `plan:kontor-cli:northstar-agent-supplied-email-triage` →
  `handoff:kontor-cli:northstar-agent-supplied-email-triage`.

Autobahn consumes this handoff to ship the single validated slice without
combining triage with mailbox processing.
