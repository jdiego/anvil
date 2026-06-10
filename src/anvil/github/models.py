from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class GitHubRepositoryInput(BaseModel):
    context_url: HttpUrl = Field(
        description="Any URL on the target GitHub API host; used to resolve the context."
    )
    repository: str = Field(
        description="Repository name with owner, e.g. 'owner/repo'.",
        pattern=r"^[^/\s]+/[^/\s]+$",
    )


class ResolveGitHubContextInput(BaseModel):
    url: HttpUrl = Field(description="Any URL pointing at a configured GitHub API host.")


class ResolveGitHubContextOutput(BaseModel):
    context: str = Field(description="Name of the matched context.")
    github_base_url: str


class PullRequestSummary(BaseModel):
    number: int
    title: str
    state: str
    draft: bool | None = None
    user_login: str | None = None
    head_ref: str | None = None
    base_ref: str | None = None
    html_url: HttpUrl | None = None
    updated_at: str | None = None


class ListPullRequestsInput(GitHubRepositoryInput):
    state: Literal["open", "closed", "all"] = "open"
    base: str | None = Field(default=None, description="Optional base branch filter.")
    head: str | None = Field(
        default=None,
        description="Optional head filter in the form 'user:branch' or 'org:branch'.",
    )
    limit: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Max PR summaries to return. Hard cap at 100; defaults to 25.",
    )


class ListPullRequestsOutput(BaseModel):
    context: str
    pull_requests: list[PullRequestSummary]
    total: int = Field(description="PRs returned by GitHub before the limit was applied.")
    returned: int = Field(description="PRs included in this response after the limit.")
    truncated: bool = Field(description="True when total exceeded limit and results were trimmed.")
    warnings: list[str] = Field(default_factory=list)


class CreatePullRequestInput(GitHubRepositoryInput):
    head: str = Field(
        min_length=1,
        description="Source branch with the changes; use 'owner:branch' for a cross-fork PR.",
    )
    base: str = Field(
        min_length=1,
        default="main",
        description="Target branch the PR merges into.",
    )
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(
        default="",
        description="Markdown body. Include rationale, screenshots, and test plan.",
    )
    draft: bool = Field(
        default=False,
        description="If true, the pull request is opened as a draft.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Safety flag. The PR is only created when this is true. "
            "When false, the tool returns a dry-run preview of what would be sent."
        ),
    )


class CreatePullRequestOutput(BaseModel):
    context: str
    number: int | None = None
    html_url: HttpUrl | None = None
    title: str
    draft: bool | None = None
    dry_run: bool = Field(
        default=False,
        description="True when the caller did not set confirm=True; no PR was created.",
    )


class CompareRefsInput(GitHubRepositoryInput):
    base_ref: str = Field(description="Base ref, e.g. a previous tag or main.")
    head_ref: str = Field(description="Head ref, e.g. a branch, SHA, or newer tag.")


class CompareRefsOutput(BaseModel):
    context: str
    base_ref: str
    head_ref: str
    status: str | None = None
    ahead_by: int
    behind_by: int
    total_commits: int
    files_changed: int
    commit_messages: list[str] = Field(default_factory=list)


class PullRequestFileDiff(BaseModel):
    filename: str
    status: str | None = None
    additions: int | None = None
    deletions: int | None = None
    changes: int | None = None
    patch: str = Field(default="", description="Raw unified patch, possibly truncated.")
    original_lines: int = Field(description="Line count of the upstream patch before truncation.")
    returned_lines: int = Field(description="Line count actually returned in `patch`.")
    truncated: bool = Field(description="True when the upstream patch was longer than the cap.")


class GetPullRequestDiffInput(GitHubRepositoryInput):
    pull_number: int = Field(ge=1, description="GitHub pull request number.")
    max_files: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of changed files to include in the response.",
    )
    max_lines_per_file: int = Field(
        default=400,
        ge=20,
        le=2000,
        description="Trailing patch lines kept per file; the rest is truncated.",
    )


class GetPullRequestDiffOutput(BaseModel):
    context: str
    pull_number: int
    title: str | None = None
    state: str | None = None
    draft: bool | None = None
    head_ref: str | None = None
    base_ref: str | None = None
    head_sha: str | None = None
    base_sha: str | None = None
    html_url: HttpUrl | None = None
    total_files: int
    returned_files: int
    files_truncated: bool
    files: list[PullRequestFileDiff] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GitHubWorkflowRunSummary(BaseModel):
    id: int
    name: str | None = None
    status: str | None = None
    conclusion: str | None = None
    event: str | None = None
    head_branch: str | None = None
    head_sha: str | None = None
    html_url: HttpUrl | None = None
    created_at: str | None = None
    updated_at: str | None = None


class GitHubActionsJobSummary(BaseModel):
    id: int
    name: str
    status: str | None = None
    conclusion: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    html_url: HttpUrl | None = None


class GetWorkflowRunStatusInput(GitHubRepositoryInput):
    run_id: int = Field(description="GitHub Actions workflow run id.")


class GetWorkflowRunStatusOutput(BaseModel):
    context: str
    run: GitHubWorkflowRunSummary
    jobs: list[GitHubActionsJobSummary] = Field(default_factory=list)
    failed_jobs: list[GitHubActionsJobSummary] = Field(default_factory=list)


class GetActionsJobLogInput(GitHubRepositoryInput):
    job_id: int
    tail: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Number of trailing log lines to return.",
    )


class GetActionsJobLogOutput(BaseModel):
    context: str
    job_id: int
    log_tail: str
    returned_lines: int
    truncated: bool
