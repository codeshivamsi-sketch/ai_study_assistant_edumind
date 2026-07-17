---
description: Trace the DB impact of current changes via codegraph
---
Trace the database impact of the current changes. Files to analyze:
$ARGUMENTS — if no arguments were given, use `git diff main --name-only`
(fall back to `git diff HEAD --name-only` if there is no main branch).

Invoke the db-blast skill and show its full output inline: the endpoint →
table read/write map, the migration SQL (if any migration files changed),
and the risk paragraph.
