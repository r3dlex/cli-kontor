# `.omc/wiki/` — subrepo-scoped OMC wiki

Persistent markdown knowledge base pages that compound across OMC
sessions working in the kontor-cli subrepo. This is the
subrepo-scoped sibling of the OMC wiki that lives at
`r3dlex/rib-workspace/.omc/wiki/`.

## What goes here

- **Architecture notes** — diagrams (mermaid), module boundaries,
  key invariants
- **Decisions** — ADRs scoped to kontor-cli (cross-cutting ADRs go
  in the workspace wiki)
- **Patterns** — conventions specific to this subrepo (e.g.,
  pipeline phase ordering, folder taxonomy rules)
- **Debugging** — known failure modes and how to triage them
- **Reference** — quick links to external systems (DavMail,
  Exchange, the LLM provider)
- **Conventions** — style and naming rules unique to this subrepo

## What does NOT belong here

- Session-scoped working memory (`.omc/state/`, `.omx/notepad.md`)
- Cross-workspace knowledge — go up to the workspace wiki
- Generated artifacts (logs, reports) — those go in `.omx/`
