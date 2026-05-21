from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, HttpUrl, model_validator


class GitLabProjectInput(BaseModel):
    context_url: HttpUrl = Field(
        description="Any URL on the target GitLab host; used to resolve the context."
    )
    project_path: str = Field(
        description="Full project path with namespace, e.g. 'group/project'.",
        pattern=r"^[^/\s][^\s]*/[^\s]+$",
    )


class CreateMergeRequestInput(GitLabProjectInput):
    source_branch: str = Field(min_length=1)
    target_branch: str = Field(min_length=1, default="main")
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(
        default="",
        description="Markdown body. Include rationale, screenshots, and test plan.",
    )
    remove_source_branch: bool = Field(
        default=False,
        description="If true, GitLab deletes the source branch after merge.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Safety flag. The MR is only created when this is true. "
            "When false, the tool returns a dry-run preview of what would be sent."
        ),
    )


class CreateMergeRequestOutput(BaseModel):
    context: str
    iid: int | None = None
    web_url: HttpUrl | None = None
    title: str
    dry_run: bool = Field(
        default=False,
        description="True when the caller did not set confirm=True; no MR was created.",
    )


class GitLabJobSummary(BaseModel):
    id: int
    name: str
    status: str
    stage: str | None = None
    web_url: HttpUrl | None = None


class GitLabPipelineSummary(BaseModel):
    id: int
    iid: int | None = None
    ref: str | None = None
    sha: str | None = None
    status: str
    web_url: HttpUrl | None = None
    created_at: str | None = None
    updated_at: str | None = None


class GetPipelineStatusInput(GitLabProjectInput):
    pipeline_id: int | None = Field(
        default=None,
        description="GitLab pipeline id. Provide this or ref.",
    )
    ref: str | None = Field(
        default=None,
        description=(
            "Branch/tag/ref name. Used to fetch the latest pipeline when pipeline_id is absent."
        ),
    )

    @model_validator(mode="after")
    def require_pipeline_id_or_ref(self) -> Self:
        if self.pipeline_id is None and not self.ref:
            raise ValueError("Provide pipeline_id or ref")
        return self


class GetPipelineStatusOutput(BaseModel):
    context: str
    pipeline: GitLabPipelineSummary | None
    failed_jobs: list[GitLabJobSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GetJobLogInput(GitLabProjectInput):
    job_id: int
    tail: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Number of trailing log lines to return.",
    )


class GetJobLogOutput(BaseModel):
    context: str
    job_id: int
    trace_tail: str
    returned_lines: int
    truncated: bool


class ListMergeRequestsInput(GitLabProjectInput):
    state: Literal["opened", "closed", "locked", "merged", "all"] = "opened"
    author: str | None = Field(
        default=None,
        description="Optional GitLab username to filter by author.",
    )


class MergeRequestSummary(BaseModel):
    iid: int
    title: str
    state: str
    draft: bool | None = None
    author_username: str | None = None
    source_branch: str | None = None
    target_branch: str | None = None
    web_url: HttpUrl | None = None
    updated_at: str | None = None


class ListMergeRequestsOutput(BaseModel):
    context: str
    merge_requests: list[MergeRequestSummary]


class CompareRefsInput(GitLabProjectInput):
    from_ref: str = Field(description="Base ref, e.g. a previous tag or main.")
    to_ref: str = Field(description="Head ref, e.g. a branch, SHA, or newer tag.")


class CompareRefsOutput(BaseModel):
    context: str
    from_ref: str
    to_ref: str
    compare_timeout: bool = False
    same: bool = False
    commits_count: int
    diffs_count: int
    commit_titles: list[str] = Field(default_factory=list)


FailureKind = Literal["lint", "test", "build", "dependency", "infra", "unknown"]


class DiagnosePipelineFailureInput(GitLabProjectInput):
    pipeline_id: int
    tail: int = Field(
        default=120,
        ge=20,
        le=500,
        description="Number of trailing log lines to include per failed job.",
    )
    max_jobs: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum failed jobs to include with log tails.",
    )


class FailedJobDiagnosis(BaseModel):
    job: GitLabJobSummary
    failure_kind: FailureKind
    trace_tail: str
    returned_lines: int
    truncated: bool
    hints: list[str] = Field(default_factory=list)


class DiagnosePipelineFailureOutput(BaseModel):
    context: str
    pipeline: GitLabPipelineSummary
    failed_jobs_count: int
    analyzed_jobs_count: int
    likely_failure_kind: FailureKind
    diagnoses: list[FailedJobDiagnosis]
    summary: str
    next_steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RetryFailedJobsInput(GitLabProjectInput):
    pipeline_id: int
    confirm: bool = Field(
        default=False,
        description="Safety flag. Failed jobs are retried only when true.",
    )


class RetryFailedJobsOutput(BaseModel):
    context: str
    pipeline_id: int
    retried_jobs: list[GitLabJobSummary] = Field(default_factory=list)
    dry_run: bool


class CancelPipelineInput(GitLabProjectInput):
    pipeline_id: int
    confirm: bool = Field(
        default=False,
        description="Safety flag. The pipeline is cancelled only when true.",
    )


class CancelPipelineOutput(BaseModel):
    context: str
    pipeline: GitLabPipelineSummary | None = None
    dry_run: bool


class MergeRequestPosition(BaseModel):
    base_sha: str
    start_sha: str
    head_sha: str
    position_type: Literal["text"] = "text"
    new_path: str | None = None
    old_path: str | None = None
    new_line: int | None = None
    old_line: int | None = None


class PostMergeRequestCommentInput(GitLabProjectInput):
    mr_iid: int
    body: str = Field(min_length=1, max_length=10000)
    position: MergeRequestPosition | None = Field(
        default=None,
        description="Optional GitLab diff position for line-level discussions.",
    )
    confirm: bool = Field(
        default=False,
        description="Safety flag. The comment is posted only when true.",
    )


class PostMergeRequestCommentOutput(BaseModel):
    context: str
    mr_iid: int
    note_id: int | None = None
    discussion_id: str | None = None
    web_url: HttpUrl | None = None
    dry_run: bool


class PostMergeRequestLineCommentInput(GitLabProjectInput):
    mr_iid: int
    body: str = Field(min_length=1, max_length=10000)
    new_path: str | None = Field(
        default=None,
        description="Path in the MR's head ref. Required for added or modified lines.",
    )
    old_path: str | None = Field(
        default=None,
        description=(
            "Path in the MR's base ref. Provide for deleted lines or alongside new_path on renames."
        ),
    )
    new_line: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Line number in the new file. Required when commenting on an added/changed line."
        ),
    )
    old_line: int | None = Field(
        default=None,
        ge=1,
        description="Line number in the old file. Required when commenting on a removed line.",
    )
    confirm: bool = Field(
        default=False,
        description="Safety flag. The comment is posted only when true.",
    )

    @model_validator(mode="after")
    def require_path_and_line(self) -> Self:
        if self.new_path is None and self.old_path is None:
            raise ValueError("Provide new_path or old_path (or both for renames).")
        if self.new_line is None and self.old_line is None:
            raise ValueError("Provide new_line or old_line.")
        return self


class PostMergeRequestLineCommentOutput(BaseModel):
    context: str
    mr_iid: int
    discussion_id: str | None = None
    new_path: str | None = None
    old_path: str | None = None
    new_line: int | None = None
    old_line: int | None = None
    base_sha: str | None = None
    start_sha: str | None = None
    head_sha: str | None = None
    dry_run: bool


class ApproveMergeRequestInput(GitLabProjectInput):
    mr_iid: int
    confirm: bool = Field(
        default=False,
        description="Safety flag. The MR is approved only when true.",
    )


class ApproveMergeRequestOutput(BaseModel):
    context: str
    mr_iid: int
    approved: bool
    dry_run: bool


class SetMergeRequestReadyInput(GitLabProjectInput):
    mr_iid: int
    confirm: bool = Field(
        default=False,
        description="Safety flag. The MR is marked ready only when true.",
    )


class SetMergeRequestReadyOutput(BaseModel):
    context: str
    mr_iid: int
    title: str | None = None
    draft: bool | None = None
    web_url: HttpUrl | None = None
    dry_run: bool


class GetMergeRequestDiffInput(GitLabProjectInput):
    mr_iid: int = Field(description="GitLab MR iid (project-scoped, not the global id).")
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
        description="Trailing diff lines kept per file; the rest is truncated.",
    )


class MergeRequestFileDiff(BaseModel):
    old_path: str | None = None
    new_path: str | None = None
    new_file: bool = False
    renamed_file: bool = False
    deleted_file: bool = False
    diff: str = Field(default="", description="Raw unified diff, possibly truncated.")
    original_lines: int = Field(description="Line count of the upstream diff before truncation.")
    returned_lines: int = Field(description="Line count actually returned in `diff`.")
    truncated: bool = Field(description="True when the upstream diff was longer than the cap.")


class GetMergeRequestDiffOutput(BaseModel):
    context: str
    mr_iid: int
    title: str | None = None
    state: str | None = None
    source_branch: str | None = None
    target_branch: str | None = None
    base_sha: str | None = None
    start_sha: str | None = None
    head_sha: str | None = None
    web_url: HttpUrl | None = None
    total_files: int = Field(description="Number of changed files reported by GitLab.")
    returned_files: int = Field(description="Number of files included in `files`.")
    files_truncated: bool = Field(description="True when `total_files` exceeds `max_files`.")
    files: list[MergeRequestFileDiff] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TriggerPipelineInput(GitLabProjectInput):
    ref: str
    variables: dict[str, str] = Field(default_factory=dict)
    confirm: bool = Field(
        default=False,
        description="Safety flag. The pipeline is triggered only when true.",
    )


class TriggerPipelineOutput(BaseModel):
    context: str
    pipeline: GitLabPipelineSummary | None = None
    dry_run: bool
