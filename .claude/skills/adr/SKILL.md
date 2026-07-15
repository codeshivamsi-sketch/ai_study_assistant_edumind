---
name: adr
description: Distill the current planning/design conversation into Architecture Decision Records. Use after a planning session, or whenever a significant technical decision was just made.
---

# ADR writer

When invoked:

1. Review the conversation for significant technical decisions —
   architecture, data model, dependency, protocol, or process
   choices where alternatives were considered.
2. For EACH decision, draft one file: docs/adr/NNNN-short-title.md
   (NNNN = next number after existing ADRs), using
   docs/adr/0000-template.md. Keep each under 20 lines. Capture
   rejected alternatives and WHY — that is the whole point.
3. Never modify an existing ADR. If a decision changes, write a
   new ADR with "Supersedes: NNNN".
4. Show drafts to the user for approval before writing files.
