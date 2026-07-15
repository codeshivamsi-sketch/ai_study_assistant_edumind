---
name: integration-test
description: Use whenever the user asks for tests, test coverage, or names user flows to verify. Writes integration tests for named flows.
---

# Integration test writer

When invoked:

1. Ask the user for the flows to cover if not already named
   (e.g. "signup → verify email → login returns a session").
2. Enumerate the test cases as NAMES only — happy paths, edge
   cases, error paths. Show the list; WAIT for user approval.
3. Build the environment: real dependencies via testcontainers
   (DB, queues); mock only external third parties (payments, email).
4. Write the approved tests. Rules:
   - Assert OUTCOMES (DB rows, response codes, side effects) —
     never implementation calls or internal function usage.
   - For NEW features: run the tests first and confirm they FAIL
     before implementing. A test that can't fail proves nothing.
5. Run to green. Never delete or weaken a failing test to pass —
   flag it to the user instead.
