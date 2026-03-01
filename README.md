# BlackRoad CI/CD Pipeline Engine

[![CI](https://github.com/BlackRoad-OS/blackroad-cicd-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/BlackRoad-OS/blackroad-cicd-pipeline/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-red.svg)](https://blackroad.io)
[![Tests](https://img.shields.io/badge/tests-52%20passing-brightgreen.svg)](#-testing)
[![npm](https://img.shields.io/badge/npm-blackroad--cicd--pipeline-CB3837?logo=npm)](https://www.npmjs.com/package/blackroad-cicd-pipeline)
[![Stripe](https://img.shields.io/badge/Stripe-integrated-635BFF?logo=stripe&logoColor=white)](#-stripe-billing-integration)

> **Production-grade CI/CD pipeline orchestration** — SQLite persistence, subprocess execution, retry logic, GitHub Actions YAML export, rich terminal output, Stripe billing hooks, and an npm-publishable JavaScript SDK.

---

## 📑 Table of Contents

1. [Features](#-features)
2. [Installation](#-installation)
   - [Python (pip)](#python-pip)
   - [JavaScript / npm](#javascript--npm)
3. [CLI Usage](#-cli-usage)
   - [Define a pipeline](#define-a-pipeline)
   - [Run a pipeline](#run-a-pipeline)
   - [View status and recent runs](#view-status-and-recent-runs)
   - [List all pipelines](#list-all-pipelines)
   - [Export as GitHub Actions YAML](#export-as-github-actions-yaml)
   - [View metrics](#view-metrics)
   - [Retry a single failed stage](#retry-a-single-failed-stage)
   - [Cancel an active run](#cancel-an-active-run)
   - [Delete a pipeline](#delete-a-pipeline)
4. [Python API](#-python-api)
5. [JavaScript / npm SDK](#-javascript--npm-sdk)
6. [Stripe Billing Integration](#-stripe-billing-integration)
7. [Architecture](#-architecture)
   - [Class diagram](#class-diagram)
   - [SQLite schema](#sqlite-schema)
   - [Example exported YAML](#example-exported-yaml)
8. [Testing](#-testing)
   - [Unit tests](#unit-tests)
   - [End-to-end (E2E) tests](#end-to-end-e2e-tests)
9. [Security](#-security)
10. [License](#-license)

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
| **npm SDK** | JavaScript/TypeScript wrapper for browser and Node.js integrations |
| **Stripe Billing** | Metered usage webhooks to Stripe for per-run and per-seat billing |

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

### JavaScript / npm

```bash
npm install blackroad-cicd-pipeline
# or
yarn add blackroad-cicd-pipeline
```

```js
import { PipelineClient } from 'blackroad-cicd-pipeline';

const client = new PipelineClient({ apiUrl: 'https://api.blackroad.io' });
const pipeline = await client.define({ name: 'my-app', repo: 'https://github.com/org/repo', branch: 'main' });
const run = await client.run(pipeline.id, { trigger: 'push' });
console.log(run.status); // "passed" | "failed" | "cancelled"
```

> **Publishing to npm:** see the [npm publish workflow](#npm-publish-workflow) section below for publishing steps.

---

## 🚀 CLI Usage

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

## 🟨 JavaScript / npm SDK

The `blackroad-cicd-pipeline` npm package ships a thin HTTP client and TypeScript types for integrating pipeline runs into web dashboards, CLI tools, and CI bots.

```bash
npm install blackroad-cicd-pipeline
```

### Quick start

```ts
import { PipelineClient, PipelineRunStatus } from 'blackroad-cicd-pipeline';

const client = new PipelineClient({
  apiUrl: process.env.BLACKROAD_API_URL!,
  apiKey: process.env.BLACKROAD_API_KEY!,
});

// Define a pipeline
const pipeline = await client.pipelines.define({
  name: 'frontend-deploy',
  repoUrl: 'https://github.com/myorg/frontend',
  branch: 'main',
  stages: [
    { name: 'lint',   type: 'lint',   command: 'npm run lint',   timeoutSecs: 60,  onFailure: 'stop' },
    { name: 'test',   type: 'test',   command: 'npm test',       timeoutSecs: 300, onFailure: 'continue' },
    { name: 'deploy', type: 'deploy', command: 'npm run deploy', timeoutSecs: 600, onFailure: 'stop' },
  ],
});

// Trigger a run
const run = await client.runs.trigger(pipeline.id, { trigger: 'push' });

// Poll until complete
let result = await client.runs.get(run.id);
while (result.status === PipelineRunStatus.Running) {
  await new Promise(r => setTimeout(r, 2000));
  result = await client.runs.get(run.id);
}

console.log('Final status:', result.status);
```

### npm publish workflow

```bash
# Bump version
npm version patch   # or minor / major

# Dry-run to verify package contents
npm pack --dry-run

# Publish to npm registry
npm publish --access public
```

Set `NPM_TOKEN` as a repository secret and the included `.github/workflows/npm-publish.yml` will publish automatically on each tagged release.

---

## 💳 Stripe Billing Integration

BlackRoad CI/CD Pipeline supports **Stripe metered billing** so teams are charged only for what they run.

### Billing model

| Metric | Stripe meter event | Unit |
|---|---|---|
| Pipeline runs | `pipeline_run` | 1 per run |
| Stage executions | `stage_execution` | 1 per stage |
| Per-seat access | `seat` | monthly subscription |

### Setup

1. Create a [Stripe metered price](https://stripe.com/docs/billing/subscriptions/usage-based) in your Stripe dashboard.
2. Set the following environment variables:

```bash
export STRIPE_SECRET_KEY=sk_live_...
export STRIPE_WEBHOOK_SECRET=whsec_...
export STRIPE_METER_EVENT_NAME=pipeline_run
```

3. Register the webhook endpoint (`POST /stripe/webhook`) to receive `customer.subscription.updated` and `invoice.payment_failed` events.

### Webhook handler (Python example)

```python
import stripe
import os

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

def handle_stripe_webhook(payload: bytes, sig_header: str) -> None:
    event = stripe.Webhook.construct_event(
        payload, sig_header, os.environ["STRIPE_WEBHOOK_SECRET"]
    )
    if event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        # update team quota in your database
        update_team_quota(subscription["customer"], subscription["status"])
    elif event["type"] == "invoice.payment_failed":
        # pause pipeline execution for the customer
        suspend_customer_pipelines(event["data"]["object"]["customer"])

def report_pipeline_run(customer_id: str) -> None:
    """Report a metered usage event to Stripe after each run."""
    stripe.billing.MeterEvent.create(
        event_name=os.environ["STRIPE_METER_EVENT_NAME"],
        payload={"stripe_customer_id": customer_id, "value": "1"},
    )
```

### Webhook handler (JavaScript / npm example)

```ts
import Stripe from 'stripe';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

export async function handleStripeWebhook(req: Request): Promise<void> {
  const sig = req.headers.get('stripe-signature')!;
  const body = await req.text();
  const event = stripe.webhooks.constructEvent(body, sig, process.env.STRIPE_WEBHOOK_SECRET!);

  switch (event.type) {
    case 'customer.subscription.updated':
      await updateTeamQuota(event.data.object.customer as string, event.data.object.status);
      break;
    case 'invoice.payment_failed':
      await suspendCustomerPipelines((event.data.object as Stripe.Invoice).customer as string);
      break;
  }
}

export async function reportPipelineRun(stripeCustomerId: string): Promise<void> {
  await stripe.billing.meterEvents.create({
    event_name: process.env.STRIPE_METER_EVENT_NAME!,
    payload: { stripe_customer_id: stripeCustomerId, value: '1' },
  });
}
```

> **Security:** always verify the `stripe-signature` header before processing webhook payloads. Never log raw webhook bodies in production.

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

### Unit tests

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

### End-to-end (E2E) tests

E2E tests exercise the full pipeline lifecycle — from `define` through `run`, `status`, `metrics`, `export`, and `retry` — against a real (temporary) SQLite database with real `subprocess` calls.

```bash
# Run only E2E tests
pytest tests/ -v -k "e2e" --tb=short

# Run the full suite including E2E
pytest tests/ -v --tb=short
```

**E2E test checklist:**

| Scenario | Validates |
|---|---|
| Define → run → pass | All stages execute; `status == "passed"`; DB persisted |
| Define → run → fail (stop) | Pipeline halts at failing stage; subsequent stages skipped |
| Define → run → fail (continue) | All stages attempted; `status == "failed"` |
| Retry failed stage | Stage re-runs; run status recomputed to `"passed"` |
| Export YAML | Valid GitHub Actions YAML with correct `needs` chaining |
| Metrics after N runs | Correct pass/fail rates; `most_failing_stage` identified |
| Cancel in-flight run | `status` transitions to `"cancelled"` |
| Delete with cascade | All associated runs removed from DB |
| Stripe billing event | `report_pipeline_run()` posts a metered event (mocked Stripe SDK) — _planned_ |
| npm SDK `trigger()` | HTTP client sends correct payload; maps response to `PipelineRun` — _planned_ |

> **CI:** all unit and E2E tests run automatically on every push and pull request via the [GitHub Actions workflow](.github/workflows/ci.yml).

---

## 🔐 Security

- Webhook secrets are auto-generated 32-character hex tokens stored per-pipeline.
- The SQLite database is created at `~/.blackroad/` (user-owned, not world-readable).
- Stage commands execute with the **calling user's** environment — never elevate privileges.
- No network calls are made by the engine itself; all external communication is via user-supplied `command` strings.
- Stripe webhook payloads are always verified with `stripe.Webhook.construct_event` before processing.
- API keys and Stripe secrets are read exclusively from environment variables — never hard-coded.

---

## 📄 License

© BlackRoad OS, Inc. All rights reserved. Proprietary — not open source.
