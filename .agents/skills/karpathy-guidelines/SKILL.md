---
name: karpathy-guidelines
description: Baseline software-engineering guidelines for agents working in this repository — think before coding, simplicity first, surgical changes, goal-driven execution. Load as the operating contract for any non-trivial change.
---

# Karpathy Software Engineering Guidelines

All agents operating in this repository load this file as a baseline.

## Four Rules

1. **Think Before Coding** — Understand the problem, its bounds, and its edge cases before writing code.
2. **Simplicity First** — The simplest correct solution is better than a complex one. Avoid premature abstraction.
3. **Surgical Changes** — Change only what is necessary. Prefer targeted edits over broad rewrites.
4. **Goal-Driven Execution** — Every change serves a clear deliverable. Verify before claiming completion.

## Violation Examples

### Think Before Coding
**Violation:** Implementing email threading without clarifying whether "thread" means conversation threading or chronological grouping.  
**Correction:** Ask or specify the threading model first.

### Simplicity First
**Violation:** Building a plugin architecture for 2 hardcoded behaviors.  
**Correction:** Use if/elif until a third behavior appears.

### Surgical Changes
**Violation:** Rewriting `pipeline.py` when the bug is in one function.  
**Correction:** Isolate the function, fix it, leave the rest.

### Goal-Driven
**Violation:** Adding feature flags and logging to every module when the AC only requires a single CLI command.  
**Correction:** Implement only what the AC specifies; add instrumentation only when it aids verification.
