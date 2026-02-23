#!/usr/bin/env python3
"""
BlackRoad CI/CD Pipeline Engine
================================
Production-grade pipeline orchestration with SQLite persistence,
subprocess execution, retry logic, YAML export, and rich CLI output.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# ─── ANSI Colors ──────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
GREEN   = "\033[32m"
RED     = "\033[31m"
YELLOW  = "\033[33m"
CYAN    = "\033[36m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
WHITE   = "\033[37m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class Stage:
    """Defines a single pipeline stage with execution parameters."""
    name: str
    type: str          # build | test | lint | deploy | security
    command: str
    timeout_secs: int = 300
    on_failure: str = "stop"   # stop | continue | retry
    retry_count: int = 0
    env_vars: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Stage":
        return cls(
            name=d["name"],
            type=d["type"],
            command=d["command"],
            timeout_secs=d.get("timeout_secs", 300),
            on_failure=d.get("on_failure", "stop"),
            retry_count=d.get("retry_count", 0),
            env_vars=d.get("env_vars", {}),
        )

    def validate(self) -> None:
        valid_types = {"build", "test", "lint", "deploy", "security"}
        valid_on_failure = {"stop", "continue", "retry"}
        if self.type not in valid_types:
            raise ValueError(f"Stage type '{self.type}' must be one of {valid_types}")
        if self.on_failure not in valid_on_failure:
            raise ValueError(f"on_failure '{self.on_failure}' must be one of {valid_on_failure}")
        if self.timeout_secs <= 0:
            raise ValueError("timeout_secs must be positive")
        if self.retry_count < 0:
            raise ValueError("retry_count must be >= 0")


@dataclass
class StageResult:
    """Result of a single stage execution."""
    stage_name: str
    status: str         # passed | failed | skipped | running
    started_at: str
    duration_ms: int
    output: str
    exit_code: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StageResult":
        return cls(
            stage_name=d["stage_name"],
            status=d["status"],
            started_at=d["started_at"],
            duration_ms=d["duration_ms"],
            output=d.get("output", ""),
            exit_code=d["exit_code"],
        )

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def failed(self) -> bool:
        return self.status == "failed"


@dataclass
class PipelineRun:
    """Represents a single execution of a pipeline."""
    id: str
    pipeline_id: str
    trigger: str        # manual | push | pr | schedule
    status: str         # idle | running | passed | failed | cancelled
    started_at: str
    finished_at: Optional[str]
    duration_ms: int
    stage_results: list  # list[StageResult]

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "pipeline_id": self.pipeline_id,
            "trigger": self.trigger,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "stage_results": [
                r.to_dict() if isinstance(r, StageResult) else r
                for r in self.stage_results
            ],
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineRun":
        stage_results = [
            StageResult.from_dict(r) if isinstance(r, dict) else r
            for r in d.get("stage_results", [])
        ]
        return cls(
            id=d["id"],
            pipeline_id=d["pipeline_id"],
            trigger=d.get("trigger", "manual"),
            status=d["status"],
            started_at=d["started_at"],
            finished_at=d.get("finished_at"),
            duration_ms=d.get("duration_ms", 0),
            stage_results=stage_results,
        )

    def summary(self) -> dict:
        passed = sum(1 for r in self.stage_results if isinstance(r, StageResult) and r.passed)
        failed = sum(1 for r in self.stage_results if isinstance(r, StageResult) and r.failed)
        return {
            "id": self.id,
            "status": self.status,
            "trigger": self.trigger,
            "duration_ms": self.duration_ms,
            "stages_passed": passed,
            "stages_failed": failed,
        }


@dataclass
class CIPipeline:
    """A CI/CD pipeline definition."""
    id: str
    name: str
    repo_url: str
    branch: str
    stages: list         # list[Stage]
    created_at: str
    updated_at: str
    webhook_secret: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "repo_url": self.repo_url,
            "branch": self.branch,
            "stages": [s.to_dict() if isinstance(s, Stage) else s for s in self.stages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "webhook_secret": self.webhook_secret,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CIPipeline":
        stages = [
            Stage.from_dict(s) if isinstance(s, dict) else s
            for s in d.get("stages", [])
        ]
        return cls(
            id=d["id"],
            name=d["name"],
            repo_url=d["repo_url"],
            branch=d.get("branch", "main"),
            stages=stages,
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            webhook_secret=d.get("webhook_secret", ""),
        )


# ─── SQLite Schema ────────────────────────────────────────────────────────────

DB_PATH = Path.home() / ".blackroad" / "cicd-pipeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pipelines (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    repo_url       TEXT NOT NULL,
    branch         TEXT NOT NULL DEFAULT 'main',
    stages         TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    webhook_secret TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    pipeline_id   TEXT NOT NULL,
    trigger       TEXT NOT NULL DEFAULT 'manual',
    status        TEXT NOT NULL DEFAULT 'idle',
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    stage_results TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
);

CREATE INDEX IF NOT EXISTS idx_runs_pipeline_id ON runs(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_runs_status       ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started_at   ON runs(started_at DESC);
"""

# ─── Pipeline Engine ──────────────────────────────────────────────────────────


class PipelineEngine:
    """
    Core CI/CD pipeline orchestration engine.

    Pipelines are stored in a SQLite database and executed via subprocess.
    Stage execution respects on_failure semantics (stop / continue / retry)
    and tracks timing at millisecond precision.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._active_runs: dict[str, bool] = {}   # run_id -> cancelled?
        self._lock = threading.Lock()
        self._init_db()

    # ── Internal DB helpers ───────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _save_run(self, run: PipelineRun) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                    (id, pipeline_id, trigger, status, started_at,
                     finished_at, duration_ms, stage_results)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.pipeline_id,
                    run.trigger,
                    run.status,
                    run.started_at,
                    run.finished_at,
                    run.duration_ms,
                    json.dumps([
                        r.to_dict() if isinstance(r, StageResult) else r
                        for r in run.stage_results
                    ]),
                ),
            )

    def _load_pipeline(self, pipeline_id: str) -> Optional[CIPipeline]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["stages"] = json.loads(d["stages"])
        return CIPipeline.from_dict(d)

    def _load_run(self, run_id: str) -> Optional[PipelineRun]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["stage_results"] = json.loads(d["stage_results"])
        return PipelineRun.from_dict(d)

    # ── Public API ────────────────────────────────────────────────────────────

    def define_pipeline(
        self,
        name: str,
        repo_url: str,
        branch: str,
        stages: list[dict],
    ) -> CIPipeline:
        """
        Create and persist a new pipeline definition.

        Args:
            name:     Human-readable pipeline name.
            repo_url: Source repository URL.
            branch:   Target branch (e.g. 'main').
            stages:   List of stage dicts matching the Stage schema.

        Returns:
            The persisted CIPipeline instance.
        """
        now = _utcnow()
        stage_objs = [Stage.from_dict(s) for s in stages]
        for s in stage_objs:
            s.validate()

        pipeline = CIPipeline(
            id=str(uuid.uuid4()),
            name=name,
            repo_url=repo_url,
            branch=branch,
            stages=stage_objs,
            created_at=now,
            updated_at=now,
            webhook_secret=uuid.uuid4().hex,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO pipelines
                    (id, name, repo_url, branch, stages,
                     created_at, updated_at, webhook_secret)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pipeline.id,
                    pipeline.name,
                    pipeline.repo_url,
                    pipeline.branch,
                    json.dumps([s.to_dict() for s in pipeline.stages]),
                    pipeline.created_at,
                    pipeline.updated_at,
                    pipeline.webhook_secret,
                ),
            )
        _print_banner(f"Pipeline '{name}' defined", pipeline.id)
        return pipeline

    def run_pipeline(
        self,
        pipeline_id: str,
        trigger: str = "manual",
    ) -> PipelineRun:
        """
        Execute all stages of a pipeline sequentially.

        Stages are executed via subprocess with full environment passthrough.
        Respects on_failure semantics per stage:
          - stop:     Abort remaining stages on first failure.
          - continue: Mark failed but keep running subsequent stages.
          - retry:    Re-attempt up to stage.retry_count times before stopping.

        Returns:
            A completed PipelineRun with per-stage results and timing.
        """
        pipeline = self._load_pipeline(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id!r} not found")

        run = PipelineRun(
            id=str(uuid.uuid4()),
            pipeline_id=pipeline_id,
            trigger=trigger,
            status="running",
            started_at=_utcnow(),
            finished_at=None,
            duration_ms=0,
            stage_results=[],
        )

        with self._lock:
            self._active_runs[run.id] = False

        self._save_run(run)
        run_start_ms = _now_ms()

        _print_pipeline_header(pipeline, run, trigger)

        pipeline_passed = True

        for stage in pipeline.stages:
            # ── Cancellation check ────────────────────────────────────────────
            with self._lock:
                if self._active_runs.get(run.id, False):
                    print(f"\n  {YELLOW}⚠  Run cancelled before stage '{stage.name}'{RESET}")
                    run.status = "cancelled"
                    break

            # ── Execute (with optional retry) ─────────────────────────────────
            result = self._execute_stage(run.id, stage)
            run.stage_results.append(result)
            self._save_run(run)

            if result.status == "failed":
                if stage.on_failure == "stop":
                    pipeline_passed = False
                    break

                elif stage.on_failure == "retry":
                    succeeded = False
                    for attempt in range(stage.retry_count):
                        print(
                            f"  {YELLOW}↺  Retry {attempt + 2}/{stage.retry_count + 1}"
                            f" for '{stage.name}'{RESET}"
                        )
                        retry_result = self._execute_stage(run.id, stage)
                        run.stage_results.append(retry_result)
                        self._save_run(run)
                        if retry_result.status == "passed":
                            succeeded = True
                            break
                    if not succeeded:
                        pipeline_passed = False
                        break

                else:  # on_failure == "continue"
                    pipeline_passed = False
                    # fall through to next stage

        # ── Finalise run ──────────────────────────────────────────────────────
        total_ms = _now_ms() - run_start_ms

        if run.status != "cancelled":
            run.status = "passed" if pipeline_passed else "failed"

        run.finished_at = _utcnow()
        run.duration_ms = total_ms
        self._save_run(run)

        with self._lock:
            self._active_runs.pop(run.id, None)

        _print_run_footer(run, total_ms)
        return run

    def get_status(self, pipeline_id: str) -> dict:
        """Return pipeline definition plus the last 10 runs."""
        pipeline = self._load_pipeline(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id!r} not found")

        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM runs
                WHERE pipeline_id = ?
                ORDER BY started_at DESC
                LIMIT 10
                """,
                (pipeline_id,),
            ).fetchall()

        runs = []
        for row in rows:
            d = dict(row)
            d["stage_results"] = json.loads(d["stage_results"])
            runs.append(PipelineRun.from_dict(d).to_dict())

        return {"pipeline": pipeline.to_dict(), "recent_runs": runs}

    def get_run(self, run_id: str) -> PipelineRun:
        """Return a specific pipeline run by its ID."""
        run = self._load_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id!r} not found")
        return run

    def list_pipelines(self) -> list[CIPipeline]:
        """Return all defined pipelines ordered by creation date (newest first)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pipelines ORDER BY created_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["stages"] = json.loads(d["stages"])
            result.append(CIPipeline.from_dict(d))
        return result

    def cancel_run(self, run_id: str) -> bool:
        """
        Signal an active run to stop after the current stage completes.

        Returns True if the run was found and flagged for cancellation,
        False if the run does not exist or is not running.
        """
        with self._lock:
            if run_id in self._active_runs:
                self._active_runs[run_id] = True
                return True

        # Fallback: mark a persisted-but-stuck "running" run as cancelled
        run = self._load_run(run_id)
        if run and run.status == "running":
            run.status = "cancelled"
            run.finished_at = _utcnow()
            self._save_run(run)
            return True
        return False

    def retry_stage(self, run_id: str, stage_name: str) -> StageResult:
        """
        Re-run a single named stage from an existing run.

        Replaces the previous result for that stage in-place and
        recomputes the overall run status.

        Returns:
            The new StageResult from the retry execution.
        """
        run = self._load_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id!r} not found")

        pipeline = self._load_pipeline(run.pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {run.pipeline_id!r} not found")

        stage = next((s for s in pipeline.stages if s.name == stage_name), None)
        if not stage:
            raise ValueError(
                f"Stage {stage_name!r} not found in pipeline '{pipeline.name}'"
            )

        print(f"\n{BOLD}{YELLOW}↺  Retrying stage '{stage_name}'{RESET}\n")
        result = self._execute_stage(run_id, stage)

        # Replace existing result or append
        existing_idx = next(
            (i for i, r in enumerate(run.stage_results) if r.stage_name == stage_name),
            None,
        )
        if existing_idx is not None:
            run.stage_results[existing_idx] = result
        else:
            run.stage_results.append(result)

        # Recompute overall run status
        all_passed = all(
            r.status == "passed" for r in run.stage_results
            if isinstance(r, StageResult)
        )
        run.status = "passed" if all_passed else "failed"
        self._save_run(run)
        return result

    def delete_pipeline(self, pipeline_id: str) -> bool:
        """
        Delete a pipeline and all of its associated runs.

        Returns True if the pipeline was found and deleted, False otherwise.
        """
        pipeline = self._load_pipeline(pipeline_id)
        if not pipeline:
            return False
        with self._conn() as conn:
            conn.execute("DELETE FROM runs WHERE pipeline_id = ?", (pipeline_id,))
            conn.execute("DELETE FROM pipelines WHERE id = ?", (pipeline_id,))
        print(f"  {RED}🗑   Pipeline '{pipeline.name}' deleted{RESET}")
        return True

    def export_yaml(self, pipeline_id: str) -> str:
        """
        Export a pipeline definition as GitHub Actions-compatible YAML.

        Stages are grouped by type and chained with 'needs' dependencies:
        lint → build → test → security → deploy

        Returns:
            A YAML string suitable for writing to .github/workflows/.
        """
        pipeline = self._load_pipeline(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id!r} not found")

        type_order = ["lint", "build", "test", "security", "deploy"]
        grouped: dict[str, list[Stage]] = {}
        for stage in pipeline.stages:
            grouped.setdefault(stage.type, []).append(stage)

        jobs: dict = {}
        prev_job_id: Optional[str] = None

        # Ordered stage types first
        for stype in type_order:
            stages_of_type = grouped.get(stype, [])
            if not stages_of_type:
                continue
            job_id = stype.replace("-", "_")
            job: dict = {
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/checkout@v4"}],
            }
            if prev_job_id:
                job["needs"] = [prev_job_id]

            for stage in stages_of_type:
                step: dict = {
                    "name": stage.name,
                    "run": stage.command,
                    "timeout-minutes": max(1, stage.timeout_secs // 60),
                }
                if stage.env_vars:
                    step["env"] = stage.env_vars
                if stage.on_failure == "continue":
                    step["continue-on-error"] = True
                job["steps"].append(step)

            jobs[job_id] = job
            prev_job_id = job_id

        # Any remaining stage types not in the canonical order
        for stype, stages_of_type in grouped.items():
            if stype not in type_order:
                job_id = stype.replace("-", "_")
                job = {
                    "runs-on": "ubuntu-latest",
                    "steps": [{"uses": "actions/checkout@v4"}],
                }
                for stage in stages_of_type:
                    step = {
                        "name": stage.name,
                        "run": stage.command,
                        "timeout-minutes": max(1, stage.timeout_secs // 60),
                    }
                    if stage.env_vars:
                        step["env"] = stage.env_vars
                    job["steps"].append(step)
                jobs[job_id] = job

        workflow = {
            "name": pipeline.name,
            "on": {
                "push": {"branches": [pipeline.branch]},
                "pull_request": {"branches": [pipeline.branch]},
            },
            "jobs": jobs,
        }

        return yaml.dump(workflow, default_flow_style=False, sort_keys=False)

    def get_metrics(self, pipeline_id: str) -> dict:
        """
        Compute aggregate metrics for a pipeline across all of its runs.

        Returns a dict containing:
            total_runs, pass_rate, failure_rate, avg_duration_ms,
            most_failing_stage, stage_failure_counts, last_run_status.
        """
        pipeline = self._load_pipeline(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id!r} not found")

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE pipeline_id = ? ORDER BY started_at DESC",
                (pipeline_id,),
            ).fetchall()

        runs = []
        for row in rows:
            d = dict(row)
            d["stage_results"] = json.loads(d["stage_results"])
            runs.append(PipelineRun.from_dict(d))

        if not runs:
            return {
                "pipeline_id": pipeline_id,
                "pipeline_name": pipeline.name,
                "total_runs": 0,
                "pass_rate": 0.0,
                "failure_rate": 0.0,
                "avg_duration_ms": 0,
                "most_failing_stage": None,
                "stage_failure_counts": {},
                "last_run_status": None,
            }

        total = len(runs)
        passed = sum(1 for r in runs if r.status == "passed")
        failed = sum(1 for r in runs if r.status == "failed")
        durations = [r.duration_ms for r in runs if r.duration_ms > 0]
        avg_dur = int(sum(durations) / len(durations)) if durations else 0

        stage_failures: dict[str, int] = {}
        for run in runs:
            for sr in run.stage_results:
                if isinstance(sr, StageResult) and sr.failed:
                    stage_failures[sr.stage_name] = stage_failures.get(sr.stage_name, 0) + 1

        most_failing = (
            max(stage_failures, key=lambda k: stage_failures[k])
            if stage_failures else None
        )

        return {
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline.name,
            "total_runs": total,
            "pass_rate": round(passed / total * 100, 1),
            "failure_rate": round(failed / total * 100, 1),
            "avg_duration_ms": avg_dur,
            "most_failing_stage": most_failing,
            "stage_failure_counts": stage_failures,
            "last_run_status": runs[0].status if runs else None,
        }

    # ── Private execution helpers ─────────────────────────────────────────────

    def _execute_stage(self, run_id: str, stage: Stage) -> StageResult:
        """Execute a single stage command via subprocess and capture output."""
        started_at = _utcnow()
        start_ms = _now_ms()

        print(
            f"  {CYAN}⏳ [{stage.type.upper():8s}]{RESET}  "
            f"{BOLD}{stage.name}{RESET}  "
            f"{DIM}{stage.command[:70]}{RESET}"
        )

        env = os.environ.copy()
        env.update({k: str(v) for k, v in stage.env_vars.items()})

        try:
            proc = subprocess.run(
                stage.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=stage.timeout_secs,
                env=env,
            )
            exit_code = proc.returncode
            output = (proc.stdout + proc.stderr).strip()
            status = "passed" if exit_code == 0 else "failed"

        except subprocess.TimeoutExpired:
            exit_code = -1
            output = f"Stage timed out after {stage.timeout_secs}s"
            status = "failed"

        except Exception as exc:  # noqa: BLE001
            exit_code = -2
            output = f"Unexpected error: {exc}"
            status = "failed"

        duration_ms = _now_ms() - start_ms
        icon = "✅" if status == "passed" else "❌"
        color = GREEN if status == "passed" else RED

        print(
            f"  {icon}  {color}{stage.name}{RESET}  "
            f"{DIM}{duration_ms}ms  exit={exit_code}{RESET}"
        )

        # Print last few lines of output on failure for quick triage
        if output and status == "failed":
            for line in output.splitlines()[-6:]:
                print(f"       {DIM}{line}{RESET}")

        return StageResult(
            stage_name=stage.name,
            status=status,
            started_at=started_at,
            duration_ms=duration_ms,
            output=output,
            exit_code=exit_code,
        )


# ─── Utility functions ────────────────────────────────────────────────────────

def _now_ms() -> int:
    """Current epoch time in milliseconds."""
    return int(time.time() * 1000)


def _utcnow() -> str:
    """Current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _print_banner(title: str, subtitle: str = "") -> None:
    width = 64
    print(f"\n{BOLD}{BLUE}{'─' * width}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    if subtitle:
        print(f"  {DIM}{subtitle}{RESET}")
    print(f"{BOLD}{BLUE}{'─' * width}{RESET}")


def _print_pipeline_header(
    pipeline: CIPipeline, run: PipelineRun, trigger: str
) -> None:
    print(f"\n{BOLD}{CYAN}▶  Pipeline Run{RESET}  {DIM}{run.id}{RESET}")
    print(f"   {DIM}Pipeline : {pipeline.name}{RESET}")
    print(f"   {DIM}Trigger  : {trigger}{RESET}")
    print(f"   {DIM}Branch   : {pipeline.branch}{RESET}")
    print(f"   {DIM}Stages   : {len(pipeline.stages)}{RESET}")
    print()


def _print_run_footer(run: PipelineRun, total_ms: int) -> None:
    icons = {"passed": "✅", "failed": "❌", "cancelled": "🚫"}
    colors = {"passed": GREEN, "failed": RED, "cancelled": YELLOW}
    icon = icons.get(run.status, "❓")
    color = colors.get(run.status, WHITE)
    print(
        f"\n{BOLD}{icon}  Pipeline {color}{run.status.upper()}{RESET}{BOLD}{RESET}"
        f"  {DIM}total={total_ms}ms{RESET}\n"
    )


def _print_table(headers: list[str], rows: list[list]) -> None:
    if not rows:
        print(f"  {DIM}(no data){RESET}\n")
        return
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(f"\n{BOLD}" + fmt.format(*headers) + RESET)
    print("  " + "  ".join("─" * w for w in col_widths))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))
    print()


# ─── Default stage templates ──────────────────────────────────────────────────

DEFAULT_STAGES: list[dict] = [
    {
        "name": "lint",
        "type": "lint",
        "command": "echo '✔ Lint passed'",
        "timeout_secs": 120,
        "on_failure": "stop",
        "retry_count": 0,
        "env_vars": {},
    },
    {
        "name": "build",
        "type": "build",
        "command": "echo '✔ Build passed'",
        "timeout_secs": 300,
        "on_failure": "stop",
        "retry_count": 0,
        "env_vars": {},
    },
    {
        "name": "test",
        "type": "test",
        "command": "echo '✔ Tests passed'",
        "timeout_secs": 600,
        "on_failure": "continue",
        "retry_count": 1,
        "env_vars": {},
    },
    {
        "name": "security-scan",
        "type": "security",
        "command": "echo '✔ Security scan passed'",
        "timeout_secs": 180,
        "on_failure": "continue",
        "retry_count": 0,
        "env_vars": {},
    },
    {
        "name": "deploy",
        "type": "deploy",
        "command": "echo '✔ Deployed'",
        "timeout_secs": 600,
        "on_failure": "stop",
        "retry_count": 2,
        "env_vars": {"DEPLOY_ENV": "production"},
    },
]

# ─── CLI command handlers ─────────────────────────────────────────────────────


def cmd_define(args: argparse.Namespace, engine: PipelineEngine) -> None:
    stages: list[dict] = DEFAULT_STAGES
    if args.stages:
        stages = json.loads(args.stages)
    pipeline = engine.define_pipeline(
        name=args.name,
        repo_url=args.repo,
        branch=args.branch,
        stages=stages,
    )
    _print_table(
        ["Field", "Value"],
        [
            ["ID", pipeline.id],
            ["Name", pipeline.name],
            ["Repo", pipeline.repo_url],
            ["Branch", pipeline.branch],
            ["Stages", str(len(pipeline.stages))],
            ["Webhook Secret", pipeline.webhook_secret[:16] + "…"],
            ["Created", pipeline.created_at[:19]],
        ],
    )


def cmd_run(args: argparse.Namespace, engine: PipelineEngine) -> None:
    run = engine.run_pipeline(args.id, trigger=args.trigger)
    _print_table(
        ["Stage", "Status", "Duration", "Exit"],
        [
            [r.stage_name, r.status, f"{r.duration_ms}ms", str(r.exit_code)]
            for r in run.stage_results
        ],
    )


def cmd_status(args: argparse.Namespace, engine: PipelineEngine) -> None:
    info = engine.get_status(args.id)
    p = info["pipeline"]
    _print_banner(f"Pipeline: {p['name']}", p["id"])
    print(f"  Repo    : {p['repo_url']}")
    print(f"  Branch  : {p['branch']}")
    print(f"  Stages  : {len(p['stages'])}")
    print(f"  Created : {p['created_at'][:19]}")
    if info["recent_runs"]:
        _print_table(
            ["Run ID (short)", "Trigger", "Status", "Duration", "Started"],
            [
                [
                    r["id"][:8] + "…",
                    r["trigger"],
                    r["status"],
                    f"{r['duration_ms']}ms",
                    r["started_at"][:19],
                ]
                for r in info["recent_runs"]
            ],
        )
    else:
        print(f"\n  {DIM}No runs yet.{RESET}\n")


def cmd_list(_args: argparse.Namespace, engine: PipelineEngine) -> None:
    pipelines = engine.list_pipelines()
    if not pipelines:
        print(f"\n  {DIM}No pipelines defined.{RESET}\n")
        return
    _print_table(
        ["ID (short)", "Name", "Repo", "Branch", "Stages", "Updated"],
        [
            [
                p.id[:8] + "…",
                p.name,
                p.repo_url[:35],
                p.branch,
                str(len(p.stages)),
                p.updated_at[:19],
            ]
            for p in pipelines
        ],
    )


def cmd_export(args: argparse.Namespace, engine: PipelineEngine) -> None:
    yaml_str = engine.export_yaml(args.id)
    if args.output:
        Path(args.output).write_text(yaml_str, encoding="utf-8")
        print(f"\n  {GREEN}✅  Exported to {args.output}{RESET}\n")
    else:
        print(yaml_str)


def cmd_metrics(args: argparse.Namespace, engine: PipelineEngine) -> None:
    m = engine.get_metrics(args.id)
    _print_banner(f"Metrics: {m.get('pipeline_name', args.id)}")
    _print_table(
        ["Metric", "Value"],
        [
            ["Total Runs", str(m["total_runs"])],
            ["Pass Rate", f"{m['pass_rate']}%"],
            ["Failure Rate", f"{m['failure_rate']}%"],
            ["Avg Duration", f"{m['avg_duration_ms']}ms"],
            ["Most Failing Stage", str(m["most_failing_stage"] or "—")],
            ["Last Run Status", str(m["last_run_status"] or "—")],
        ],
    )
    if m.get("stage_failure_counts"):
        _print_table(
            ["Stage", "Failure Count"],
            [[k, str(v)] for k, v in m["stage_failure_counts"].items()],
        )


def cmd_cancel(args: argparse.Namespace, engine: PipelineEngine) -> None:
    ok = engine.cancel_run(args.id)
    if ok:
        print(f"\n  {YELLOW}⚠   Run {args.id} cancellation requested.{RESET}\n")
    else:
        print(f"\n  {RED}✗   Could not cancel run {args.id} "
              f"(not found or not running).{RESET}\n")


def cmd_delete(args: argparse.Namespace, engine: PipelineEngine) -> None:
    ok = engine.delete_pipeline(args.id)
    if not ok:
        print(f"\n  {RED}✗   Pipeline {args.id} not found.{RESET}\n")


def cmd_retry_stage(args: argparse.Namespace, engine: PipelineEngine) -> None:
    result = engine.retry_stage(args.run_id, args.stage_name)
    _print_table(
        ["Field", "Value"],
        [
            ["Stage", result.stage_name],
            ["Status", result.status],
            ["Duration", f"{result.duration_ms}ms"],
            ["Exit Code", str(result.exit_code)],
        ],
    )


# ─── Argument parser ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cicd_pipeline",
        description="BlackRoad CI/CD Pipeline Engine — production-grade orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cicd_pipeline.py define --name my-app --repo https://github.com/org/repo
  python cicd_pipeline.py run <pipeline-id>
  python cicd_pipeline.py status <pipeline-id>
  python cicd_pipeline.py export <pipeline-id> -o .github/workflows/generated.yml
  python cicd_pipeline.py metrics <pipeline-id>
  python cicd_pipeline.py list
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # define
    p_def = sub.add_parser("define", help="Define a new pipeline")
    p_def.add_argument("--name", required=True, help="Pipeline name")
    p_def.add_argument("--repo", required=True, help="Repository URL")
    p_def.add_argument("--branch", default="main", help="Target branch [default: main]")
    p_def.add_argument(
        "--stages",
        default=None,
        help="JSON array of stage dicts (uses built-in defaults if omitted)",
    )

    # run
    p_run = sub.add_parser("run", help="Execute a pipeline by ID")
    p_run.add_argument("id", help="Pipeline ID")
    p_run.add_argument(
        "--trigger",
        default="manual",
        choices=["manual", "push", "pr", "schedule"],
    )

    # status
    p_status = sub.add_parser("status", help="Show pipeline status and recent runs")
    p_status.add_argument("id", help="Pipeline ID")

    # list
    sub.add_parser("list", help="List all pipelines")

    # export
    p_exp = sub.add_parser("export", help="Export pipeline as GitHub Actions YAML")
    p_exp.add_argument("id", help="Pipeline ID")
    p_exp.add_argument("--output", "-o", default=None, help="Write YAML to file")

    # metrics
    p_met = sub.add_parser("metrics", help="Show aggregate pipeline metrics")
    p_met.add_argument("id", help="Pipeline ID")

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel an active run")
    p_cancel.add_argument("id", help="Run ID")

    # delete
    p_del = sub.add_parser("delete", help="Delete a pipeline and its runs")
    p_del.add_argument("id", help="Pipeline ID")

    # retry-stage
    p_retry = sub.add_parser("retry-stage", help="Re-run a single failed stage")
    p_retry.add_argument("run_id", help="Run ID")
    p_retry.add_argument("stage_name", help="Name of the stage to retry")

    return parser


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    engine = PipelineEngine()

    dispatch = {
        "define":       cmd_define,
        "run":          cmd_run,
        "status":       cmd_status,
        "list":         cmd_list,
        "export":       cmd_export,
        "metrics":      cmd_metrics,
        "cancel":       cmd_cancel,
        "delete":       cmd_delete,
        "retry-stage":  cmd_retry_stage,
    }

    handler = dispatch.get(args.command)
    if handler:
        try:
            handler(args, engine)
        except ValueError as exc:
            print(f"\n  {RED}Error: {exc}{RESET}\n", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
