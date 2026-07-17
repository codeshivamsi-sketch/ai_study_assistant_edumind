---
description: Full blast radius of current changes — code + DB — via codegraph
---
Compute the blast radius of the current changes. Parse $ARGUMENTS: a
`--hops N` flag anywhere in it caps the transitive trace at N hops (default
unlimited — full closure). Whatever remains after removing that flag are
files to analyze — if none remain, use `git diff main --name-only` (fall
back to `git diff HEAD --name-only` if there is no main branch).

Using codegraph:
1. Identify every changed SYMBOL (function/class) inside those files from
   the actual diff — not just the file list. A one-line change must not
   taint every symbol in the file.
2. For each changed symbol, trace dependents hop by hop: hop 1 is its
   direct callers/importers/inheritors, hop 2 is their dependents, and so
   on. Expand the frontier one hop at a time until a hop adds no new
   symbols (fixpoint — the closure is complete) or the `--hops` cap is
   reached, whichever comes first. Record the hop count for each
   dependent, and record which hop the trace actually stopped at (fixpoint
   vs capped by `--hops`).
3. If the diff touches models, schema files, or migrations, invoke the
   db-blast skill and append its output as the DB Impact section below.

Do not summarize or truncate the dependent lists. Write the full report to
docs/blast/<YYYY-MM-DD>-<HHMMSS>-blast.md — get the actual current date and
time by running `date +%Y-%m-%d-%H%M%S`, never guess it. Create docs/blast/
if it doesn't exist. Each run is a new snapshot; never overwrite previous
reports. Structure the report with these sections, in order:

- `## Code Impact` — the table: changed symbol → direct dependents →
  transitive dependents, sorted by hop count (hop count is the triage key);
  note whether the closure hit fixpoint or was capped by `--hops`, and at
  which hop; then a mermaid flowchart of the full closure, changed nodes
  marked distinctly from impacted nodes
- `## DB Impact` — the db-blast skill's output: the endpoint/table/access
  edge list, the migration SQL, and a mermaid flowchart built from the
  edge list's NEW/REMOVED/CHANGED rows only (omit UNCHANGED — keep the
  diagram focused on what this diff actually did). Style NEW edges solid
  green, REMOVED edges dashed red, CHANGED edges solid orange labeled with
  old→new access (e.g. `R → RW`); include a one-line legend under the
  diagram. If any NEW/REMOVED/CHANGED edges exist, add a note that the
  Data Access Map in docs/architecture.md is now stale and suggest
  re-running /arch. If step 3 didn't fire, this section is just "No
  DB-touching changes"
- `## Untested` — anything in the closure with no test touching it
- `## Risk` — one paragraph covering both code and DB risk (skip the DB
  half if there's no DB Impact)

After writing, show me the Code Impact table, the DB Impact section (if
present), and the Risk paragraph inline, plus the saved file path.
