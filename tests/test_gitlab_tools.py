from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response
from pydantic import ValidationError

from anvil.gitlab.models import (
    ApproveMergeRequestInput,
    CancelPipelineInput,
    CompareRefsInput,
    CreateMergeRequestInput,
    DiagnosePipelineFailureInput,
    GetJobLogInput,
    GetMergeRequestDiffInput,
    GetPipelineStatusInput,
    ListMergeRequestsInput,
    PostMergeRequestCommentInput,
    PostMergeRequestLineCommentInput,
    RetryFailedJobsInput,
    SetMergeRequestReadyInput,
    TriggerPipelineInput,
)
from anvil.gitlab.tools import (
    approve_gitlab_merge_request,
    cancel_gitlab_pipeline,
    compare_gitlab_refs,
    create_gitlab_merge_request,
    diagnose_gitlab_pipeline_failure,
    get_gitlab_job_log,
    get_gitlab_mr_diff,
    get_gitlab_pipeline_status,
    list_gitlab_merge_requests,
    post_gitlab_mr_comment,
    post_gitlab_mr_line_comment,
    retry_gitlab_failed_jobs,
    set_gitlab_mr_ready,
    trigger_gitlab_pipeline,
)


@pytest.mark.asyncio
async def test_create_mr_dry_run_does_not_call_gitlab(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        result = await create_gitlab_merge_request(
            CreateMergeRequestInput(
                context_url="https://gitlab.example.com/group/project",
                project_path="group/project",
                source_branch="feat/x",
                target_branch="main",
                title="feat: x",
                description="why",
                confirm=False,
            )
        )

        assert result.dry_run is True
        assert result.iid is None
        assert mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_create_mr_confirmed_posts_payload(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests"
    ).mock(
        return_value=Response(
            201,
            json={
                "iid": 7,
                "title": "feat: x",
                "web_url": "https://gitlab.example.com/group/project/-/merge_requests/7",
            },
        )
    )

    result = await create_gitlab_merge_request(
        CreateMergeRequestInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            source_branch="feat/x",
            target_branch="main",
            title="feat: x",
            description="why",
            confirm=True,
        )
    )

    assert result.dry_run is False
    assert result.iid == 7
    assert route.called
    sent_token = route.calls.last.request.headers["PRIVATE-TOKEN"]
    assert sent_token == "gitlab-token"


@pytest.mark.asyncio
@respx.mock
async def test_get_pipeline_status_returns_failed_jobs(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123").mock(
        return_value=Response(
            200,
            json={
                "id": 123,
                "iid": 8,
                "ref": "main",
                "sha": "abc",
                "status": "failed",
                "web_url": "https://gitlab.example.com/group/project/-/pipelines/123",
            },
        )
    )
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123/jobs").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": 456,
                    "name": "pytest",
                    "status": "failed",
                    "stage": "test",
                    "web_url": "https://gitlab.example.com/group/project/-/jobs/456",
                },
                {"id": 457, "name": "ruff", "status": "success", "stage": "lint"},
            ],
        )
    )

    result = await get_gitlab_pipeline_status(
        GetPipelineStatusInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            pipeline_id=123,
        )
    )

    assert result.pipeline is not None
    assert result.pipeline.status == "failed"
    assert len(result.failed_jobs) == 1
    assert result.failed_jobs[0].name == "pytest"


@pytest.mark.asyncio
@respx.mock
async def test_get_job_log_returns_tail(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/jobs/456/trace").mock(
        return_value=Response(200, text="line1\nline2\nline3\n")
    )

    result = await get_gitlab_job_log(
        GetJobLogInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            job_id=456,
            tail=2,
        )
    )

    assert result.trace_tail == "line2\nline3"
    assert result.returned_lines == 2
    assert result.truncated is True


@pytest.mark.asyncio
@respx.mock
async def test_list_merge_requests_returns_compact_summaries(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests").mock(
        return_value=Response(
            200,
            json=[
                {
                    "iid": 7,
                    "title": "feat: x",
                    "state": "opened",
                    "draft": False,
                    "author": {"username": "alice"},
                    "source_branch": "feat/x",
                    "target_branch": "main",
                    "web_url": "https://gitlab.example.com/group/project/-/merge_requests/7",
                    "updated_at": "2026-05-12T00:00:00Z",
                }
            ],
        )
    )

    result = await list_gitlab_merge_requests(
        ListMergeRequestsInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            state="opened",
            author="alice",
        )
    )

    assert len(result.merge_requests) == 1
    assert result.merge_requests[0].iid == 7
    assert result.merge_requests[0].author_username == "alice"


@pytest.mark.asyncio
@respx.mock
async def test_list_merge_requests_applies_limit_and_flags_truncation(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests").mock(
        return_value=Response(
            200,
            json=[
                {"iid": i, "title": f"feat {i}", "state": "opened"} for i in range(5)
            ],
        )
    )

    result = await list_gitlab_merge_requests(
        ListMergeRequestsInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            limit=2,
        )
    )

    assert len(result.merge_requests) == 2
    assert result.returned == 2
    assert result.total == 5
    assert result.truncated is True
    assert any("limit" in warning.lower() for warning in result.warnings)


@pytest.mark.asyncio
@respx.mock
async def test_compare_refs_returns_counts_and_commit_titles(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/repository/compare").mock(
        return_value=Response(
            200,
            json={
                "compare_timeout": False,
                "same": False,
                "commits": [{"title": "fix: bug"}, {"message": "feat: thing\n\nbody"}],
                "diffs": [{"new_path": "a.py"}, {"new_path": "b.py"}],
            },
        )
    )

    result = await compare_gitlab_refs(
        CompareRefsInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            from_ref="v1.0.0",
            to_ref="main",
        )
    )

    assert result.commits_count == 2
    assert result.diffs_count == 2
    assert result.commit_titles == ["fix: bug", "feat: thing"]


@pytest.mark.asyncio
@respx.mock
async def test_get_mr_diff_returns_metadata_and_file_diffs(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/7/changes"
    ).mock(
        return_value=Response(
            200,
            json={
                "iid": 7,
                "title": "feat: x",
                "state": "opened",
                "source_branch": "feat/x",
                "target_branch": "main",
                "web_url": "https://gitlab.example.com/group/project/-/merge_requests/7",
                "diff_refs": {
                    "base_sha": "base123",
                    "start_sha": "start123",
                    "head_sha": "head123",
                },
                "changes": [
                    {
                        "old_path": "a.py",
                        "new_path": "a.py",
                        "new_file": False,
                        "renamed_file": False,
                        "deleted_file": False,
                        "diff": "@@ -1,2 +1,2 @@\n-old\n+new",
                    },
                    {
                        "old_path": None,
                        "new_path": "b.py",
                        "new_file": True,
                        "renamed_file": False,
                        "deleted_file": False,
                        "diff": "@@ -0,0 +1,1 @@\n+hello",
                    },
                ],
            },
        )
    )

    result = await get_gitlab_mr_diff(
        GetMergeRequestDiffInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=7,
        )
    )

    assert result.mr_iid == 7
    assert result.title == "feat: x"
    assert result.source_branch == "feat/x"
    assert result.head_sha == "head123"
    assert result.total_files == 2
    assert result.returned_files == 2
    assert result.files_truncated is False
    assert result.files[1].new_file is True
    assert result.files[0].diff.endswith("+new")
    assert result.files[0].truncated is False
    assert result.warnings == []


@pytest.mark.asyncio
@respx.mock
async def test_get_mr_diff_truncates_files_and_lines(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    long_diff = "\n".join(f"+line{i}" for i in range(50))
    respx.get(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/8/changes"
    ).mock(
        return_value=Response(
            200,
            json={
                "iid": 8,
                "title": "big",
                "state": "opened",
                "source_branch": "feat/big",
                "target_branch": "main",
                "diff_refs": {"base_sha": "b", "start_sha": "s", "head_sha": "h"},
                "changes": [
                    {"new_path": f"f{i}.py", "old_path": f"f{i}.py", "diff": long_diff}
                    for i in range(5)
                ],
            },
        )
    )

    result = await get_gitlab_mr_diff(
        GetMergeRequestDiffInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=8,
            max_files=2,
            max_lines_per_file=20,
        )
    )

    assert result.total_files == 5
    assert result.returned_files == 2
    assert result.files_truncated is True
    assert all(f.truncated for f in result.files)
    assert all(f.returned_lines == 20 for f in result.files)
    assert all(f.original_lines == 50 for f in result.files)
    assert len(result.warnings) == 2


@pytest.mark.asyncio
@respx.mock
async def test_diagnose_pipeline_failure_aggregates_failed_jobs_and_logs(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123").mock(
        return_value=Response(
            200,
            json={
                "id": 123,
                "iid": 8,
                "ref": "main",
                "sha": "abc",
                "status": "failed",
                "web_url": "https://gitlab.example.com/group/project/-/pipelines/123",
            },
        )
    )
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123/jobs").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": 456,
                    "name": "pytest",
                    "status": "failed",
                    "stage": "test",
                    "web_url": "https://gitlab.example.com/group/project/-/jobs/456",
                },
                {
                    "id": 457,
                    "name": "ruff",
                    "status": "failed",
                    "stage": "lint",
                    "web_url": "https://gitlab.example.com/group/project/-/jobs/457",
                },
                {"id": 458, "name": "build", "status": "success", "stage": "build"},
            ],
        )
    )
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/jobs/456/trace").mock(
        return_value=Response(
            200,
            text="setup\nrunning pytest\nAssertionError: expected 1\nFAILED tests/test_x.py\n",
        )
    )
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/jobs/457/trace").mock(
        return_value=Response(
            200,
            text=(
                "line0\n"
                "line1\n"
                "line2\n"
                "line3\n"
                "line4\n"
                "line5\n"
                "line6\n"
                "line7\n"
                "line8\n"
                "line9\n"
                "line10\n"
                "line11\n"
                "line12\n"
                "line13\n"
                "line14\n"
                "line15\n"
                "line16\n"
                "line17\n"
                "line18\n"
                "line19\n"
                "ruff check failed\n"
                "would reformat: src/app.py\n"
            ),
        )
    )

    result = await diagnose_gitlab_pipeline_failure(
        DiagnosePipelineFailureInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            pipeline_id=123,
            tail=20,
            max_jobs=5,
        )
    )

    assert result.pipeline.status == "failed"
    assert result.failed_jobs_count == 2
    assert result.analyzed_jobs_count == 2
    assert result.likely_failure_kind == "lint"
    assert [diagnosis.failure_kind for diagnosis in result.diagnoses] == ["test", "lint"]
    assert result.diagnoses[1].trace_tail.endswith("ruff check failed\nwould reformat: src/app.py")
    assert result.diagnoses[1].truncated is True
    assert result.warnings == []


@pytest.mark.asyncio
@respx.mock
async def test_diagnose_pipeline_failure_warns_when_max_jobs_limits_analysis(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123").mock(
        return_value=Response(200, json={"id": 123, "status": "failed"})
    )
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123/jobs").mock(
        return_value=Response(
            200,
            json=[
                {"id": 456, "name": "test-a", "status": "failed"},
                {"id": 457, "name": "test-b", "status": "failed"},
            ],
        )
    )
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/jobs/456/trace").mock(
        return_value=Response(200, text="pytest\nFAILED tests/test_a.py\n")
    )

    result = await diagnose_gitlab_pipeline_failure(
        DiagnosePipelineFailureInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            pipeline_id=123,
            max_jobs=1,
        )
    )

    assert result.failed_jobs_count == 2
    assert result.analyzed_jobs_count == 1
    assert result.warnings == ["Analyzed 1 of 2 failed jobs; increase max_jobs for more detail."]


@pytest.mark.asyncio
@respx.mock
async def test_retry_failed_jobs_dry_run_does_not_retry(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123/jobs").mock(
        return_value=Response(
            200,
            json=[
                {"id": 456, "name": "pytest", "status": "failed"},
                {"id": 457, "name": "ruff", "status": "success"},
            ],
        )
    )
    retry_route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/jobs/456/retry"
    ).mock(return_value=Response(201, json={"id": 789, "name": "pytest", "status": "pending"}))

    result = await retry_gitlab_failed_jobs(
        RetryFailedJobsInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            pipeline_id=123,
            confirm=False,
        )
    )

    assert result.dry_run is True
    assert [job.id for job in result.retried_jobs] == [456]
    assert retry_route.called is False


@pytest.mark.asyncio
@respx.mock
async def test_retry_failed_jobs_confirmed_retries_failed_jobs(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123/jobs").mock(
        return_value=Response(200, json=[{"id": 456, "name": "pytest", "status": "failed"}])
    )
    retry_route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/jobs/456/retry"
    ).mock(return_value=Response(201, json={"id": 789, "name": "pytest", "status": "pending"}))

    result = await retry_gitlab_failed_jobs(
        RetryFailedJobsInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            pipeline_id=123,
            confirm=True,
        )
    )

    assert result.dry_run is False
    assert result.retried_jobs[0].id == 789
    assert retry_route.called


@pytest.mark.asyncio
async def test_cancel_pipeline_dry_run_does_not_call_gitlab(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        result = await cancel_gitlab_pipeline(
            CancelPipelineInput(
                context_url="https://gitlab.example.com/group/project",
                project_path="group/project",
                pipeline_id=123,
                confirm=False,
            )
        )

    assert result.dry_run is True
    assert mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_cancel_pipeline_confirmed_posts_cancel(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/pipelines/123/cancel"
    ).mock(return_value=Response(200, json={"id": 123, "status": "canceled"}))

    result = await cancel_gitlab_pipeline(
        CancelPipelineInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            pipeline_id=123,
            confirm=True,
        )
    )

    assert result.pipeline is not None
    assert result.pipeline.status == "canceled"
    assert route.called


@pytest.mark.asyncio
async def test_post_mr_comment_dry_run_does_not_call_gitlab(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        result = await post_gitlab_mr_comment(
            PostMergeRequestCommentInput(
                context_url="https://gitlab.example.com/group/project",
                project_path="group/project",
                mr_iid=7,
                body="looks good",
                confirm=False,
            )
        )

    assert result.dry_run is True
    assert mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_post_mr_comment_confirmed_posts_note(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/7/notes"
    ).mock(
        return_value=Response(
            201,
            json={
                "id": 99,
                "web_url": "https://gitlab.example.com/group/project/-/merge_requests/7#note_99",
            },
        )
    )

    result = await post_gitlab_mr_comment(
        PostMergeRequestCommentInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=7,
            body="looks good",
            confirm=True,
        )
    )

    assert result.note_id == 99
    assert route.calls.last.request.content == b'{"body":"looks good"}'


def _mr_changes_response_for_line_comment() -> dict[str, object]:
    return {
        "iid": 7,
        "title": "feat: x",
        "state": "opened",
        "source_branch": "feat/x",
        "target_branch": "main",
        "diff_refs": {
            "base_sha": "base123",
            "start_sha": "start123",
            "head_sha": "head123",
        },
        "changes": [],
    }


@pytest.mark.asyncio
@respx.mock
async def test_post_mr_line_comment_dry_run_returns_position_only(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/7/changes"
    ).mock(return_value=Response(200, json=_mr_changes_response_for_line_comment()))
    post_route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/7/discussions"
    )

    result = await post_gitlab_mr_line_comment(
        PostMergeRequestLineCommentInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=7,
            new_path="src/foo.py",
            new_line=42,
            body="unreachable branch",
            confirm=False,
        )
    )

    assert result.dry_run is True
    assert result.discussion_id is None
    assert result.head_sha == "head123"
    assert result.new_line == 42
    assert post_route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_post_mr_line_comment_confirmed_posts_discussion_with_position(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/7/changes"
    ).mock(return_value=Response(200, json=_mr_changes_response_for_line_comment()))
    post_route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/7/discussions"
    ).mock(return_value=Response(201, json={"id": "disc-1"}))

    result = await post_gitlab_mr_line_comment(
        PostMergeRequestLineCommentInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=7,
            new_path="src/foo.py",
            new_line=42,
            body="unreachable branch",
            confirm=True,
        )
    )

    assert result.dry_run is False
    assert result.discussion_id == "disc-1"
    assert post_route.called
    sent = json.loads(post_route.calls.last.request.content.decode())
    assert sent["body"] == "unreachable branch"
    assert sent["position"]["new_path"] == "src/foo.py"
    assert sent["position"]["new_line"] == 42
    assert sent["position"]["head_sha"] == "head123"
    assert sent["position"]["position_type"] == "text"


@pytest.mark.asyncio
async def test_post_mr_line_comment_requires_path_and_line(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    with pytest.raises(ValidationError):
        PostMergeRequestLineCommentInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=7,
            body="x",
            new_line=10,
            confirm=False,
        )

    with pytest.raises(ValidationError):
        PostMergeRequestLineCommentInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=7,
            body="x",
            new_path="src/foo.py",
            confirm=False,
        )


@pytest.mark.asyncio
@respx.mock
async def test_approve_mr_confirmed_posts_approve(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.post(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/7/approve"
    ).mock(return_value=Response(201, json={"iid": 7}))

    result = await approve_gitlab_merge_request(
        ApproveMergeRequestInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=7,
            confirm=True,
        )
    )

    assert result.approved is True
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_set_mr_ready_confirmed_updates_draft_false(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.put(
        "https://gitlab.example.com/api/v4/projects/group%2Fproject/merge_requests/7"
    ).mock(
        return_value=Response(
            200,
            json={
                "iid": 7,
                "title": "feat: x",
                "draft": False,
                "web_url": "https://gitlab.example.com/group/project/-/merge_requests/7",
            },
        )
    )

    result = await set_gitlab_mr_ready(
        SetMergeRequestReadyInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            mr_iid=7,
            confirm=True,
        )
    )

    assert result.draft is False
    assert route.calls.last.request.content == b'{"draft":false}'


@pytest.mark.asyncio
@respx.mock
async def test_trigger_pipeline_confirmed_posts_pipeline(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    route = respx.post("https://gitlab.example.com/api/v4/projects/group%2Fproject/pipeline").mock(
        return_value=Response(
            201,
            json={
                "id": 321,
                "ref": "main",
                "status": "pending",
                "web_url": "https://gitlab.example.com/group/project/-/pipelines/321",
            },
        )
    )

    result = await trigger_gitlab_pipeline(
        TriggerPipelineInput(
            context_url="https://gitlab.example.com/group/project",
            project_path="group/project",
            ref="main",
            variables={"RUN_SLOW": "1"},
            confirm=True,
        )
    )

    assert result.pipeline is not None
    assert result.pipeline.id == 321
    assert b'"variables":[{"key":"RUN_SLOW","value":"1"}]' in route.calls.last.request.content
