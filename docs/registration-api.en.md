# Registration API Service

`chatpypi serve` exposes a registration-only HTTP API for other sites' backends. It has no standalone Web UI, and browsers must never hold the service, PyPI, or GitHub credentials.

## Install and Configure

Serving dependencies stay outside the base CLI installation:

```bash
python -m pip install "ChatPyPI[api]"
chatenv new -t chatpypi-api default
```

`chatpypi-api` is a typed ChatEnv schema:

| Field | Default | Meaning |
| --- | --- | --- |
| `CHATPYPI_API_TOKEN` | none | Sensitive Bearer token for every `/api/*` route; at least 16 characters |
| `CHATPYPI_API_HOST` | `127.0.0.1` | Listen address |
| `CHATPYPI_API_PORT` | `8765` | Listen port |
| `CHATPYPI_API_ALLOWED_HOSTS` | loopback hosts | Trusted HTTP Host values; wildcards are rejected |
| `CHATPYPI_API_ALLOWED_OWNERS` | `ChatArch` | Comma-separated GitHub owner allowlist |
| `CHATPYPI_REGISTRATION_ENABLED` | `false` | Global external registration-write gate |
| `CHATPYPI_API_MAX_BODY_BYTES` | `65536` | JSON body limit |
| `CHATPYPI_API_MAX_QUEUE` | `32` | queued/running job limit |
| `CHATPYPI_API_RATE_LIMIT_PER_MINUTE` | `120` | `/api/*` requests per client address |

A non-loopback listener requires explicit trusted hosts; `*` is invalid. The server also needs the existing active official-PyPI upload token, official-PyPI web-session token profile, and GitHub ChatEnv token. Preflight never logs in, refreshes, or copies those credentials. Upload/readback is fixed to `pypi.org`; request data and `.pypirc` cannot select another repository URL.

```bash
chatpypi paths --format json
chatpypi serve
```

`paths` is a local, operator-only read proving that state belongs under ChatArch home. State/workspace directories use 0700 and SQLite/lock files use 0600; symlink escapes are rejected.

## HTTP Contract

Except for minimal `GET /health`, every route requires:

```http
Authorization: Bearer <service-token>
```

Swagger, ReDoc, the default OpenAPI URL, and CORS are disabled; `/api/*` rejects requests carrying a browser `Origin`. Authenticated `GET /api/schema` returns the OpenAPI JSON.

| Method and path | Behavior |
| --- | --- |
| `GET /health` | Anonymous minimal `{"status":"ok"}` |
| `GET /api/capabilities` | Registration-only stages, fixed defaults, and write-gate state |
| `POST /api/preflight` | Read-only PyPI/GitHub/auth checks for a bounded name list |
| `POST /api/plans` | Create an immutable plan with no external write |
| `POST /api/jobs` | Exactly confirm and asynchronously submit a plan |
| `GET /api/jobs?limit=20&offset=0` | Bounded job listing |
| `GET /api/jobs/{id}` | Job, stage receipts, and fixed safe error |
| `GET /api/schema` | Authenticated OpenAPI JSON |

Unknown request fields are rejected. A caller cannot provide filesystem paths, argv, commands, proxy/provider URLs, env profiles, or credentials.

### Preflight

```json
{
  "names": ["example-package"],
  "owner": "ChatArch"
}
```

Each item includes server-derived `normalized_name` and `module_name`, plus:

- `registry.status`: `available`, `occupied`, or `unknown`;
- `registry.ownership`: `owned` / `not_owned` / `unknown` for an occupied name, or `not_applicable`;
- `repository.status`: `absent`, `exists`, or `unknown`;
- `credentials.pypi_upload`, `pypi_session`, and `github`: `ready`, `needs_auth`, or `unknown`;
- `github_identity`, `can_plan`, and fixed-category `blockers`.

Only a registry 404 means `available`. Network or parsing uncertainty remains `unknown`.

### Immutable Plan

```json
{
  "distribution": "example-package",
  "description": "Example package",
  "owner": "ChatArch",
  "visibility": "private"
}
```

Visibility defaults to `private`; a public repository requires explicit `visibility=public` in the plan. The response freezes:

- distribution/repository, PEP 503 normalized name, and Python module;
- owner, visibility, and description;
- `initial_version=0.0.1`, `requires_python=>=3.10`, and `template=chatarch`;
- `default_branch=main` and `workflow_filename=publish.yml`;
- all stages, plan digest, `ready` / `blockers`, and a server-generated exact `confirmation`.

Plan creation is read-only. An occupied name or unknown provider read cannot produce a plan. Missing authentication may produce a plan with a `needs_auth` blocker, but its job becomes blocked before local or remote mutation.

### Idempotent Submission

```http
POST /api/jobs
Idempotency-Key: <caller-generated-stable-key>
Content-Type: application/json

{
  "plan_id": "<plan-id>",
  "confirmation": "<exact-confirmation-from-plan>"
}
```

The same key and submission returns the original job with `idempotent_replay=true`. Reusing a key for another submission returns `idempotency_conflict`. queued/running/reconciliation jobs exclude another job for the same normalized distribution. With `CHATPYPI_REGISTRATION_ENABLED=false`, submission returns `registration_disabled` while reads, preflight, and planning remain available.

The fixed job read model contains `id`, `plan_id`, `normalized_name`, `status`, `stage`, `receipts`, `created_at`, `updated_at`, and optional `error`. `status` is one of `queued`, `running`, `blocked`, `failed`, `reconciliation_required`, or `registered`; submission responses additionally include `idempotent_replay`.

## Registration-only Workflow

One executor writer runs:

```text
credentials → preflight → scaffold → tests → build_check
→ pypi_upload → pypi_readback → public_install → github_repository → source_push
→ [public_protection] → trusted_publisher → github_readback → registered
```

Key boundaries:

- The job preflights again and performs the initial placeholder upload only while the name is still absent.
- Scaffold/build/check reuse ChatPyPI APIs. Build uses already-installed service dependencies in no-isolation mode; test/build/twine/git commands use a sanitized minimal environment, fixed argv, `shell=False`, noninteractive mode, and bounded time/output.
- Exact PyPI `0.0.1` wheel/sdist readback and a cache-disabled clean installation by name from the official Simple index must pass before repository creation. The installed version and real CLI tree are verified.
- After the initial push, the workflow adds and reads back the active exact GitHub Trusted Publisher. It does not use the pending Publisher path.
- Public plans apply and read back `main` protection immediately after the initial push: PR required, zero required approvals, enforced admins, and force-push/deletion disabled. Unprotected public repositories cannot complete. Private plans do not automatically apply this public policy.
- Final readback verifies planned visibility, the `main` default branch, and the protection policy.
- The terminal state is `registered`; it does not claim a later tag/OIDC feature release happened.

Missing or invalid auth detected before the first external write yields `blocked/needs_auth`. Once a mutation has started, later auth failure, timeout, failed readback/receipt, or process interruption yields `reconciliation_required` and is never automatically replayed. An operator must reconcile provider state first.

`status` represents the job lifecycle. For a non-success terminal state, `stage` preserves the last attempted stage, while `receipts` contain only completed, allowlisted results.

## Server-side Client

Consume the API only from another site's backend:

```python
import os

from chatpypi.client import RegistrationAPIClient

client = RegistrationAPIClient(
    os.environ["CHATPYPI_SERVICE_URL"],
    token=os.environ["CHATPYPI_SERVICE_TOKEN"],
)

preflight = client.preflight(["example-package"], owner="ChatArch")
plan = client.create_plan(
    "example-package",
    owner="ChatArch",
    visibility="private",
    description="Example package",
)
job = client.create_job(
    plan["id"],
    plan["confirmation"],
    idempotency_key="registration-example-package-001",
)
current = client.get_job(job["id"])
```

The client never retries mutations. Keep the service URL/token in private backend configuration, never in static browser assets.

## Explicitly Out of Scope

The first slice does not bump versions, create tags, trigger or claim an OIDC feature release, deploy Pages, modify a consuming site, switch production services, or automatically recover an uncertain external write.
