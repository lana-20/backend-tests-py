# Redis: cache-aside

A read-through cache in front of a slower source of truth
([`app/cache.py`](app/cache.py)), served over HTTP ([`app/api.py`](app/api.py)) with an
`X-Cache: HIT|MISS` header. The source counts its reads, so tests can tell a cache hit
from a miss without timing anything.

```bash
uv run pytest redis_cache
```

## What it covers

| Test | Risk |
|---|---|
| First read misses and fills the cache; second read is a hit | The cache never gets used, or caches the wrong shape |
| Cached keys have a TTL | Keys that live forever, so a missed invalidation means stale data forever |
| An update deletes the cached copy; the next read reloads | Serving stale data after a write |
| Updating an uncached contact creates no key | Writes polluting the cache |
| An expired key is reloaded from the source | Expiry not handled as a miss |
| Unknown ids are 404 and not cached | Caching "nothing" by accident |

Each test uses its own key prefix, so tests share one Redis but never each other's keys.
To test expiry without waiting 300 s, the test shortens one key's TTL to 1 ms with
`PEXPIRE` and polls until Redis reports it gone.

**Cost:** about 10 seconds.

## What's different about testing a cache

The response is the same with or without the cache, so correctness tests alone can't
see it. You need an observable: here, the source's read count and the `X-Cache` header.
Time is part of the behavior (TTLs), so tests control it instead of waiting for it.
And the interesting bugs are about *staleness* after writes, so invalidation gets more
tests than reads.
