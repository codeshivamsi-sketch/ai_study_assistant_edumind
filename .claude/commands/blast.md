---
description: Full blast radius of current changes via codegraph
---
Compute the blast radius of the current changes. Files to analyze:
$ARGUMENTS — if no arguments were given, use `git diff main --name-only`
(fall back to `git diff HEAD --name-only` if there is no main branch).

Using codegraph:
1. Identify every changed SYMBOL (function/class) inside those files from
   the actual diff — not just the file list. A one-line change must not
   taint every symbol in the file.
2. For each changed symbol, trace ALL dependents transitively — callers,
   importers, inheritors — with NO depth limit, until the closure is
   complete. Record the hop count for each dependent.
3. Output, in this order:
   - a table: changed symbol → direct dependents → transitive dependents,
     sorted by hop count (hop count is the triage key)
   - a mermaid flowchart of the full closure, changed nodes marked
     distinctly from impacted nodes
   - a list of anything in the closure with no test touching it
   - a one-paragraph risk assessment in plain language

Do not summarize or truncate the dependent lists. Write the full report to
docs/blast/<YYYY-MM-DD>-<HHMMSS>-blast.md — get the actual current date and
time by running `date +%Y-%m-%d-%H%M%S`, never guess it. Create docs/blast/
if it doesn't exist. Each run is a new snapshot; never overwrite previous
reports. After writing, show me the table and the risk paragraph inline,
plus the saved file path.
