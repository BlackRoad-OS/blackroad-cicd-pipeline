# BlackRoad CI/CD Pipeline Engine

[![CI](https://github.com/BlackRoad-OS/blackroad-cicd-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/BlackRoad-OS/blackroad-cicd-pipeline/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-red.svg)](https://blackroad.io)
[![Tests](https://img.shields.io/badge/tests-52%20passing-brightgreen.svg)](#testing)
[![Production Ready](https://img.shields.io/badge/production-ready-brightgreen.svg)](https://blackroad.io)
[![npm Compatible](https://img.shields.io/badge/npm-compatible-CB3837.svg?logo=npm)](https://blackroad.io)
[![Stripe Compatible](https://img.shields.io/badge/Stripe-compatible-635BFF.svg?logo=stripe)](https://blackroad.io)

> **BlackRoad CI/CD Pipeline Engine** is a production-grade pipeline orchestration platform with SQLite persistence, subprocess execution, retry logic, GitHub Actions YAML export, and rich terminal output. Purpose-built for teams shipping npm packages, Stripe-integrated services, and cloud-native applications at scale.

---

## Table of Contents

1. [Overview](#overview)
2. [Features](#-features)
3. [Installation](#-installation)
   - [Python (pip)](#python-pip)
   - [npm / Node.js Projects](#npm--nodejs-projects)
4. [Quick Start](#-quick-start)
5. [CLI Reference](#-cli-reference)
   - [define](#define-a-pipeline)
   - [run](#run-a-pipeline)
   - [status](#view-status-and-recent-runs)
   - [list](#list-all-pipelines)
   - [export](#export-as-github-actions-yaml)
   - [metrics](#view-metrics)
   - [retry-stage](#retry-a-single-failed-stage)
   - [cancel](#cancel-an-active-run)
   - [delete](#delete-a-pipeline)
6. [Python API](#-python-api)
7. [Integration Guides](#-integration-guides)
   - [npm Packages](#npm-package-pipeline)
   - [Stripe Webhooks & Payments](#stripe-webhooks--payments)
8. [Architecture](#-architecture)
   - [Class Diagram](#class-diagram)
   - [SQLite Schema](#sqlite-schema)
   - [Exported YAML Example](#example-exported-yaml)
9. [Testing](#-testing)
10. [Security](#-security)
11. [License](#-license)

---

## Overview

BlackRoad CI/CD Pipeline Engine gives engineering teams a **single-file, zero-infrastructure** orchestration layer that runs locally, on bare-metal, or inside any container. It persists all pipeline definitions and run history to a local SQLite database and can export any pipeline as a ready-to-commit GitHub Actions workflow.

**Why BlackRoad?**

- **No SaaS lock-in.** Your pipelines live in your repo and your database.
- **npm-first.** First-class stage templates for `npm install`, `npm test`, `npm publish`, and semantic-release workflows.
- **Stripe-ready.** Pre-built stage configurations for Stripe webhook validation, payment integration smoke-tests, and PCI-scoped security gates.
- **52 passing tests.** Fully validated via pytest with mocked subprocess execution.
- **Single dependency.** Only `pyyaml` is required beyond the Python standard library.

---

## ✨ Features

| Feature | Description |
|---|---|
| **Pipeline Definition** | Define multi-stage pipelines with typed stages (`build`, `test`, `lint`, `deploy`, `security`) |
| **Sequential Execution** | Stages execute via `subprocess` with per-stage timeout, env vars, and exit-code capture |
| **Failure Modes** | Per-stage `on_failure`: `stop` · `continue` · `retry` with configurable `retry_count` |
| **SQLite Persistence** | All pipelines and runs stored in `~/.blackroad/cicd-pipeline.db` (WAL mode, FK constraints) |
| **GitHub Actions Export** | One-command YAML export with `needs` chaining: `lint → build → test → security → deploy` |
| **Metrics** | Pass rate, failure rate, avg duration, most-failing-stage across all historical runs |
| **Rich CLI** | Coloured stage output (✅ ❌ ⏳), tables, banners — zero external dependencies beyond stdlib + PyYAML |
| **Thread-safe Cancellation** | Signal any in-flight run to stop after its current stage completes |
| **Retry Single Stage** | Re-run one failed stage without re-running the whole pipeline |
| **npm Compatible** | Pre-built stage templates for npm install, test, build, and publish workflows |
| **Stripe Compatible** | Stage templates for Stripe webhook validation and payment integration testing |

---

## 📦 Installation

### Python (pip)

```bash
git clone https://github.com/BlackRoad-OS/blackroad-cicd-pipeline.git
cd blackroad-cicd-pipeline
pip install pyyaml          # only external dependency
python cicd_pipeline.py --help
```

No build step required — the engine is a single self-contained Python file.

### npm / Node.js Projects

Add the pipeline engine to any npm-based project by running it alongside your existing toolchain:

```bash
# In your Node.js / npm project root
git clone https://github.com/BlackRoad-OS/blackroad-cicd-pipeline.git .blackroad
pip install pyyaml

# Define a pipeline for your npm package
python .blackroad/cicd_pipeline.py define \
  --name my-npm-package \
  --repo https://github.com/myorg/my-npm-package \
  --branch main \
  --stages '[
    {"name":"install","type":"build","command":"npm ci","timeout_secs":120,"on_failure":"stop","retry_count":1,"env_vars":{"CI":"true"}},
    {"name":"lint","type":"lint","command":"npm run lint","timeout_secs":60,"on_failure":"stop","retry_count":0,"env_vars":{}},
    {"name":"test","type":"test","command":"npm test -- --coverage","timeout_secs":300,"on_failure":"continue","retry_count":1,"env_vars":{"CI":"true","NODE_ENV":"test"}},
    {"name":"build","type":"build","command":"npm run build","timeout_secs":300,"on_failure":"stop","retry_count":0,"env_vars":{"NODE_ENV":"production"}},
    {"name":"publish","type":"deploy","command":"npm publish --access public","timeout_secs":120,"on_failure":"stop","retry_count":0,"env_vars":{"NODE_ENV":"production"}}
  ]'
```

---

## 🚀 Quick Start

```bash
# 1. Install
git clone https://github.com/BlackRoad-OS/blackroad-cicd-pipeline.git
cd blackroad-cicd-pipeline
pip install pyyaml

# 2. Define a pipeline
python cicd_pipeline.py define \
  --name my-app \
  --repo https://github.com/myorg/my-app \
  --branch main

# 3. Run it
python cicd_pipeline.py run <pipeline-id>

# 4. Check status
python cicd_pipeline.py status <pipeline-id>

# 5. Export to GitHub Actions
python cicd_pipeline.py export <pipeline-id> -o .github/workflows/ci.yml
```

---

## 🖥 CLI Reference

### Define a pipeline

```bash
python cicd_pipeline.py define \
  --name my-app \
  --repo https://github.com/myorg/my-app \
  --branch main
```

Provide custom stages as a JSON array:

```bash
python cicd_pipeline.py define \
  --name my-app \
  --repo https://github.com/myorg/my-app \
  --branch main \
  --stages '[
    {"name":"lint","type":"lint","command":"ruff check .","timeout_secs":60,"on_failure":"stop","retry_count":0,"env_vars":{}},
    {"name":"test","type":"test","command":"pytest tests/ -v","timeout_secs":300,"on_failure":"continue","retry_count":1,"env_vars":{"CI":"true"}},
    {"name":"deploy","type":"deploy","command":"./scripts/deploy.sh","timeout_secs":600,"on_failure":"stop","retry_count":2,"env_vars":{"DEPLOY_ENV":"production"}}
  ]'
```

### Run a pipeline

```bash
python cicd_pipeline.py run <pipeline-id>
python cicd_pipeline.py run <pipeline-id> --trigger push
```

**Example output:**

```
▶  Pipeline Run  3f8a1b2c-...
   Pipeline : my-app
   Trigger  : push
   Branch   : main
   Stages   : 3

  ⏳ [LINT    ]  lint  ruff check .
  ✅  lint  142ms  exit=0
  ⏳ [TEST    ]  test  pytest tests/ -v
  ✅  test  4832ms  exit=0
  ⏳ [DEPLOY  ]  deploy  ./scripts/deploy.sh
  ✅  deploy  1021ms  exit=0

✅  Pipeline PASSED  total=6012ms
```

### View status and recent runs

```bash
python cicd_pipeline.py status <pipeline-id>
```

### List all pipelines

```bash
python cicd_pipeline.py list
```

### Export as GitHub Actions YAML

```bash
# Print to stdout
python cicd_pipeline.py export <pipeline-id>

# Write to file
python cicd_pipeline.py export <pipeline-id> -o .github/workflows/generated.yml
```

### View metrics

```bash
python cicd_pipeline.py metrics <pipeline-id>
```

### Retry a single failed stage

```bash
python cicd_pipeline.py retry-stage <run-id> deploy
```

### Cancel an active run

```bash
python cicd_pipeline.py cancel <run-id>
```

### Delete a pipeline

```bash
python cicd_pipeline.py delete <pipeline-id>
```

---

## 🐍 Python API

```python
from cicd_pipeline import PipelineEngine, Stage

engine = PipelineEngine()   # uses ~/.blackroad/cicd-pipeline.db by default

# Define
pipeline = engine.define_pipeline(
    name="backend-api",
    repo_url="https://github.com/BlackRoad-OS/backend-api",
    branch="main",
    stages=[
        {"name": "lint",   "type": "lint",   "command": "ruff check .", "timeout_secs": 60,  "on_failure": "stop",     "retry_count": 0, "env_vars": {}},
        {"name": "test",   "type": "test",   "command": "pytest -q",    "timeout_secs": 300, "on_failure": "continue", "retry_count": 1, "env_vars": {"CI": "true"}},
        {"name": "deploy", "type": "deploy", "command": "./deploy.sh",  "timeout_secs": 600, "on_failure": "stop",     "retry_count": 2, "env_vars": {"ENV": "prod"}},
    ],
)

# Run
run = engine.run_pipeline(pipeline.id, trigger="push")
print(run.status)          # "passed" | "failed" | "cancelled"

# Metrics
metrics = engine.get_metrics(pipeline.id)
print(metrics["pass_rate"])          # e.g. 94.7
print(metrics["most_failing_stage"]) # e.g. "deploy"

# Export YAML
yaml_str = engine.export_yaml(pipeline.id)
open(".github/workflows/ci.yml", "w").write(yaml_str)

# Retry single stage
result = engine.retry_stage(run.id, "deploy")
print(result.status)       # "passed"

# Status
info = engine.get_status(pipeline.id)
print(info["recent_runs"][0]["status"])
```

---

## 🔌 Integration Guides

### npm Package Pipeline

The following pipeline covers the full lifecycle of publishing an npm package: dependency installation, linting, testing, building, and publishing to the npm registry.

```bash
python cicd_pipeline.py define \
  --name my-npm-package \
  --repo https://github.com/myorg/my-npm-package \
  --branch main \
  --stages '[
    {"name":"install","type":"build","command":"npm ci","timeout_secs":120,"on_failure":"stop","retry_count":1,"env_vars":{"CI":"true"}},
    {"name":"lint","type":"lint","command":"npm run lint","timeout_secs":60,"on_failure":"stop","retry_count":0,"env_vars":{}},
    {"name":"test","type":"test","command":"npm test -- --coverage","timeout_secs":300,"on_failure":"continue","retry_count":1,"env_vars":{"CI":"true","NODE_ENV":"test"}},
    {"name":"build","type":"build","command":"npm run build","timeout_secs":300,"on_failure":"stop","retry_count":0,"env_vars":{"NODE_ENV":"production"}},
    {"name":"publish","type":"deploy","command":"npm publish --access public","timeout_secs":120,"on_failure":"stop","retry_count":0,"env_vars":{"NODE_AUTH_TOKEN":"${NPM_TOKEN}","NODE_ENV":"production"}}
  ]'
```

Export the pipeline directly to a GitHub Actions workflow:

```bash
python cicd_pipeline.py export <pipeline-id> -o .github/workflows/npm-publish.yml
```

> **Security note:** Never hard-code `NPM_TOKEN` in stage definitions. Always reference it via `${NPM_TOKEN}` and inject the real value at runtime through your secrets manager or CI/CD environment (e.g. GitHub Actions secrets).

**Python API equivalent:**

```python
from cicd_pipeline import PipelineEngine

engine = PipelineEngine()

pipeline = engine.define_pipeline(
    name="my-npm-package",
    repo_url="https://github.com/myorg/my-npm-package",
    branch="main",
    stages=[
        {"name": "install", "type": "build",  "command": "npm ci",                        "timeout_secs": 120, "on_failure": "stop",     "retry_count": 1, "env_vars": {"CI": "true"}},
        {"name": "lint",    "type": "lint",   "command": "npm run lint",                  "timeout_secs": 60,  "on_failure": "stop",     "retry_count": 0, "env_vars": {}},
        {"name": "test",    "type": "test",   "command": "npm test -- --coverage",        "timeout_secs": 300, "on_failure": "continue", "retry_count": 1, "env_vars": {"CI": "true", "NODE_ENV": "test"}},
        {"name": "build",   "type": "build",  "command": "npm run build",                 "timeout_secs": 300, "on_failure": "stop",     "retry_count": 0, "env_vars": {"NODE_ENV": "production"}},
        {"name": "publish", "type": "deploy", "command": "npm publish --access public",   "timeout_secs": 120, "on_failure": "stop",     "retry_count": 0, "env_vars": {"NODE_AUTH_TOKEN": "${NPM_TOKEN}", "NODE_ENV": "production"}},
    ],
)

run = engine.run_pipeline(pipeline.id, trigger="push")
print(run.status)   # "passed" | "failed"
```

---

### Stripe Webhooks & Payments

The following pipeline validates Stripe webhook endpoints, runs payment integration smoke-tests, and executes a PCI-scoped security scan before any production deployment.

```bash
python cicd_pipeline.py define \
  --name stripe-payment-service \
  --repo https://github.com/myorg/stripe-payment-service \
  --branch main \
  --stages '[
    {"name":"install","type":"build","command":"npm ci","timeout_secs":120,"on_failure":"stop","retry_count":1,"env_vars":{"CI":"true"}},
    {"name":"lint","type":"lint","command":"npm run lint","timeout_secs":60,"on_failure":"stop","retry_count":0,"env_vars":{}},
    {"name":"unit-test","type":"test","command":"npm test","timeout_secs":300,"on_failure":"stop","retry_count":1,"env_vars":{"CI":"true","NODE_ENV":"test","STRIPE_SECRET_KEY":"${STRIPE_TEST_SECRET_KEY}","STRIPE_WEBHOOK_SECRET":"${STRIPE_TEST_WEBHOOK_SECRET}"}},
    {"name":"stripe-webhook-test","type":"test","command":"npm run test:webhooks","timeout_secs":120,"on_failure":"stop","retry_count":1,"env_vars":{"CI":"true","STRIPE_SECRET_KEY":"${STRIPE_TEST_SECRET_KEY}","STRIPE_WEBHOOK_SECRET":"${STRIPE_TEST_WEBHOOK_SECRET}"}},
    {"name":"security-scan","type":"security","command":"npm audit --audit-level=high","timeout_secs":60,"on_failure":"stop","retry_count":0,"env_vars":{}},
    {"name":"deploy","type":"deploy","command":"./scripts/deploy.sh","timeout_secs":600,"on_failure":"stop","retry_count":2,"env_vars":{"NODE_ENV":"production","STRIPE_SECRET_KEY":"${STRIPE_LIVE_SECRET_KEY}","STRIPE_WEBHOOK_SECRET":"${STRIPE_LIVE_WEBHOOK_SECRET}"}}
  ]'
```

> **Security note:** Never hard-code Stripe secret keys in stage definitions. Always reference them via environment variable substitution (e.g. `${STRIPE_TEST_SECRET_KEY}`) and inject real values at runtime through your secrets manager or CI/CD environment.

**Python API equivalent:**

```python
from cicd_pipeline import PipelineEngine

engine = PipelineEngine()

pipeline = engine.define_pipeline(
    name="stripe-payment-service",
    repo_url="https://github.com/myorg/stripe-payment-service",
    branch="main",
    stages=[
        {"name": "install",              "type": "build",    "command": "npm ci",                    "timeout_secs": 120, "on_failure": "stop",     "retry_count": 1, "env_vars": {"CI": "true"}},
        {"name": "lint",                 "type": "lint",     "command": "npm run lint",              "timeout_secs": 60,  "on_failure": "stop",     "retry_count": 0, "env_vars": {}},
        {"name": "unit-test",            "type": "test",     "command": "npm test",                  "timeout_secs": 300, "on_failure": "stop",     "retry_count": 1, "env_vars": {"CI": "true", "NODE_ENV": "test", "STRIPE_SECRET_KEY": "${STRIPE_TEST_SECRET_KEY}", "STRIPE_WEBHOOK_SECRET": "${STRIPE_TEST_WEBHOOK_SECRET}"}},
        {"name": "stripe-webhook-test",  "type": "test",     "command": "npm run test:webhooks",     "timeout_secs": 120, "on_failure": "stop",     "retry_count": 1, "env_vars": {"CI": "true", "STRIPE_SECRET_KEY": "${STRIPE_TEST_SECRET_KEY}", "STRIPE_WEBHOOK_SECRET": "${STRIPE_TEST_WEBHOOK_SECRET}"}},
        {"name": "security-scan",        "type": "security", "command": "npm audit --audit-level=high", "timeout_secs": 60, "on_failure": "stop",  "retry_count": 0, "env_vars": {}},
        {"name": "deploy",               "type": "deploy",   "command": "./scripts/deploy.sh",       "timeout_secs": 600, "on_failure": "stop",     "retry_count": 2, "env_vars": {"NODE_ENV": "production", "STRIPE_SECRET_KEY": "${STRIPE_LIVE_SECRET_KEY}", "STRIPE_WEBHOOK_SECRET": "${STRIPE_LIVE_WEBHOOK_SECRET}"}},
    ],
)

run = engine.run_pipeline(pipeline.id, trigger="push")
print(run.status)   # "passed" | "failed"
```

---

## 🏗 Architecture

### Class diagram

```
CIPipeline
  id: uuid
  name: str
  repo_url: str
  branch: str
  stages: list[Stage]
  webhook_secret: str

Stage
  name: str
  type: lint|build|test|security|deploy
  command: str
  timeout_secs: int
  on_failure: stop|continue|retry
  retry_count: int
  env_vars: dict[str, str]

PipelineRun
  id: uuid
  pipeline_id: uuid → CIPipeline
  trigger: manual|push|pr|schedule
  status: idle|running|passed|failed|cancelled
  started_at: ISO 8601
  finished_at: ISO 8601 | None
  duration_ms: int
  stage_results: list[StageResult]

StageResult
  stage_name: str
  status: passed|failed|skipped
  started_at: ISO 8601
  duration_ms: int
  output: str (last 6 lines on failure)
  exit_code: int
```

### SQLite schema

```sql
-- ~/.blackroad/cicd-pipeline.db

CREATE TABLE pipelines (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    repo_url       TEXT NOT NULL,
    branch         TEXT NOT NULL DEFAULT 'main',
    stages         TEXT NOT NULL DEFAULT '[]',   -- JSON
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    webhook_secret TEXT NOT NULL DEFAULT ''
);

CREATE TABLE runs (
    id            TEXT PRIMARY KEY,
    pipeline_id   TEXT NOT NULL REFERENCES pipelines(id),
    trigger       TEXT NOT NULL DEFAULT 'manual',
    status        TEXT NOT NULL DEFAULT 'idle',
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    stage_results TEXT NOT NULL DEFAULT '[]'     -- JSON
);

CREATE INDEX idx_runs_pipeline_id ON runs(pipeline_id);
CREATE INDEX idx_runs_status       ON runs(status);
CREATE INDEX idx_runs_started_at   ON runs(started_at DESC);
```

### Example exported YAML

```yaml
name: backend-api
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: lint
        run: ruff check .
        timeout-minutes: 1
  test:
    runs-on: ubuntu-latest
    needs: [lint]
    steps:
      - uses: actions/checkout@v4
      - name: test
        run: pytest -q
        timeout-minutes: 5
        continue-on-error: true
        env:
          CI: "true"
  deploy:
    runs-on: ubuntu-latest
    needs: [test]
    steps:
      - uses: actions/checkout@v4
      - name: deploy
        run: ./deploy.sh
        timeout-minutes: 10
        env:
          ENV: prod
```

---

## 🧪 Testing

```bash
pip install pytest pyyaml
pytest tests/ -v --tb=short
```

**52 tests** across 9 test classes:

| Class | Tests |
|---|---|
| `TestStageDataclass` | serialisation round-trip, validation guards |
| `TestStageResultDataclass` | serialisation, `.passed`/`.failed` properties |
| `TestDefinePipeline` | creation, persistence, uniqueness, validation |
| `TestListAndDelete` | ordering, cascade delete, not-found handling |
| `TestRunPipeline` | full pass, stop/continue-on-failure, timing, mock subprocess, env vars |
| `TestStatusTransitions` | status dict, 10-run cap, cancel |
| `TestRetryStage` | result replacement, status recompute, error cases |
| `TestExportYaml` | YAML validity, needs chaining, continue-on-error, branch |
| `TestMetrics` | pass/failure rates, most-failing-stage, avg duration |

---

## 🔐 Security

- Webhook secrets are auto-generated 32-character hex tokens stored per-pipeline.
- The SQLite database is created at `~/.blackroad/` (user-owned, not world-readable).
- Stage commands execute with the **calling user's** environment — never elevate privileges.
- No network calls are made by the engine itself; all external communication is via user-supplied `command` strings.
- **Stripe keys** must always be supplied as environment variables injected at runtime — never embedded in pipeline stage definitions committed to source control.

---

## 📄 License

© BlackRoad OS, Inc. All rights reserved. Proprietary — not open-access.
