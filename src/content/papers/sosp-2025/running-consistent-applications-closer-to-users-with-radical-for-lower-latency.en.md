---
title: "Running Consistent Applications Closer to Users with Radical for Lower Latency"
oneline: "Radical keeps data in a primary datacenter but runs deterministic serverless handlers near users, validating cached reads and securing writes with one overlapped LVI round trip."
authors:
  - "Nicolaas Kaashoek"
  - "Oleg A. Golev"
  - "Austin T. Li"
  - "Amit Levy"
  - "Wyatt Lloyd"
affiliations:
  - "Princeton University"
  - "Sentient Foundation"
  - "Cornell University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764831"
tags:
  - serverless
  - caching
  - transactions
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Radical keeps the authoritative storage system in one primary datacenter but lets deterministic serverless handlers execute near users against eventually consistent caches. Its Lock-Validate-WriteIntent (LVI) protocol compresses validation, locking, and recovery setup into one round trip that overlaps with speculative execution, so successful requests get most of the latency benefit of moving compute outward without giving up linearizability.

## Problem

The paper targets a now-common deployment mismatch. Cloud providers are adding more regional datacenters, edge points of presence, and on-prem clusters, so compute can be placed much closer to users. But a large class of user-facing applications, such as social media, booking services, and forums, still need strong consistency. If they keep storage in one primary datacenter, every near-user execution pays WAN latency on each storage access. If they instead geo-replicate the storage system, each read or write becomes slower because replicas must coordinate across large distances.

The authors argue that this is exactly the regime where existing approaches waste latency. A user request typically performs multiple storage operations, so a centralized deployment multiplies the WAN penalty. A strongly consistent geo-replicated store does not fix that, because the PRAM lower bound still forces read and write latency to reflect the maximum distance between replicas. The result is that applications remain effectively tied to their data even when compute infrastructure has moved outward.

## Key Insight

The paper's key proposition is that a strongly consistent request does not need to block on every remote storage operation if the system can know the request's read/write set before the handler runs. In that case, one pre-execution coordination message can validate the cached state, lock the relevant keys, and prepare recovery for speculative writes, while the application runs locally near the user.

That observation only works if the handler is deterministic and if the runtime can intercept all storage accesses. Radical therefore chooses serverless functions as its unit of execution: they are naturally stateless, make their storage operations explicit, and can be compiled into a deterministic WebAssembly subset. The paper's contribution is not merely speculative execution, but speculative execution that is strong enough to expose a result after a single overlapped control round trip.

## Design

Radical has a near-user runtime and cache at each deployment location, plus one near-storage site colocated with the primary database. When a function `f` is registered, Radical's analyzer derives a companion function `f_rw` that computes the exact keys the invocation will read and write. The analyzer uses symbolic execution and dependency analysis over the serverless handler. If later accesses depend on earlier reads, `f_rw` can execute those prerequisite reads against the local cache; if the cache was stale, validation will fail and the speculative result will be discarded anyway.

At invocation time, the near-user runtime first runs `f_rw`, then starts two activities in parallel. It speculatively executes `f` against the local cache, and it sends an LVI request containing the read/write set and the cache's version numbers to the near-storage location. There, the LVI server acquires per-key read or write locks, sorted lexicographically to avoid deadlock, and validates that the cached versions match the primary store. If any item is stale or missing, the speculative path is abandoned: the near-storage site runs the handler itself, returns the authoritative result, and sends back fresh values so the cache can repair itself.

If validation succeeds, Radical still has to deal with speculative writes without paying another synchronous round trip. Its answer is a write intent. During LVI processing, the near-storage site records an intent for any execution that may write and starts a timer. Once the speculative execution completes and the LVI response says validation succeeded, Radical can return the speculative result to the client immediately. The actual writes are sent afterward as an asynchronous followup, and the locks remain held until those writes are applied.

The recovery path is what makes that safe. If the followup never arrives because the near-user site fails or the message is lost, the timer fires and the near-storage site deterministically re-executes the handler using the same inputs. Because the original LVI request already acquired read locks, the replay sees the same storage state; because functions run in a restricted WebAssembly environment without timers or randomness, the replay produces the same writes. Radical also requires any external service interaction to be made idempotent or otherwise at-most-once safe. This combination of validation, locking, write intents, and deterministic replay is the paper's mechanism for linearizability.

## Evaluation

The prototype is intentionally built on existing infrastructure rather than a custom platform: AWS Lambda for near-user execution, an EC2-based LVI server, DynamoDB as the primary store, and DynamoDB again as the cache so the measurements isolate Radical's protocol rather than a faster cache implementation. The authors port five real applications into 27 Rust-to-WASM serverless functions, and the analyzer succeeds on all 27, with three requiring the paper's dependent-read optimization.

The main experiments focus on a social network, a hotel booking service, and a forum deployed across five AWS regions, with Virginia hosting the primary data. Against a baseline that runs the whole application next to the primary store, Radical cuts median end-to-end latency by 28-35%: hotel booking drops from 270 ms to 194 ms, social media from 234 ms to 154 ms, and the forum from 317 ms to 229 ms. Compared with an idealized inconsistent lower bound that uses only local storage, Radical still attains 84-89% of the maximum possible improvement. Importantly, these wins persist under skewed workloads because the LVI validation step succeeds about 95% of the time.

The function-level results also match the paper's story. Handlers with execution times above the near-user to near-storage RTT benefit the most because the LVI round trip is mostly hidden under execution. Short handlers, including 13-18 ms write-heavy ones, gain less, but they stay within a few milliseconds of running directly near storage rather than suffering catastrophic regressions. The evaluation therefore supports the central claim well, though it is still an AWS prototype and it compares against centralized deployment plus an idealized lower bound rather than a full end-to-end implementation of a real geo-replicated strongly consistent store. Cost is the main tradeoff: the paper estimates roughly a 31% infrastructure increase over the baseline, plus backup executions on the roughly 5% of requests whose validation fails.

## Novelty & Impact

The closest comparison is not another cache or another serverless runtime, but geo-distributed storage systems such as Spanner and speculative systems such as Correctables. Spanner and related databases pay coordination latency inside the storage layer on each operation; Correctables let applications observe progressively stronger results, but the optimistic value still comes from the storage protocol itself. Radical instead moves the key optimization boundary up to the application runtime. It uses static analysis to know what a request will touch, speculative execution to hide distance, and write intents to defer durability without losing correctness.

That gives the paper a clear systems contribution. It is a new mechanism for running linearizable applications closer to users without redesigning the database beneath them, and it is likely to matter to researchers working on edge/cloud execution, stateful serverless platforms, and wide-area transaction processing. Even if later systems replace DynamoDB or Lambda with better components, the paper's main idea is portable: overlap one carefully structured consistency round with deterministic application execution instead of forcing the application to wait on every remote storage action.

## Limitations

Radical is not a universal deployment model. It requires applications to be decomposed into independent serverless functions, and those functions must expose read/write sets that are either statically derivable or cheap to predict. If computing the read/write set is itself expensive, the latency of `f_rw` sits directly on the critical path. If the analyzer cannot derive the set at all, Radical falls back to running the function near storage, eliminating the benefit.

The system also depends on determinism and trust assumptions that are easy to understate. Handlers must avoid ambient nondeterminism such as timers or randomness, external services must provide idempotent or at-most-once interfaces, and developers must trust both the near-user and near-storage sites because both process shared application state. Finally, low-latency functions benefit only modestly. The paper explicitly notes that Radical is most attractive once handler execution is long enough to cover roughly one LVI round trip, and its replicated-server discussion suggests a practical break-even around 20 ms.

## Related Work

- _Corbett et al. (OSDI '12)_ - Spanner provides globally consistent storage by coordinating across replicas on each request, whereas Radical keeps one primary store and overlaps a single coordination round with speculative execution.
- _Lloyd et al. (SOSP '11)_ - COPS offers low-latency geo-replication with causal consistency, while Radical targets linearizability for applications that cannot weaken consistency that far.
- _Jia and Witchel (SOSP '21)_ - Boki improves stateful serverless storage inside a datacenter; Radical instead uses serverless handlers as the analyzable execution unit for wide-area low-latency consistency.
- _Guerraoui et al. (OSDI '16)_ - Correctables expose progressively stronger results for speculative application logic, whereas Radical makes one pre-execution LVI request sufficient to validate and commit a speculative execution.

## My Notes

<!-- empty; left for the human reader -->
