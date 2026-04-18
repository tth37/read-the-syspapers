---
title: "Orthrus: Efficient and Timely Detection of Silent User Data Corruption in the Cloud with Resource-Adaptive Computation Validation"
oneline: "Orthrus validates annotated data-path closures on other cores and checks control/data boundaries with checksums to catch most cloud SDCs at low overhead."
authors:
  - "Chenxiao Liu"
  - "Zhenting Zhu"
  - "Quanxi Li"
  - "Yanwen Xia"
  - "Yifan Qiao"
  - "Xiangyun Deng"
  - "Youyou Lu"
  - "Tao Xie"
  - "Huimin Cui"
  - "Zidong Du"
  - "Harry Xu"
  - "Chenxi Wang"
affiliations:
  - "University of Chinese Academy of Sciences"
  - "UCLA"
  - "UC Berkeley"
  - "Peking University"
  - "Tsinghua University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764832"
code_url: "https://github.com/ICTPLSys/Orthrus"
tags:
  - fault-tolerance
  - observability
  - datacenter
  - compilers
category: verification-and-reliability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Orthrus targets silent user-data corruption caused by post-installation CPU errors without paying the cost of full replication. It asks developers to mark user-data types and data-path operators, then uses compiler-inserted versioned memory, asynchronous cross-core re-execution, and lightweight checksums on control/data boundaries to catch most corruptions with about 4% average runtime overhead.

## Problem

The paper starts from an uncomfortable operational fact: modern datacenter CPUs can become "mercurial" after deployment, producing rare but reproducible computation errors on particular cores. In a cloud setting, those errors matter most when they silently corrupt user data rather than crash the program. A wrong account balance, wrong key-value lookup result, or wrong analytic output is much worse than a fail-stop because it can escape to the user, violate SLAs, and trigger long forensic and legal fallout.

Existing defenses miss the target or cost too much. Offline CPU testing can identify bad processors eventually, but it does not tell operators which user data was corrupted before the next test window. Checksums help only when data is corrupted while being stored or transmitted; they do not catch CPU errors that compute the wrong update and then write a perfectly well-formed but incorrect value. At the other extreme, replication-based validation replays the whole application on another machine, while instruction-level validation re-checks execution nearly cycle by cycle. Both can detect more faults, but their CPU, memory, and synchronization costs are too high for production cloud services.

Orthrus therefore asks a narrower question: can we validate only the parts of a cloud application that actually compute over user data, and do so quickly enough that the mechanism is deployable online?

## Key Insight

The central claim is that cloud applications often expose a useful asymmetry between control path and data path. The control path parses requests, schedules work, and moves data around, but usually does not transform user data itself. The data path, by contrast, consists of compact operators such as `get`, `set`, `insert`, `map`, and `reduce` that actually compute on user-visible state. If Orthrus re-executes only those operators on another core using the same input and the same initial heap state, it can detect most harmful CPU-induced corruptions without replicating the entire process.

This decomposition also suggests a hybrid validator. Re-execution is worth spending on data-path operators because that is where wrong computation mutates user data. The control path can instead be checked with cheap per-object checksums at the moments data crosses the boundary between control logic and data operators. Orthrus is therefore not trying to prove whole-program correctness; it is trying to spend validation budget exactly where silent corruption is most likely to matter.

## Design

Orthrus exposes two annotations: `user-data` marks classes or structs whose instances represent protected user data, and `closure` marks a data-path operator as a unit of validation. An LLVM-based compiler pass then rewrites the operator. User-data allocations become `OrthrusNew` allocations in a versioned shared space; ordinary allocations stay in a private heap. Pointers to protected objects become `OrthrusPtr`s whose `load()` returns immutable data and whose `store()` performs an out-of-place update that creates a fresh version. Escape analysis keeps temporary objects in the private heap when they provably die before the closure returns, which reduces metadata and versioning overhead.

The runtime splits execution into an application process and a validator process. They have separate private heaps but share the versioned user-data space. When a closure finishes, Orthrus emits a closure log containing the closure identity, its inputs, its outputs, the versions it read, and any system-call results that must be replayed instead of re-executed. Because the log and the referenced versions fully describe the closure's starting state, the validator can re-run that closure on a different core later and out of order. Its writes go only to the validator's private heap, and its output is compared with the logged application output using either an overloaded equality operator or a bitwise comparison.

Control-path protection is cheaper. Each user-data version carries a 16-bit CRC checksum. Orthrus generates a checksum whenever a new protected object or version is created, and verifies it whenever data crosses from control path into data path or back. This catches corruption introduced while requests are parsed, copied, or forwarded, without paying for whole-program re-execution.

The scheduler is where the "resource-adaptive" part actually lives. Orthrus keeps per-core validation queues, prefers running validation on idle cores in the same NUMA node for cache-local log sharing, and samples when resources are tight. Sampling is guided rather than random: closures that have not been validated recently, or that appear under a new caller context, get higher priority, and closures containing floating-point or vector instructions are prioritized because prior fleet studies found those units especially vulnerable. Shenango-based validator threads can be added dynamically when closure-specific latency rises, and work stealing prevents one long queue from delaying corruption detection. A garbage collector reclaims stale versions using an approximate overlap test between a version's visible window and each closure's active window, which keeps versioning from exploding memory usage.

## Evaluation

The evaluation uses four real applications with clear data/control splits: Memcached, Masstree, an in-memory LSMTree tier, and Phoenix MapReduce. Experiments run on three servers with dual Xeon Gold 6342 CPUs and 100 Gbps InfiniBand. The main baselines are the original application and a replication-based validator. Since real mercurial-core faults are rare, the authors inject machine-level faults with an LLVM-based framework modeled after Alibaba's reported error types across ALU, SIMD, FPU, and cache-related instructions.

The headline result is that Orthrus stays close to vanilla performance. Averaged across workloads, it adds about 4% runtime overhead and 25% memory overhead, while RBV costs about 2.0x runtime and 2.1x memory. Memcached throughput drops only 4.4%; Phoenix adds under 2% time overhead; LSMTree still retains 95% of vanilla throughput even under a deliberately write-heavy workload. Checksum generation and verification on control-path boundaries add less than 1% overall overhead.

Timeliness is the second important result. Average validation latency is 1.6 microseconds for Memcached, 22.6 microseconds for Masstree, 7.7 microseconds for LSMTree, and 234 milliseconds for Phoenix. In the latency-sensitive services, this is two to three orders of magnitude lower than RBV because Orthrus validates only closures, uses shared-memory logs, and allows out-of-order re-execution instead of serializing a replica behind the primary.

Coverage is good but intentionally not perfect. With one validation core, Orthrus detects about 86.7% of injected SDCs on average; with two cores that rises to about 91%, and with four cores to about 96%. The one-core case is still 1.41x better than unguided random sampling. When Orthrus is given as many cores as the application, its upper-bound detection rates are within a couple of points of RBV for most error classes, though RBV still wins slightly because it also replays more of the control path.

## Novelty & Impact

Relative to replication-based validation, Orthrus's novelty is not "run a backup copy more cheaply"; it changes the unit of redundancy from whole request execution to annotated data-path closures. Relative to instruction-level validation, it gives up completeness in exchange for deployability on commodity cloud servers. The compiler/runtime co-design is what makes that trade believable: versioned user-data memory, closure logs, cross-core validation, and adaptive sampling fit together into a system that can run continuously rather than only during testing.

This is likely to matter for operators of data stores and data-processing services that already have a clean separation between routing logic and user-data operators. It also suggests a broader methodological point: if silent hardware faults are localized and reproducible, then online protection does not need to mirror the whole application. It can mirror only the semantically dangerous slice.

## Limitations

Orthrus is explicitly a best-effort detector, not a complete safety net. It cannot detect masked errors that leave the final result unchanged. It does not directly validate non-deterministic system calls, synchronization primitives, or external I/O inside a closure; instead it logs and replays their results, so corruption inside those operations may escape detection. It can also miss control-path errors that invoke the wrong closure, because the checksum mechanism only verifies data integrity at the boundary, not whether the boundary crossing itself was the right one.

The design also depends on structural assumptions. Developers must identify user-data types and closure boundaries, and each closure must be single-threaded internally. Sampling means some executions are skipped under resource pressure, so detection rates fall on highly parallel or write-heavy workloads such as Phoenix with only one validation core, or Masstree under tight memory budgets. Finally, Orthrus detects corruption and can optionally delay user-visible operations in a strict safe mode, but it does not recover corrupted state by itself.

## Related Work

- _Hochschild et al. (HotOS '21)_ - "Cores that don't count" documents persistent post-installation CPU errors in production fleets; Orthrus turns that operational diagnosis into an online application-level defense.
- _Ngo et al. (OSDI '20)_ - Copilots validate replicated state machines by running a coordinated replica, whereas Orthrus validates only data-path closures and uses versioned shared memory to avoid replica-wide synchronization.
- _Fiala et al. (SC '12)_ - HPC SDC detection and correction relies on redundancy and checkpointing for large jobs; Orthrus instead targets continuously running cloud services and user-data integrity.
- _Mukherjee et al. (ISCA '02)_ - Redundant multithreading validates at instruction granularity with stronger guarantees and much higher hardware/runtime cost; Orthrus retreats to closure-level validation to stay deployable in commodity clouds.

## My Notes

<!-- empty; left for the human reader -->
