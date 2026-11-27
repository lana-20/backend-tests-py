# Other document stores: DynamoDB Local and the Firestore emulator

Both are cloud-only databases with official local stand-ins. Each runs in a container,
and each test gets its own table (DynamoDB) or project id (Firestore), so tests never
share data.

```bash
uv run pytest document_stores/dynamodb
uv run pytest document_stores/firestore
```

## DynamoDB Local

[`dynamodb/contacts_table.py`](dynamodb/contacts_table.py): a table keyed by
`owner` (partition) and `contact_id` (sort), a global secondary index on `email`, and a
TTL attribute. boto3 talks to `amazon/dynamodb-local` through `endpoint_url`, with
placeholder credentials.

| Test | Risk |
|---|---|
| Conditional put | A plain `put_item` silently overwrites an existing item |
| Optimistic locking (`version` attribute, `ConditionExpression`) | Two clients overwrite each other's changes |
| Query vs Scan | Same answer, but Scan reads (and bills for) the whole table: `ScannedCount` 15 vs 5 |
| GSI lookup, and `ConsistentRead` on a GSI rejected | Assuming an index read sees a write that just happened |
| Pagination with `LastEvaluatedKey` | Stopping after the first page; and the gotcha that a page filled exactly can be followed by an empty one |
| TTL enabled, expired items filtered on read | Serving expired items: DynamoDB Local never deletes them, and real DynamoDB can take days |

**Cost:** about 20 seconds.

**What's different about testing DynamoDB:** you design for access patterns, so tests
check that each pattern is a Query, not a Scan. There are no joins or constraints
besides the key and conditions, so integrity rules live in condition expressions and
need their own tests. Results are paginated by size, not just by count. DynamoDB Local
is kinder than production in ways that matter: no TTL deletion, immediately consistent
indexes, no throttling and no capacity limits.

## Firestore emulator

[`firestore/contacts.py`](firestore/contacts.py) and
[`firestore/firestore.rules`](firestore/firestore.rules), tested against the emulator
from the Google Cloud CLI image, with `google-cloud-firestore` pointed at it through
`FIRESTORE_EMULATOR_HOST` and a `demo-` project id (one that can't exist in Google Cloud).

| Test | Risk |
|---|---|
| Create, read, update, delete; `create()` refuses to overwrite | Lost or overwritten documents |
| Composite query (equality + `array_contains` + order by) | Wrong results or order |
| Transaction: message + counter together; a failure inside leaves nothing | Counters that drift from the data they count |
| Security rules: owner reads, other users and signed-out users get 403, no creating documents for someone else | Data readable or writable by the wrong user |

**Security rules from Python:** the Python SDK is an admin client and bypasses rules,
in production and in the emulator. So the rules tests use the emulator's REST API with
unsigned ID tokens (which only an emulator accepts), the same approach as Firebase's
`@firebase/rules-unit-testing`. Rules are loaded per project through the emulator's
`securityRules` endpoint ([`firestore/rest_client.py`](firestore/rest_client.py)).

**Cost:** about 20 seconds; the emulator image is large (over 1 GB) to pull.

**What's different about testing Firestore:** server SDKs skip security rules, so rules
need tests that act as end users. The emulator doesn't require composite indexes, while
production rejects the same query until the index exists; the index the query needs is
kept in [`firestore/firestore.indexes.json`](firestore/firestore.indexes.json), next to
the code, but nothing here deploys or verifies it. Transactions retry automatically on
contention, so transaction code must be safe to run more than once.
