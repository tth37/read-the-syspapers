---
title: "HawkSet: Automatic, Application-Agnostic, and Efficient Concurrent PM Bug Detection"
oneline: "HawkSet detects concurrent PM bugs from one binary-traced execution by extending lockset analysis to the lifetime of unpersisted data."
authors:
  - "João Oliveira"
  - "João Gonçalves"
  - "Miguel Matos"
affiliations:
  - "IST Lisbon & INESC-ID"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717477"
code_url: "https://github.com/Jonyleo/HawkSet-exp"
tags:
  - persistent-memory
  - formal-methods
  - fuzzing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HawkSet argues that concurrent PM bugs should be detected by reasoning about the lifetime of values that are visible but not yet durable, rather than by trying to witness one rare bad schedule. It combines binary instrumentation, PM-aware lockset analysis, vector-clock filtering, and an initialization heuristic to recover all PMRace-reported bugs in the paper's overlap set, surface races on the same P-Masstree and P-ART operations as DURINN, and add 7 new bugs, while reaching up to 159x lower time-to-race than PMRace on Fast-Fair.

## Problem

Persistent memory makes a value visible to other threads before that value is guaranteed to survive a crash. That gap is already tricky in single-threaded code, but under concurrency it creates a new failure mode: a thread can observe and act on a value whose producing store has not yet been persisted. After a crash, the consumer-side effect may remain while the producer-side update disappears. The paper calls this a persistency-induced race.

Prior tools do not cover this space well. Generic race detectors ignore PM semantics, so they miss the fact that the critical window extends past the store until the matching persist or overwrite. Concurrent PM tools such as PMRace and DURINN do reason about durability, but they rely on application-specific semantics, guided schedules, or repeated executions that must directly observe a bad interleaving. That makes them hard to generalize beyond key-value-store-style workloads and expensive on large test spaces.

## Key Insight

The central claim is that a concurrent PM bug is defined by the full lifetime of an unpersisted value, not by one observed store/load pair. If a store becomes visible at time `t1` and is only guaranteed durable at time `t2`, then the analysis should ask whether some other thread can load that location anywhere in `[t1, t2)` without sharing a protecting lock discipline.

That reframing makes lockset analysis useful again. HawkSet only tracks PM accesses, which the paper cites as roughly 4% of all memory accesses, so the technique is tractable. The remaining work is to adapt locksets to PM semantics, filter pairs that cannot run concurrently, and suppress the large number of initialization-related false positives that classic lockset analysis would otherwise report.

## Design

HawkSet is implemented as about 2600 lines of C++ on top of Intel PIN and works from binary instrumentation. During execution it records PM loads, stores, flushes, fences, thread creation/join, and synchronization primitives. A memory-simulation component assumes a worst-case cache: data becomes durable only after an explicit flush plus fence. That is deliberately conservative and matches the paper's focus on platforms where programmers cannot assume eADR-like behavior.

The key abstraction is the `effective lockset` of a store. Instead of using the lockset at the store instruction alone, HawkSet intersects the lockset at the store with the lockset at the later persist point, or with the lockset at an overwriting store. It also tags locksets with a thread-local logical timestamp that increments on lock acquisition. This matters because a lock released and reacquired between the store and the persist should not count as one continuous critical section.

To avoid reporting impossible races, HawkSet adds inter-thread happens-before filtering with vector clocks over thread creation, PM accesses, and joins. A store/persist pair is only compared against loads from other threads whose vector clocks are concurrent. HawkSet then applies the Initialization Removal Heuristic: it treats a PM address as unpublished until a second thread accesses it and discards only those pre-publication stores that were already explicitly persisted. That approximation keeps true bugs where a pointer is published before its initialization is durable.

The final analysis is simple: for each store and each concurrent load to the same PM region from another thread, report a persistency-induced race when the store's effective lockset and the load's lockset have empty intersection. The implementation also handles partially overlapping accesses and emits backtraces for both sides of the race.

## Evaluation

The evaluation covers 9 PM applications, including trees, hash tables, learned indexes, Memcached-pmem, and MadFS, on a 128-core Xeon machine with 1 TB of Intel DCPMM. With eight-thread workloads up to 100k operations, HawkSet reports 20 persistency-induced races, 7 of them previously unknown. The paper says it finds every bug previously reported by PMRace on the overlapping applications and reaches races on the same P-Masstree and P-ART operations that DURINN reports, though it does not claim a one-to-one race match there.

The most convincing comparison is against PMRace on Fast-Fair. Using PMRace's 240 provided seeds, HawkSet averages 6.65 seconds per workload while PMRace uses the full 600-second cap. On one known Fast-Fair race, that translates into an expected time-to-race improvement of about 159x. More importantly, HawkSet also reports a new Fast-Fair bug that PMRace misses, because the race only appears on a rare edge-case insertion path and HawkSet does not need to witness the exact interleaving.

The scalability story is credible rather than spectacular. End-to-end testing time grows sublinearly and reaches a little over three minutes on the largest 100k-operation experiments, while peak memory use stays around 4 GB. False positives are the main pain point: the Initialization Removal Heuristic removes all false positives on Fast-Fair, MadFS, P-Masstree, and P-ART and most of them on several other systems, but Memcached-pmem remains noisy because safe PM-region reuse looks like republished initialization.

## Novelty & Impact

HawkSet's novelty is not just using locksets on PM code; it is redefining what the lockset must cover. By lifting the analysis from the instant of the store to the entire visible-but-not-durable interval, then combining that with vector-clock pruning and a publication heuristic, the paper turns a classic concurrency technique into a concurrent PM bug detector.

That is useful for two audiences. PM-system developers get a binary-level tool that is much less tied to one library or one workload model than earlier concurrent PM debuggers. Researchers get a cleaner formulation of this bug class, which should transfer to post-Optane PM designs and likely to future CXL-backed persistent tiers as well.

## Limitations

HawkSet still depends on coverage: if the workload never reaches the relevant PM accesses, the analysis cannot report the race. It also stops at race reporting, not semantic validation, so lock-free designs can generate many benign races that must be triaged manually. The paper is explicit that this shows up in applications such as MadFS and in the large benign-race counts for some lock-free structures.

The initialization heuristic is also imperfect. Memory reuse can make a safely reinitialized region look falsely published, which is why Memcached-pmem still shows many false positives after IRH. The authors avoid instrumenting PM allocators to fix that because allocator interfaces are fragmented and doing so would weaken HawkSet's application-agnostic story. Finally, the tool is not literally zero-setup: PM file paths must be supplied, and custom synchronization primitives or CAS-based control paths may need a small configuration file or wrapper functions.

## Related Work

- _Chen et al. (ASPLOS '22)_ - PMRace uses fuzzing and delay injection to directly observe PM inter-thread inconsistencies in key-value-store-style workloads, whereas HawkSet reports candidate races from one traced execution via PM-aware lockset reasoning.
- _Fu et al. (OSDI '22)_ - DURINN serializes execution into operations and forces adversarial interleavings with breakpoints to test durable-linearizability bugs; HawkSet stays at the PM-access level and does not depend on operation semantics.
- _Savage et al. (TOCS '97)_ - Eraser introduced dynamic lockset race detection for multithreaded programs, and HawkSet can be read as extending that idea with persistence lifetimes, timestamps, and vector-clock pruning.
- _Fu et al. (SOSP '21)_ - Witcher systematically tests crash consistency for NVM key-value stores without concurrency awareness, while HawkSet targets the bug class that appears only when visibility and durability diverge across threads.

## My Notes

<!-- empty; left for the human reader -->
