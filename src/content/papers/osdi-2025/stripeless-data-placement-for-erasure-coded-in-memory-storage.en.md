---
title: "Stripeless Data Placement for Erasure-Coded In-Memory Storage"
oneline: "Nos removes stripes by choosing backups from an SBIBD matrix and XOR-encoding replicas in the background, cutting write-path overhead without losing multi-failure recovery."
authors:
  - "Jian Gao"
  - "Jiwu Shu"
  - "Bin Yan"
  - "Yuhao Zhang"
  - "Keji Huang"
affiliations:
  - "Tsinghua University"
  - "Huawei Technologies Co., Ltd"
conference: osdi-2025
code_url: "https://github.com/IcicleF/Nos"
tags:
  - storage
  - fault-tolerance
  - rdma
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Nos argues that multiple-failure recovery in an in-memory KV store does not require stripes if placement itself enforces the right overlap constraints. It uses an SBIBD-based affinity matrix to decide which backups each primary may use, then lets backups asynchronously XOR buffered replicas into parities. Nostor, the KV store built on top of Nos, gets materially higher throughput than stripe-based erasure-coded baselines while using much less memory than full replication.

## Problem

The paper targets RDMA-based distributed in-memory storage systems that hold hot, latency-sensitive objects. In this setting, main memory is expensive enough that replication is unattractive, but the storage path is fast enough that the hidden control costs of conventional erasure coding become first-order bottlenecks. The authors argue that stripes are the root cause.

With intra-object striping, each object is split across `k` nodes, so even reading a small object fans out into multiple network I/Os. That is especially painful because prior measurements show that most in-memory KV objects are small. With inter-object striping, the system keeps whole objects intact, but now it must assign objects to stripes. Static policies waste memory when stripes end up partially empty or when placement cannot adapt to slow nodes; dynamic policies need a metadata service or proxy on the critical path, which adds latency, creates a bottleneck, and may become a single point of failure. On a fast RDMA fabric, neither tradeoff is appealing. The problem is therefore to keep erasure coding's storage efficiency without paying for stripe construction, stripe lookup, or object splitting.

## Key Insight

The core claim is that recoverability is fundamentally a placement property, not a stripe property. What stripes really buy is enough algebraic structure to guarantee that after up to `p` failures, some surviving encoded chunk still depends on recoverable live data. Nos recreates that guarantee without explicit stripes by constraining which primary nodes may replicate to which backup nodes.

The mechanism is a `(v, k, 1)` symmetric balanced incomplete block design (SBIBD), where `v = k^2 - k + 1`. Interpreting the SBIBD matrix as a primary-to-backup affinity matrix gives each primary exactly `k` admissible backup nodes, and any two primaries share at most one common backup. That overlap bound is the key invariant: when an object is replicated to `(p + 1)` backups and each backup XORs one object from each of its `k` source primaries into a parity, simultaneous failures cannot entangle every surviving parity beyond recovery. At worst, degraded recovery recurses once to reconstruct another missing object and then uses that result to reconstruct the target object.

## Design

Nos is parameterized by `(k, p)` with the precondition `k > p`. Each object has one primary copy plus `(p + 1)` replicas on backup nodes chosen from the primary's `k` SBIBD-approved targets. Backup nodes do not coordinate to assemble stripes. Instead, each backup receives replicas from `k` source primaries, buffers them by source, and in the background XORs one buffered replica from every source into a parity chunk. Because the primary copy remains unchanged, the code is systematic.

Nostor turns that coding scheme into a distributed in-memory KV store. It hashes keys first to a subcluster and then to a primary server. Foreground RDMA RPC threads handle client GET/PUT requests, while background threads digest replicated deltas into parities. PUTs are versioned: a primary appends the new version, assigns a sequence number, computes a delta against the prior version, replicates that delta to `(p + 1)` backups, and only then advances the committed sequence number so the write becomes visible and fault-tolerant. GETs simply read the committed head version at the primary.

The background pipeline is where Nostor avoids stripe-management overhead without giving up space efficiency. If a background thread can collect one new object from each replication-source queue, it emits a full parity with `k` encodees. If some queues are temporarily empty, it times out after 10 microseconds and creates a partial parity instead, then later tries to fill that parity using per-source parity queues. Updates apply by XORing new deltas into the existing parity; deletions may turn full parities back into partial ones. For failures, Nostor first brings all surviving replication targets of a failed server to a consistent committed state, then serves degraded reads by querying all living backup nodes, picking the parity that involves the fewest failed objects, and recursively decoding if needed. Node repair reconstructs missing primaries and parities in parallel.

## Evaluation

The evaluation runs on 16 CloudLab nodes with 100 Gb RDMA NICs and compares Nostor against Cocytus, PQ, Split, and plain replication. The setup stresses exactly the regime the paper cares about: small values, high request rates, and in-memory access paths where extra fanout or control-plane coordination should dominate.

The microbenchmarks validate the central thesis. For 100%-GET workloads on small values, Nostor reaches `3.92x` the throughput of Split at `(k, p) = (4, 2)` and `6.06x` at `(6, 2)`, closely matching the reduction in I/O fanout from whole-object access. For PUTs, it stays near replication for 64 B values and clearly outperforms Cocytus and PQ because it avoids synchronized stripe allocation. A dummy design that adds an MDS into the I/O path performs even worse, losing `89.2%` of GET throughput and `72.4%` of PUT throughput relative to Nostor, which strongly supports the paper's claim that centralized placement lookup is unacceptable here.

The end-to-end results are also strong. Across real Twemcache traces, Nostor improves throughput by `1.61x` to `2.60x` over the erasure-coded baselines while keeping similar or lower median latency. It uses `18.7%` to `57.4%` less memory than replication and repairs nodes `16.4%` faster than Split. The main caveat is degraded reads: for `(4, 2)` and `(6, 2)`, Nostor's degraded-read latency is `16.5%` higher than Split on average, and in the worst-case `(6, 3)` recursive-recovery scenario it is `35.0%` higher than Cocytus and `62.4%` higher than Split. That tradeoff is consistent with the design, which optimizes common-case writes and steady-state reads rather than worst-case degraded access.

## Novelty & Impact

Relative to _Chen et al. (FAST '16)_, Nos does not try to make stripe-based in-memory erasure coding more tolerable; it removes stripes from the placement abstraction altogether. Relative to _Cheng et al. (SC '21)_, it is not a logging refinement around stripes but a different answer to how parity should be formed in memory. The paper's real novelty is importing SBIBD from combinatorial design into systems placement and using it to prove a stripeless recovery invariant that is simple enough to implement in a real KV store.

That makes the work interesting to two audiences. Systems builders working on RDMA in-memory stores, remote memory, or erasure-coded KV services get a concrete alternative to both replication and stripe allocation. Researchers in coding-for-systems get an example where the important contribution is not a stronger code algebra but a better placement structure for a modern performance regime.

## Limitations

Nos pays for its simplicity with rigid structural constraints. Because it needs a `(v, k, 1)` SBIBD, the cluster size is tied to `v = k^2 - k + 1`, and each node only exchanges coded data with `Theta(sqrt(v))` peers rather than the whole cluster. That makes mixing multiple `k` values or adapting the policy to arbitrary cluster layouts harder than with Reed-Solomon-style schemes.

The design also consumes more network bandwidth than conventional erasure coding. Each write sends one extra replica relative to a scheme that only needs `p` parity destinations, and degraded recovery may read `O(kp)` objects before amortization brings the average cost back down. The benefits are explicitly aimed at fast in-memory systems; the paper says slow-storage systems would see limited gains, and wide-stripe regimes with very large `k` are a poor fit because the required number of failure domains grows quadratically. Finally, Nostor disallows degraded writes, and the evaluation uses two logical servers per physical node, so the failure-domain realism is weaker than a production deployment.

## Related Work

- _Chen et al. (FAST '16)_ - Cocytus also applies erasure coding to an in-memory KV store, but it still allocates objects into stripes; Nos removes stripe allocation and its associated placement bottlenecks.
- _Rashmi et al. (OSDI '16)_ - EC-Cache uses intra-object chunking and online erasure coding for low-latency cluster caching, whereas Nos keeps objects whole and avoids the `k`-way access fanout of split-object designs.
- _Cheng et al. (SC '21)_ - LogECMem improves an in-memory KV store with parity logging, but it remains a stripe-based design; Nos instead discards stripes as the organizing abstraction.
- _Lee et al. (FAST '22)_ - Hydra studies resilient remote memory under a far-memory model, while Nostor provides a multi-client distributed KV store with committed PUT semantics and stripeless inter-object coding.

## My Notes

<!-- empty; left for the human reader -->
