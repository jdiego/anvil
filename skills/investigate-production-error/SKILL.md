---
name: investigate-production-error
description: Investigate a production Sentry issue at incident scope using Anvil MCP tools.
---

# Investigate Production Error

Investigate a production error at incident scope.

Use the Sentry issue URL provided by the user or by the invocation parameters.

## Workflow

1. Call `get_sentry_issue` with the Sentry issue URL to fetch the issue and latest event.
2. Assess impact: level, status, first seen, last seen, times seen, affected users.
3. Identify the release and environment from the issue metadata.
4. Call `get_sentry_release` for the affected release to check deploy timing and commits.
5. Call `list_sentry_issues` filtered to the same project to find related concurrent errors.
6. If a GitLab pipeline is associated with the release, call `get_gitlab_pipeline_status` to check whether the deploy pipeline completed cleanly.
7. Summarize the blast radius: which users, environments, and services are affected.
8. Propose immediate triage actions such as rollback, hotfix, silence, or monitor before a full code fix.

## Constraints

- Do not resolve or assign the issue without explicit user confirmation.
- Do not paste raw event payloads; summarize the relevant fields only.
- If the Sentry host does not match a configured context, ask the user before proceeding.

## Expected Answer

- Incident summary: what broke, when, and how widely.
- Root cause hypothesis with supporting evidence.
- Immediate mitigation options with trade-offs.
- Next step: hotfix, rollback, or monitor.
