---
description: Fresh-instance review of the current diff (author ≠ examiner)
---
Do NOT review the diff yourself in this session — this session may have
written the code, and the author must never be the examiner.

Instead, run this in bash and relay the complete output to me:

  git diff main | claude -p "Review this diff: bugs, edge cases, violated
  invariants from CLAUDE.md and docs/adr/. Be specific: file:line for every
  finding."

(If there is no main branch, use `git diff HEAD` instead. If the diff is
empty, say so and stop.)

The whole point is that a fresh claude -p instance, with no memory of this
conversation, does the review. Present its findings verbatim, then you may
add follow-up context if I ask.
