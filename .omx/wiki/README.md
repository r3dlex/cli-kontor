# `.omx/wiki/` — OMX execution-time wiki for kontor-cli

Execution-time knowledge base: the runbooks, observed behavior, and
operational notes that the OMX workflow accumulates while the
kontor-cli code is being deployed, monitored, and supported.

This is the OMX sibling of the OMC planning-time
[`.omc/wiki/`](../omc/wiki/README.md).

## What goes here

- **Runbooks** — how to execute the pipelines
  (`process --phase rebuild|realtime|heal`)
- **Operational notes** — observed DavMail / Exchange quirks
- **Performance baselines** — LLM latency, classifier confidence
  distributions, etc.
- **Incident postmortems** — what broke, root cause, prevention
- **Migration playbooks** — how to onboard a new mail source or
  LLM provider

## What does NOT belong here

- OMC-level knowledge (use [`.omc/wiki/`](../omc/wiki/))
- Transient logs (`.omx/logs/`)
- Live runtime state (`.omx/runtime/`, `.omx/state/`)
