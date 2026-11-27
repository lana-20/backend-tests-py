# MongoDB

A contacts API on MongoDB ([`app/api.py`](app/api.py)) and the server-side rules that
protect its data ([`app/collections.py`](app/collections.py)), tested with PyMongo
against MongoDB 8.0 in a container.

```bash
uv run pytest mongodb
```

The container runs as a **single-node replica set**, because a standalone `mongod`
supports neither multi-document transactions nor change streams. The fixture initiates
the set and polls until the node has elected itself primary (an inherent wait). Each
test gets its own database, dropped afterwards, so tests are isolated and parallel-safe.

## What it covers

| Tests | Risk |
|---|---|
| [`test_crud.py`](tests/test_crud.py) | API writes that don't match what's stored: wrong fields, dates stored as strings, updates that touch more than they should |
| [`test_validation_and_indexes.py`](tests/test_validation_and_indexes.py) | Malformed documents getting in ($jsonSchema validator, error code 121); duplicate emails (unique index); queries that silently scan the whole collection |
| [`test_ttl.py`](tests/test_ttl.py) | Expired sessions still accepted, because TTL deletion is late by design |
| [`test_aggregation.py`](tests/test_aggregation.py) | A pipeline returning wrong counts, wrong ordering, or another owner's data |
| [`test_transactions.py`](tests/test_transactions.py) | Half-written data: a contact saved without its first message |
| [`test_change_streams.py`](tests/test_change_streams.py) | Subscribers missing changes, or getting more than the changed field |

**Index usage** is checked with `explain()`: the email lookup must be an index scan
(`EXPRESS_IXSCAN` on MongoDB 8, `FETCH -> IXSCAN` before), the "owner's contacts, newest
first" query must use the compound index *without* a SORT stage, and a query on an
unindexed field must show `COLLSCAN` (the control case that proves the check works).

**TTL, deterministically:** the TTL monitor deletes expired documents about once a
minute, so "expired at exactly 60 minutes" can't be observed directly. The tests
(1) check the index definition, (2) drive the app's own expiry check with an injected
clock, proving an expired session is refused while its document still exists, and
(3) watch one real deletion, with the monitor sped up to every second
(`ttlMonitorSleepSecs=1`), polling with a timeout.

**Cost:** about 25 seconds, most of it container start-up.

## What's different about testing MongoDB

- **No schema unless you add one.** The database accepts any document by default; a
  validator makes the server enforce shape and types, and it deserves its own tests.
- **Indexes are invisible to correctness tests.** A query returns the same documents with
  or without an index, just slower. Only `explain()` shows the difference.
- **Features depend on the deployment.** Transactions and change streams need a replica
  set; a test setup that differs from production can hide or invent failures.
- **Background processes (TTL) are asynchronous.** Tests check the definition and the
  app's handling, not the timing.
- **Change streams are asynchronous** and only see changes made after they open; tests
  open the stream first and read with a timeout.
