// Generic per-sweep memoization for conformance helpers.
//
// A single conformance sweep typically calls the same expensive
// helper (AgentCard fetch, capability lookup, etc.) from multiple
// contracts. Each helper that wants to share its result across
// contracts within one sweep declares a SweepCache; the runner
// clears every registered cache at the start of each sweep so
// state never leaks between runs.
//
// Usage:
//
//   const cardCache = createSweepCache<string, CardFetchResult>();
//
//   export async function fetchCard(url: string) {
//     return cardCache.getOrFetch(url, async () => {
//       const res = await fetch(...);
//       ...
//     });
//   }
//
// `clearAllSweepCaches()` (called by the runner) drops every entry
// in every registered cache without needing the caller to know
// which caches exist.

interface SweepCacheRegistry {
  clear: () => void;
}

const _registered = new Set<SweepCacheRegistry>();

export interface SweepCache<K, V> {
  /** Return the cached value for `key`, or call `fetcher` and cache
   *  its (in-flight) promise so concurrent callers share one fetch. */
  getOrFetch: (key: K, fetcher: () => Promise<V>) => Promise<V>;
  /** Drop everything. Normally called via `clearAllSweepCaches()`
   *  from the runner; exposed for tests that want surgical control. */
  clear: () => void;
}

export function createSweepCache<K, V>(): SweepCache<K, V> {
  const map = new Map<K, Promise<V>>();
  const cache: SweepCache<K, V> = {
    getOrFetch(key, fetcher) {
      const cached = map.get(key);
      if (cached) return cached;
      const promise = fetcher();
      map.set(key, promise);
      return promise;
    },
    clear() {
      map.clear();
    },
  };
  _registered.add(cache as SweepCacheRegistry);
  return cache;
}

export function clearAllSweepCaches(): void {
  for (const cache of _registered) cache.clear();
}
