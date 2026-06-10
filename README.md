# anvil

Secure MCP platform for coding agents, developer workflows, and multi-context integrations.

`anvil` centralizes safe access to developer systems such as Sentry, GitLab, and GitHub while keeping authentication and secrets outside repositories, prompts, logs, and MCP client configuration.

## Goals

- Provide secure Sentry access for coding agents.
- Provide safe GitLab automation for merge requests and pipelines.
- Provide read-only GitHub primitives for pull requests, diffs, refs, and Actions logs.
- Support multiple organizations, environments, and upstream hosts.
- Avoid hardcoded tokens in prompts, configs, logs, tests, or repositories.
- Keep MCP transport wiring separate from business logic.

## Architecture

```text
AI Agent
↓
MCP Client (Codex / OpenCode / Claude)
↓
anvil
↓
contexts.yaml + local secret store
↓
Sentry / GitLab / GitHub APIs
```

## Features

Current tools:

- `resolve_sentry_context` — read-only, no upstream call.
- `get_sentry_issue` — read-only, fetches issue + latest event.
- `list_sentry_issues` — read-only, lists compact Sentry issue summaries.
- `assign_sentry_issue` — destructive, assigns a Sentry issue after confirmation.
- `resolve_sentry_issue` — destructive, resolves a Sentry issue after confirmation.
- `link_sentry_issue_to_mr` — destructive, comments on a Sentry issue with a GitLab MR link.
- `get_sentry_release` — read-only, fetches compact Sentry release metadata.
- `open_fix_mr_from_sentry` — destructive, prepares a Sentry fix workflow and can create a remote branch.
- `get_gitlab_pipeline_status` — read-only, fetches pipeline status + failed jobs.
- `get_gitlab_job_log` — read-only, fetches a truncated GitLab CI job log tail.
- `diagnose_gitlab_pipeline_failure` — read-only, aggregates failed jobs and log tails.
- `retry_gitlab_failed_jobs` — destructive, retries only failed CI jobs after confirmation.
- `cancel_gitlab_pipeline` — destructive, cancels a pipeline after confirmation.
- `list_gitlab_merge_requests` — read-only, lists compact MR summaries.
- `compare_gitlab_refs` — read-only, compares refs and returns commit/diff counts.
- `get_gitlab_mr_diff` — read-only, returns MR metadata + bounded per-file diffs.
- `resolve_github_context` — read-only, no upstream call.
- `list_github_pull_requests` — read-only, lists compact GitHub PR summaries.
- `get_github_pull_request_diff` — read-only, returns PR metadata + bounded per-file patches.
- `compare_github_refs` — read-only, compares refs and returns compact commit/file counts.
- `get_github_workflow_run_status` — read-only, returns workflow run metadata + jobs.
- `get_github_actions_job_log` — read-only, fetches a truncated GitHub Actions job log tail.
- `create_github_pull_request` — destructive, opens a GitHub PR after confirmation (dry-run otherwise).
- `post_gitlab_mr_comment` — destructive, posts MR note/discussion after confirmation.
- `post_gitlab_mr_line_comment` — destructive, posts an inline diff comment after confirmation.
- `approve_gitlab_merge_request` — destructive, approves an MR after confirmation.
- `set_gitlab_mr_ready` — destructive, marks a draft MR as ready after confirmation.
- `trigger_gitlab_pipeline` — destructive, creates a new pipeline after confirmation.
- `create_gitlab_merge_request` — destructive, requires `confirm=True` (dry-run otherwise).
- `doctor_report` — read-only diagnostic of config, secrets, and upstream connectivity.

Current resources:

- `contexts://list` — read-only discovery of configured contexts and public upstream base URLs. Secret identifiers and token values are omitted.

Current Claude Code skills:

- `fix-sentry-issue`
- `review-sentry-issue`
- `debug-pipeline`
- `review-merge-request`
- `investigate-production-error`
- `prepare-release-summary`
- `create-hotfix-plan`

Current MCP prompts:

- The same workflow names above are exposed as transitional MCP prompts for clients that support MCP prompts but do not support Claude Code skills. They are generated from the same `skills/*/SKILL.md` files to avoid drift.

Each tool advertises MCP annotations (`title`, `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) so hosts can render a confirmation UI and decide when to prompt. List tools accept a `limit` (default 25, max 100) and report `total`/`returned`/`truncated`/`warnings` so agents never silently miss results.

### Tool surface and scaling

anvil currently exposes ~30 tools — at the top of the "one tool per action" range. The MCP tool list lands in the model's context window on every turn, so the surface is bounded deliberately. **Decision:** the next upstream service (or a meaningful batch of new actions) should switch from one-tool-per-action to a `search_actions` + `execute_action` pattern (optionally promoting the 3–5 most-used tools to dedicated entries) rather than adding more flat tools. Reference: the `build-mcp-server` skill (`mcp-server-dev` plugin), `references/tool-design.md`.

## Project Structure

```text
anvil/
├── pyproject.toml
├── README.md
├── contexts.yaml.example
├── .claude-plugin/
│   └── plugin.json     # Claude Code plugin metadata
├── skills/             # Claude Code workflow skills
├── src/anvil/
│   ├── cli.py          # CLI entrypoint (serve | doctor)
│   ├── server.py       # FastMCP wiring only
│   ├── config.py       # Loads contexts.yaml
│   ├── contexts.py     # Pydantic models + host-to-context resolution
│   ├── exceptions.py   # Typed error hierarchy
│   ├── http.py         # Shared async httpx + retries
│   ├── keychain.py     # Secret resolution (env -> Keychain -> secret-tool -> pass)
│   ├── logging.py      # structlog JSON to stderr with redaction
│   ├── doctor.py       # Config/secret/upstream diagnostic
│   ├── sentry/         # Sentry client + tools + I/O models
│   ├── gitlab/         # GitLab client + tools + I/O models
│   └── github/         # GitHub client + read-only MCP tools + I/O models
└── tests/
```

`server.py` should remain the MCP entrypoint only. Business logic lives in domain modules for configuration, context resolution, secret access, upstream API calls, workflows, and MCP tool functions.

## Installation

```bash
git clone <repo-url> anvil
cd anvil
uv sync
uv sync --extra dev
```

## Configuration

Global configuration is stored outside the repository:

```text
~/.config/anvil/contexts.yaml
```

A ready-to-edit template is committed at [`contexts.yaml.example`](contexts.yaml.example):

```bash
mkdir -p ~/.config/anvil
cp contexts.yaml.example ~/.config/anvil/contexts.yaml
```

Example:

```yaml
contexts:
  example:
    sentry:
      base_url: "https://sentry.example.com"
      token_keychain: "anvil/sentry/example"
    gitlab:
      base_url: "https://gitlab.example.com"
      token_keychain: "anvil/gitlab/example"
    github:
      base_url: "https://api.github.com"
      token_keychain: "anvil/github/example"
```

All services are optional per context, but each context must configure at least one of `sentry`, `gitlab`, or `github`. An empty context fails configuration validation with a clear `no services configured` error.

For GitHub Enterprise, set `github.base_url` to the API root, for example `https://github.example.com/api/v3`.

## Secrets

Secrets are stored in the local platform secret store and retrieved dynamically at runtime.

Example on macOS:

```bash
security add-generic-password \
  -a "$USER" \
  -s "anvil/sentry/example" \
  -w
```

For development or CI, export an environment variable derived from the service name by uppercasing it and replacing slashes, dashes, and dots with underscores:

```bash
export ANVIL_SENTRY_EXAMPLE=...
```

Tokens are never stored in repository files, prompts, logs, shell history, or MCP configuration.

## Running

```bash
uv run anvil           # equivalent to: uv run anvil serve
uv run anvil doctor    # validate config, secrets, upstream connectivity
```

`doctor` exits non-zero if any check fails.

## Observability

Structured JSON logs are emitted to stderr because stdout is reserved for the MCP stdio transport. Set the level via `ANVIL_LOG_LEVEL` (default `INFO`).

Common secret-shaped fields (`Authorization`, `PRIVATE-TOKEN`, `token`, `secret`, `password`, `api_key`, `x-api-key`) are automatically redacted.

## Development

```bash
make install
make check
make doctor
make format
```

Equivalent commands:

```bash
uv sync --extra dev
uv run ruff check src tests
uv run mypy
uv run pytest
```

## Troubleshooting

Start with:

```bash
uv run anvil doctor
```

Common failures:

| Symptom | Likely cause | Fix |
|---|---|---|
| `config_loaded: fail` with `Config not found` | `~/.config/anvil/contexts.yaml` is missing | Copy `contexts.yaml.example` to `~/.config/anvil/contexts.yaml` |
| `config_loaded: fail` with `Invalid YAML` | Indentation or a stray tab in the YAML | Re-check the file in your editor |
| `secret:anvil/sentry/example` fails | The secret is not in the local secret store or env | Add it to your secret store or export `ANVIL_SENTRY_EXAMPLE` |
| An upstream returns 401 | Token is invalid, expired, or has insufficient scope | Regenerate the token with the minimum required scope |
| `Context not found for host: ...` | The URL host does not match any configured context | Add the host to `contexts.yaml` or pass a URL on a configured host |
| Tool says `dry-run` and nothing happened | The tool is destructive and `confirm=True` was not passed | Re-invoke after reviewing the preview |

## MCP Client Configuration

Claude Code:

```bash
claude mcp add anvil -- uv run --directory /absolute/path/to/anvil anvil
```

Codex CLI:

```toml
[mcp_servers.anvil]
command = "uv"
args = [
  "run",
  "--directory",
  "/absolute/path/to/anvil",
  "anvil",
]
```

OpenCode:

```json
{
  "mcp": {
    "anvil": {
      "type": "local",
      "command": [
        "uv",
        "run",
        "--directory",
        "/absolute/path/to/anvil",
        "anvil"
      ]
    }
  }
}
```

Use an absolute checkout path in MCP client configuration, then restart the client.

## Claude Code Plugin

This repository also ships Claude Code skills for workflow guidance. The MCP server remains the source of API primitives; skills describe how an agent should combine those tools.

For local development, load the plugin from the checkout:

```bash
claude --plugin-dir /absolute/path/to/anvil
```

Installed plugin skills are namespaced by the plugin name, for example `/anvil:fix-sentry-issue`.

## Development Philosophy

The MCP should remain stateless, avoid storing secrets, support multiple contexts, keep authentication centralized, and expose clean tools/resources for coding agents. Workflow guidance belongs in skills. MCP prompts are transitional aliases backed by the same skill markdown.

## License

Internal tooling.
