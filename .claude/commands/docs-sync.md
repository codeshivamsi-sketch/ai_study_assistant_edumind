---
description: Refresh all project docs (README, architecture map) to match the current codebase
---
Refresh project docs to match the current codebase. Focus: $ARGUMENTS — if
empty, refresh everything below; otherwise limit to the named doc(s)/area.

1. README.md — re-derive tech stack, badges, the HLD/architecture mermaid
   diagram, services, endpoint tables, and build/phase notes from the
   actual codebase. Remove stale references everywhere a removed
   technology/service/phase appears (badges, diagrams, phase notes) — not
   just the irst spot found.
2. docs/architecture.md — regenerate by invoking the /arch command's flow
   (mindmap + schema erDiagram + data access map). Do not reimplement
   /arch's generation logic here — orchestrate it; /arch remains the
   single source of truth and stays usable standalone.
3. Anything you can't verify from the code itself — prose claims, product
   descriptions, "why" statements — don't guess: list it separately as
   "needs manual review" instead of rewriting it.

Show a diff of every doc that would change, and wait for my approval
before writing any of them.
