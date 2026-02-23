"""
Tests for cicd_pipeline.py
===========================
Coverage: pipeline definition, YAML export, stage results, status transitions,
metrics calculation, subprocess mocking, retry logic, list and delete operations.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from cicd_pipeline import (
    CIPipeline,
    PipelineEngine,
    PipelineRun,
    Stage,
    StageResult,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine(tmp_path: Path) -> PipelineEngine:
    """PipelineEngine wired to a temporary SQLite database."""
    return PipelineEngine(db_path=tmp_path / "test-pipeline.db")


@pytest.fixture
def simple_stages() -> list[dict]:
    return [
        {
            "name": "lint",
            "type": "lint",
            "command": "echo lint-ok",
            "timeout_secs": 30,
            "on_failure": "stop",
            "retry_count": 0,
            "env_vars": {},
        },
        {
            "name": "test",
            "type": "test",
            "command": "echo test-ok",
            "timeout_secs": 60,
            "on_failure": "continue",
            "retry_count": 0,
            "env_vars": {},
        },
    ]


@pytest.fixture
def pipeline(engine: PipelineEngine, simple_stages: list[dict]) -> CIPipeline:
    return engine.define_pipeline(
        name="test-pipeline",
        repo_url="https://github.com/BlackRoad-OS/test-repo",
        branch="main",
        stages=simple_stages,
    )


# ─── Stage dataclass ──────────────────────────────────────────────────────────


class TestStageDataclass:
    def test_to_dict_round_trip(self) -> None:
        s = Stage(
            name="build",
            type="build",
            command="make build",
            timeout_secs=120,
            on_failure="retry",
            retry_count=3,
            env_vars={"CI": "true", "NODE_ENV": "test"},
        )
        d = s.to_dict()
        s2 = Stage.from_dict(d)
        assert s2.name == "build"
        assert s2.retry_count == 3
        assert s2.env_vars == {"CI": "true", "NODE_ENV": "test"}

    def test_validate_valid_stage(self) -> None:
        s = Stage(name="s", type="test", command="echo hi")
        s.validate()  # should not raise

    def test_validate_invalid_type_raises(self) -> None:
        s = Stage(name="s", type="unknown", command="echo hi")
        with pytest.raises(ValueError, match="type"):
            s.validate()

    def test_validate_invalid_on_failure_raises(self) -> None:
        s = Stage(name="s", type="test", command="echo hi", on_failure="ignore")
        with pytest.raises(ValueError, match="on_failure"):
            s.validate()

    def test_validate_negative_timeout_raises(self) -> None:
        s = Stage(name="s", type="test", command="echo hi", timeout_secs=-1)
        with pytest.raises(ValueError, match="timeout_secs"):
            s.validate()


# ─── StageResult dataclass ────────────────────────────────────────────────────


class TestStageResultDataclass:
    def test_to_dict_round_trip(self) -> None:
        sr = StageResult(
            stage_name="lint",
            status="passed",
            started_at="2025-01-01T00:00:00+00:00",
            duration_ms=456,
            output="All good",
            exit_code=0,
        )
        sr2 = StageResult.from_dict(sr.to_dict())
        assert sr2.stage_name == "lint"
        assert sr2.duration_ms == 456
        assert sr2.exit_code == 0

    def test_passed_property(self) -> None:
        sr = StageResult("s", "passed", "t", 0, "", 0)
        assert sr.passed is True
        assert sr.failed is False

    def test_failed_property(self) -> None:
        sr = StageResult("s", "failed", "t", 0, "", 1)
        assert sr.failed is True
        assert sr.passed is False


# ─── Pipeline definition ──────────────────────────────────────────────────────


class TestDefinePipeline:
    def test_returns_cicd_pipeline(
        self, engine: PipelineEngine, simple_stages: list[dict]
    ) -> None:
        p = engine.define_pipeline("my-app", "https://github.com/org/repo", "main", simple_stages)
        assert isinstance(p, CIPipeline)
        assert p.name == "my-app"
        assert p.branch == "main"

    def test_stages_are_stage_objects(
        self, engine: PipelineEngine, simple_stages: list[dict]
    ) -> None:
        p = engine.define_pipeline("p", "https://g.io", "main", simple_stages)
        assert all(isinstance(s, Stage) for s in p.stages)
        assert len(p.stages) == 2

    def test_unique_ids_generated(
        self, engine: PipelineEngine, simple_stages: list[dict]
    ) -> None:
        p1 = engine.define_pipeline("p1", "https://a.io", "main", simple_stages)
        p2 = engine.define_pipeline("p2", "https://b.io", "main", simple_stages)
        assert p1.id != p2.id

    def test_webhook_secret_non_empty(
        self, engine: PipelineEngine, simple_stages: list[dict]
    ) -> None:
        p = engine.define_pipeline("p", "https://g.io", "main", simple_stages)
        assert len(p.webhook_secret) >= 32

    def test_persisted_to_db(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        loaded = engine._load_pipeline(pipeline.id)
        assert loaded is not None
        assert loaded.name == pipeline.name
        assert len(loaded.stages) == 2

    def test_invalid_stage_raises(self, engine: PipelineEngine) -> None:
        bad_stages = [{"name": "x", "type": "invalid", "command": "echo hi"}]
        with pytest.raises(ValueError, match="type"):
            engine.define_pipeline("p", "https://g.io", "main", bad_stages)


# ─── List and delete ──────────────────────────────────────────────────────────


class TestListAndDelete:
    def test_list_pipelines(
        self, engine: PipelineEngine, simple_stages: list[dict]
    ) -> None:
        engine.define_pipeline("alpha", "https://a.io", "main", simple_stages)
        engine.define_pipeline("beta", "https://b.io", "develop", simple_stages)
        names = [p.name for p in engine.list_pipelines()]
        assert "alpha" in names
        assert "beta" in names

    def test_list_returns_newest_first(
        self, engine: PipelineEngine, simple_stages: list[dict]
    ) -> None:
        engine.define_pipeline("first", "https://a.io", "main", simple_stages)
        engine.define_pipeline("second", "https://b.io", "main", simple_stages)
        pipelines = engine.list_pipelines()
        assert pipelines[0].name == "second"

    def test_delete_pipeline(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        assert engine.delete_pipeline(pipeline.id) is True
        assert engine._load_pipeline(pipeline.id) is None

    def test_delete_pipeline_removes_runs(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        engine.run_pipeline(pipeline.id)
        engine.delete_pipeline(pipeline.id)
        status_runs = None
        with engine._conn() as conn:
            status_runs = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE pipeline_id = ?", (pipeline.id,)
            ).fetchone()[0]
        assert status_runs == 0

    def test_delete_nonexistent_returns_false(self, engine: PipelineEngine) -> None:
        assert engine.delete_pipeline(str(uuid.uuid4())) is False


# ─── Pipeline execution ───────────────────────────────────────────────────────


class TestRunPipeline:
    def test_all_stages_pass(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        run = engine.run_pipeline(pipeline.id)
        assert run.status == "passed"
        assert len(run.stage_results) == 2
        assert all(r.status == "passed" for r in run.stage_results)

    def test_run_records_timing(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        run = engine.run_pipeline(pipeline.id)
        assert run.duration_ms >= 0
        assert run.finished_at is not None
        assert run.started_at is not None
        for sr in run.stage_results:
            assert sr.duration_ms >= 0

    def test_stop_on_failure(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "fail-first",
                "type": "build",
                "command": "exit 1",
                "timeout_secs": 10,
                "on_failure": "stop",
                "retry_count": 0,
                "env_vars": {},
            },
            {
                "name": "should-not-run",
                "type": "test",
                "command": "echo should-not-execute",
                "timeout_secs": 10,
                "on_failure": "stop",
                "retry_count": 0,
                "env_vars": {},
            },
        ]
        p = engine.define_pipeline("stop-test", "https://g.io", "main", stages)
        run = engine.run_pipeline(p.id)
        assert run.status == "failed"
        assert len(run.stage_results) == 1
        assert run.stage_results[0].stage_name == "fail-first"
        assert run.stage_results[0].status == "failed"

    def test_continue_on_failure(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "fail-continue",
                "type": "build",
                "command": "exit 1",
                "timeout_secs": 10,
                "on_failure": "continue",
                "retry_count": 0,
                "env_vars": {},
            },
            {
                "name": "runs-anyway",
                "type": "test",
                "command": "echo still-running",
                "timeout_secs": 10,
                "on_failure": "stop",
                "retry_count": 0,
                "env_vars": {},
            },
        ]
        p = engine.define_pipeline("continue-test", "https://g.io", "main", stages)
        run = engine.run_pipeline(p.id)
        assert run.status == "failed"
        assert len(run.stage_results) == 2
        assert run.stage_results[0].status == "failed"
        assert run.stage_results[1].status == "passed"

    def test_run_persisted_to_db(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        run = engine.run_pipeline(pipeline.id)
        fetched = engine.get_run(run.id)
        assert fetched.id == run.id
        assert fetched.status == run.status

    def test_trigger_stored(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        run = engine.run_pipeline(pipeline.id, trigger="push")
        assert engine.get_run(run.id).trigger == "push"

    def test_run_unknown_pipeline_raises(self, engine: PipelineEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.run_pipeline(str(uuid.uuid4()))

    def test_mock_subprocess_called(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "mock output"
        mock_result.stderr = ""

        with patch("cicd_pipeline.subprocess.run", return_value=mock_result) as mock_run:
            run = engine.run_pipeline(pipeline.id)
        assert run.status == "passed"
        assert mock_run.call_count == len(pipeline.stages)

    def test_stage_env_vars_forwarded(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "env-check",
                "type": "test",
                "command": 'test "$MY_VAR" = "hello"',
                "timeout_secs": 10,
                "on_failure": "stop",
                "retry_count": 0,
                "env_vars": {"MY_VAR": "hello"},
            }
        ]
        p = engine.define_pipeline("env-test", "https://g.io", "main", stages)
        run = engine.run_pipeline(p.id)
        assert run.stage_results[0].status == "passed"


# ─── Status transitions ───────────────────────────────────────────────────────


class TestStatusTransitions:
    def test_get_status_returns_pipeline_and_runs(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        engine.run_pipeline(pipeline.id)
        status = engine.get_status(pipeline.id)
        assert "pipeline" in status
        assert "recent_runs" in status
        assert status["pipeline"]["id"] == pipeline.id
        assert len(status["recent_runs"]) >= 1

    def test_get_status_limits_to_10(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        for _ in range(12):
            engine.run_pipeline(pipeline.id)
        status = engine.get_status(pipeline.id)
        assert len(status["recent_runs"]) <= 10

    def test_get_run_raises_for_unknown(self, engine: PipelineEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.get_run(str(uuid.uuid4()))

    def test_cancel_nonexistent_run_returns_false(self, engine: PipelineEngine) -> None:
        assert engine.cancel_run(str(uuid.uuid4())) is False

    def test_cancel_persisted_running_run(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        # Manually insert a "running" run to test DB-level cancel
        run = PipelineRun(
            id=str(uuid.uuid4()),
            pipeline_id=pipeline.id,
            trigger="manual",
            status="running",
            started_at="2025-01-01T00:00:00+00:00",
            finished_at=None,
            duration_ms=0,
            stage_results=[],
        )
        engine._save_run(run)
        ok = engine.cancel_run(run.id)
        assert ok is True
        fetched = engine.get_run(run.id)
        assert fetched.status == "cancelled"


# ─── Retry stage ──────────────────────────────────────────────────────────────


class TestRetryStage:
    def test_retry_failed_stage_passes(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "flakey",
                "type": "test",
                "command": "exit 1",
                "timeout_secs": 10,
                "on_failure": "stop",
                "retry_count": 0,
                "env_vars": {},
            }
        ]
        p = engine.define_pipeline("retry-test", "https://g.io", "main", stages)
        run = engine.run_pipeline(p.id)
        assert run.stage_results[0].status == "failed"

        # Patch the stage command in DB to succeed on retry
        pipeline = engine._load_pipeline(p.id)
        pipeline.stages[0].command = "echo now-passing"
        with engine._conn() as conn:
            conn.execute(
                "UPDATE pipelines SET stages = ? WHERE id = ?",
                (json.dumps([s.to_dict() for s in pipeline.stages]), p.id),
            )

        result = engine.retry_stage(run.id, "flakey")
        assert result.status == "passed"

        updated_run = engine.get_run(run.id)
        assert updated_run.status == "passed"

    def test_retry_updates_existing_result(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "build",
                "type": "build",
                "command": "echo build-ok",
                "timeout_secs": 10,
                "on_failure": "stop",
                "retry_count": 0,
                "env_vars": {},
            }
        ]
        p = engine.define_pipeline("upd-test", "https://g.io", "main", stages)
        run = engine.run_pipeline(p.id)
        original_count = len(run.stage_results)

        engine.retry_stage(run.id, "build")
        updated = engine.get_run(run.id)
        # Result replaced in-place, not appended
        assert len(updated.stage_results) == original_count

    def test_retry_unknown_stage_raises(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        run = engine.run_pipeline(pipeline.id)
        with pytest.raises(ValueError, match="not found"):
            engine.retry_stage(run.id, "nonexistent-stage")

    def test_retry_unknown_run_raises(self, engine: PipelineEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.retry_stage(str(uuid.uuid4()), "build")


# ─── YAML export ──────────────────────────────────────────────────────────────


class TestExportYaml:
    def test_produces_valid_yaml(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        yaml_str = engine.export_yaml(pipeline.id)
        parsed = yaml.safe_load(yaml_str)
        assert isinstance(parsed, dict)

    def test_contains_required_keys(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        parsed = yaml.safe_load(engine.export_yaml(pipeline.id))
        assert "name" in parsed
        assert "on" in parsed
        assert "jobs" in parsed

    def test_pipeline_name_in_yaml(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        assert pipeline.name in engine.export_yaml(pipeline.id)

    def test_stage_commands_in_yaml(
        self, engine: PipelineEngine, simple_stages: list[dict]
    ) -> None:
        p = engine.define_pipeline("cmd-test", "https://g.io", "main", simple_stages)
        yaml_str = engine.export_yaml(p.id)
        assert "echo lint-ok" in yaml_str
        assert "echo test-ok" in yaml_str

    def test_branch_in_on_block(
        self, engine: PipelineEngine, simple_stages: list[dict]
    ) -> None:
        p = engine.define_pipeline("branch-test", "https://g.io", "develop", simple_stages)
        parsed = yaml.safe_load(engine.export_yaml(p.id))
        assert "develop" in parsed["on"]["push"]["branches"]

    def test_job_needs_chaining(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "lint-stage",
                "type": "lint",
                "command": "echo lint",
                "timeout_secs": 10,
                "on_failure": "stop",
                "retry_count": 0,
                "env_vars": {},
            },
            {
                "name": "build-stage",
                "type": "build",
                "command": "echo build",
                "timeout_secs": 10,
                "on_failure": "stop",
                "retry_count": 0,
                "env_vars": {},
            },
        ]
        p = engine.define_pipeline("chain-test", "https://g.io", "main", stages)
        parsed = yaml.safe_load(engine.export_yaml(p.id))
        # build job should depend on lint job
        assert "needs" in parsed["jobs"]["build"]
        assert "lint" in parsed["jobs"]["build"]["needs"]

    def test_continue_on_error_flag(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "test-cont",
                "type": "test",
                "command": "echo test",
                "timeout_secs": 10,
                "on_failure": "continue",
                "retry_count": 0,
                "env_vars": {},
            }
        ]
        p = engine.define_pipeline("cont-test", "https://g.io", "main", stages)
        parsed = yaml.safe_load(engine.export_yaml(p.id))
        test_steps = parsed["jobs"]["test"]["steps"]
        cont_step = next(s for s in test_steps if s.get("name") == "test-cont")
        assert cont_step.get("continue-on-error") is True

    def test_export_unknown_pipeline_raises(self, engine: PipelineEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_yaml(str(uuid.uuid4()))


# ─── Metrics ──────────────────────────────────────────────────────────────────


class TestMetrics:
    def test_empty_metrics(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        m = engine.get_metrics(pipeline.id)
        assert m["total_runs"] == 0
        assert m["pass_rate"] == 0.0
        assert m["failure_rate"] == 0.0
        assert m["most_failing_stage"] is None

    def test_pass_rate_after_passing_runs(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        engine.run_pipeline(pipeline.id)
        engine.run_pipeline(pipeline.id)
        m = engine.get_metrics(pipeline.id)
        assert m["total_runs"] == 2
        assert m["pass_rate"] == 100.0
        assert m["failure_rate"] == 0.0

    def test_failure_rate_tracked(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "always-fail",
                "type": "test",
                "command": "exit 1",
                "timeout_secs": 10,
                "on_failure": "continue",
                "retry_count": 0,
                "env_vars": {},
            }
        ]
        p = engine.define_pipeline("fail-metrics", "https://g.io", "main", stages)
        engine.run_pipeline(p.id)
        engine.run_pipeline(p.id)
        m = engine.get_metrics(p.id)
        assert m["failure_rate"] == 100.0
        assert m["pass_rate"] == 0.0

    def test_most_failing_stage_identified(self, engine: PipelineEngine) -> None:
        stages = [
            {
                "name": "bad-stage",
                "type": "test",
                "command": "exit 1",
                "timeout_secs": 10,
                "on_failure": "continue",
                "retry_count": 0,
                "env_vars": {},
            },
            {
                "name": "good-stage",
                "type": "build",
                "command": "echo ok",
                "timeout_secs": 10,
                "on_failure": "continue",
                "retry_count": 0,
                "env_vars": {},
            },
        ]
        p = engine.define_pipeline("most-fail", "https://g.io", "main", stages)
        engine.run_pipeline(p.id)
        engine.run_pipeline(p.id)
        m = engine.get_metrics(p.id)
        assert m["most_failing_stage"] == "bad-stage"

    def test_avg_duration_positive(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        engine.run_pipeline(pipeline.id)
        m = engine.get_metrics(pipeline.id)
        assert m["avg_duration_ms"] >= 0

    def test_last_run_status(
        self, engine: PipelineEngine, pipeline: CIPipeline
    ) -> None:
        engine.run_pipeline(pipeline.id)
        m = engine.get_metrics(pipeline.id)
        assert m["last_run_status"] == "passed"

    def test_metrics_unknown_pipeline_raises(self, engine: PipelineEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.get_metrics(str(uuid.uuid4()))
