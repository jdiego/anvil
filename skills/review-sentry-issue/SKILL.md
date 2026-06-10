---
name: review-sentry-issue
description: Triage a Sentry issue using Anvil MCP tools and propose a focused implementation plan without making changes.
---

# Review Sentry Issue

Review a Sentry issue and propose an implementation plan.

Use the Sentry issue URL provided by the user or by the invocation parameters.

## Workflow

1. Call `get_sentry_issue` with the Sentry issue URL.
2. Identify the failing exception, culprit, release/environment hints, request context, and the most relevant stack frames from the latest event.
3. Map those frames to likely files and functions in the local repository.
4. Propose the smallest fix that addresses the root cause.
5. Include tests or verification steps that would catch the regression.
6. If a merge request is needed, prepare a concise MR title, description, and test plan.

## Constraints

- Do not paste the full `latest_event` payload back to the user.
- Ignore noisy framework frames unless they affect the root cause.
- Do not create a GitLab merge request until the user explicitly confirms.
- If the Sentry URL host does not match a configured context, ask the user which environment should be configured instead of guessing.

## Expected Answer

- Summary of the failure.
- Probable root cause.
- Files/functions to inspect.
- Proposed fix.
- Verification plan.
- Optional MR draft if the user asks for one.
