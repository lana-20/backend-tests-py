# backend-tests-py

[![CI](https://github.com/lana-20/backend-tests-py/actions/workflows/ci.yml/badge.svg)](https://github.com/lana-20/backend-tests-py/actions/workflows/ci.yml)
[Test report (Allure)](https://lana-20.github.io/backend-tests-py/allure/) ·
[Reports site](https://lana-20.github.io/backend-tests-py/)

Backend tests in Python 3.12 and pytest, each against a **real, disposable dependency**:
databases, emulators and a Linux box start in containers (testcontainers) for the test
run and are thrown away after it. No mocks of the systems under test, and no shared
test environments.

## What's covered

| Section | What's tested | Tool | Risk it covers | Cost (CI) | Tests |
|---|---|---|---|---|---|
| [GraphQL](graphql_api) | Queries, mutations, variables over HTTP; per-field auth; errors next to partial data; cursor pagination; depth/alias/size limits; N+1 query count; schema snapshot + breaking-change gate | Strawberry, FastAPI, uvicorn, Requests, graphql-core | Data leaking to the wrong user, abusive queries, slow resolvers, breaking clients | ~8 s, no Docker | 42 + gate |
| [PostgreSQL](sql_engines) | Migrations, constraints, locking, isolation, queries vs plain SQL, rows after an API call | SQLAlchemy 2, Alembic, psycopg 3 | Bad data getting in, lost updates, schema drift | ~10 s | 30 (+4 skipped) |
| [MySQL](sql_engines) | Same suite | PyMySQL | Same, plus case-insensitive collation and driver error classes | ~20 s | 30 (+4 skipped) |
| [SQL Server](sql_engines) | Same suite, plus snapshot isolation and NVARCHAR | pymssql, Developer edition image | Same, plus readers blocking on writers and a silently dropped FOR UPDATE | ~20 s | 32 (+2 skipped) |
| [SQLite](sql_engines) | Same suite, plus database-wide locking and the foreign-keys pragma | sqlite3 | Same, plus "it passed on SQLite" false confidence | ~2 s, no Docker | 31 (+3 skipped) |
| [MongoDB](mongodb) | CRUD via API, $jsonSchema validator, index use via `explain()`, TTL, aggregation, transaction, change streams | PyMongo, single-node replica set | Malformed documents, collection scans, half-written data, missed events | ~25 s | 21 |
| [DynamoDB Local](document_stores#dynamodb-local) | Conditional writes, optimistic locking, query vs scan, GSI, pagination, TTL | boto3 | Overwrites, full-table scans, missed pages, serving expired items | ~20 s | 9 |
| [Firestore emulator](document_stores#firestore-emulator) | CRUD, composite query, transaction, security rules as end users | google-cloud-firestore, emulator REST API | Wrong users reading data, drifting counters | ~20 s | 10 |
| [Redis](redis_cache) | Cache-aside hits and misses, TTLs, invalidation on update | redis-py | Stale data after writes, keys that never expire | ~10 s | 7 |
| [SSH / Linux](linux_ssh) | Process, port, health, permissions, logs by request id, headroom, supervised restart, cron, logrotate, SSH hardening | Paramiko; Debian with sshd and supervisord | A "deployed" box that isn't actually healthy or locked down | ~40 s | 22 |
| [Bash / Bats](linux_ssh) | The deploy healthcheck script: retries, give-up, usage errors | Bats with a stubbed `curl` | A pipeline that waits forever, or calls a dead service healthy | < 1 s, no Docker | 6 |

Cost is the test run in CI, including container start-up. The SQL skips are
engine-specific tests (for example SQL Server snapshot isolation) on the other engines,
each with its reason.

**SQL: engine x what's tested**

| | PostgreSQL | MySQL | SQL Server | SQLite |
|---|:-:|:-:|:-:|:-:|
| Alembic up/down/up; models match the migrated schema | ✓ | ✓ | ✓ | ✓ (batch mode) |
| NOT NULL, UNIQUE, FK, CHECK | ✓ | ✓ | ✓ | ✓ |
| Rollback, lost update, optimistic locking | ✓ | ✓ | ✓ | ✓ |
| Row lock (FOR UPDATE / UPDLOCK) | ✓ | ✓ | ✓ | database lock instead |
| Query correctness vs plain SQL; rows after an API call | ✓ | ✓ | ✓ | ✓ |
| Isolation defaults, collation, NVARCHAR, TOP/LIMIT, identity, upsert syntax | ✓ | ✓ | ✓ | ✓ |
| Snapshot isolation | | | ✓ | |

Each engine difference is listed in the [SQL README](sql_engines#engine-differences-written-down-as-tests).

## Running it

Needs [uv](https://docs.astral.sh/uv/). Docker is needed for everything except GraphQL,
SQLite and Bats.

```bash
uv sync                                   # Python 3.12 and every pinned dependency

uv run pytest graphql_api                 # GraphQL
uv run pytest sql_engines -m postgres     # or -m mysql, -m mssql, -m sqlite
uv run pytest sql_engines                 # all four engines
uv run pytest mongodb
uv run pytest document_stores/dynamodb
uv run pytest document_stores/firestore
uv run pytest redis_cache
uv run pytest linux_ssh
bats linux_ssh/bats                       # brew install bats-core

uv run ruff check . && uv run ruff format --check . && uv run mypy .
```

pytest writes Allure results to `allure-results/`; to view them:
`npx allure@3.33.0 generate allure-results --output allure-report`.

## How it's built

- **Real dependencies, started per run.** testcontainers starts each container on a
  random port and removes it afterwards. Images are pinned to exact tags.
- **Isolation per test.** A rolled-back transaction (SQL), or a new database (MongoDB),
  table (DynamoDB), project id (Firestore) or key prefix (Redis) per test. Tests don't
  depend on order and don't share data.
- **No sleeps to synchronize.** Where waiting is inherent (a container starting, a
  supervisor restarting a process, a change event arriving), the test polls for a
  condition with a timeout, through one helper: [`common/polling.py`](common/polling.py).
  Concurrency tests are deterministic: two connections take turns in one thread, and
  NOWAIT turns "would block" into an immediate error.
- **Secrets are generated, not committed.** Database passwords and SSH keys are created
  per run, in memory.
- **Everything pinned.** Exact versions in `pyproject.toml` and `uv.lock`. Dependabot
  updates Python packages, GitHub Actions and the SSH box's base image; container tags
  referenced from Python code are pinned there and bumped by hand.
- **CI** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)): lint and type check,
  one job per section, one job per SQL engine, the GraphQL breaking-change gate, and
  Bats. Every job uploads Allure results; a final job merges them into one report,
  labeled by section (and by engine for SQL), and publishes it to GitHub Pages.

## Related

- [api-contract-tests-ts](https://github.com/lana-20/api-contract-tests-ts): contract
  testing for a REST and GraphQL API in TypeScript (OpenAPI, Pact, oasdiff, Apollo Server).
- [api-contract-tests-py](https://github.com/lana-20/api-contract-tests-py): API contract
  testing in Python (Requests and pytest over real HTTP, OpenAPI and Pydantic contracts,
  Schemathesis).

Author: [Lana Begunova](https://github.com/lana-20) · [MIT License](LICENSE)
