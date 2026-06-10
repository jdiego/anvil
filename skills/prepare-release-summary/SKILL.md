---
name: prepare-release-summary
description: Prepare release notes from GitLab or GitHub refs, merged changes, and optional Sentry release metadata using Anvil MCP tools.
---

# Prepare Release Summary

Prepare a release summary between two refs.

Use the context URL, project/repository, from ref, and to ref provided by the user or by the invocation parameters.

## Workflow

1. Determine the platform from the context URL host.
2. For GitLab: call `compare_gitlab_refs` to get commit count and changed files, then call `list_gitlab_merge_requests` filtered to merged MRs targeting the release branch.
3. For GitHub: call `compare_github_refs` and `list_github_pull_requests` filtered to merged PRs.
4. If Sentry is configured in the same context, call `get_sentry_release` for the target ref to include deploy metadata and any new issues introduced in this release.
5. Classify changes: features, fixes, refactors, dependency bumps, breaking changes.
6. Flag any MR/PR that lacks a description, linked issue, or test plan.

## Expected Answer

- Release headline: version, date, change count.
- Categorized change list with MR/PR titles and authors.
- Breaking changes section, empty if none.
- Known issues or open Sentry errors introduced in this range.
- Suggested release notes draft.
