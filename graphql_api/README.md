# GraphQL (Strawberry on FastAPI)

A small contacts-and-messages GraphQL API ([`app/`](app)), tested over real HTTP: each
test starts the app with uvicorn on a free port and sends `POST /graphql` with
`requests`. Storage is in-memory SQLite, so this section needs no containers.

```bash
uv run pytest graphql_api
```

## What it covers

| Tests | Risk |
|---|---|
| [`test_queries_and_mutations.py`](tests/test_queries_and_mutations.py) | Wrong data, mutations that don't write (each one checks the database row), variables of the wrong type |
| [`test_auth.py`](tests/test_auth.py) | Operations open to anonymous callers; a field (`Contact.email`) leaking to non-owners |
| [`test_error_shape.py`](tests/test_error_shape.py) | Clients that read the status code and miss errors; partial data handled wrongly; leaked internals |
| [`test_pagination.py`](tests/test_pagination.py) | Pages that skip or repeat rows; unbounded page sizes |
| [`test_limits.py`](tests/test_limits.py) | Denial of service via deep nesting, alias amplification or huge documents. Each test also proves the database was never queried |
| [`test_n_plus_one.py`](tests/test_n_plus_one.py) | The N+1 query problem. Counts SQL statements per request with a SQLAlchemy event listener: 2 queries with the DataLoader, 1 + N without it |
| [`test_schema_contract.py`](tests/test_schema_contract.py) | The schema drifting from the committed SDL ([`schema.graphql`](schema.graphql)) without review |
| [`test_breaking_changes.py`](tests/test_breaking_changes.py) | A breaking-change gate that can't fail: removed fields, changed types and new required arguments must all be reported |

**Breaking-change gate in CI:** the `GraphQL breaking-change gate` job first runs the
self-test above, then compares `schema.graphql` with the base branch's copy using
graphql-core's `find_breaking_changes` ([`breaking_changes.py`](breaking_changes.py)).
Additive changes pass; a removed field or a new required argument fails the build.

**Cost:** about 8 seconds for the whole section; no Docker.

## How testing GraphQL differs from REST

- **One endpoint, one method.** Every request is `POST /graphql`. Routing tests become
  tests of operations and fields.
- **Almost always 200.** Errors live in the body's `errors` array, so a test that only
  checks the status code passes on failures. Every test here checks the body.
- **Partial success is normal.** One response can hold `data` *and* `errors`: bob asking
  for a contact's `name` and `email` gets the name, `email: null`, and an error whose
  `path` is `["contact", "email"]`. A null in a non-null field propagates to the nearest
  nullable parent, which can be `data` itself.
- **Errors are typed by convention, not by status.** Clients branch on
  `extensions.code` (`UNAUTHENTICATED`, `FORBIDDEN`, `BAD_USER_INPUT`), so the tests pin
  those codes.
- **Authorization is per field, not per route.** One query touches many resolvers, and
  each needs its own rule.
- **The client chooses the cost of a request.** Depth, alias and size limits, plus a cap on
  page size, are part of the API's contract, and they're tested like features.
- **The schema is the contract.** It's introspectable and diffable, so breaking changes are
  caught mechanically, before code review, the way OpenAPI diffs work for REST.
- **N+1 is a resolver-design bug** that only shows up with nested lists, so it gets a
  dedicated check that counts queries.

A note on Strawberry: for requests that never execute (syntax errors, unknown fields,
bad variables), the GraphQL spec says to omit `data`; Strawberry sends `"data": null`.
The tests check `data is None`, which accepts both.

The same domain, with a TypeScript Apollo Server GraphQL layer, lives in
[api-contract-tests-ts/graphql](https://github.com/lana-20/api-contract-tests-ts/tree/main/graphql).
