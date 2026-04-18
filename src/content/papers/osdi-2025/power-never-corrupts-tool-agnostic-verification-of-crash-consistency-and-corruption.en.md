---
title: "PoWER Never Corrupts: Tool-Agnostic Verification of Crash Consistency and Corruption Detection"
oneline: "PoWER turns crash consistency into write preconditions and combines it with a CRC-based corruption model to verify PM storage systems in Verus and Dafny."
authors:
  - "Hayley LeBlanc"
  - "Jacob R. Lorch"
  - "Chris Hawblitzel"
  - "Cheng Huang"
  - "Yiheng Tao"
  - "Nickolai Zeldovich"
  - "Vijay Chidambaram"
affiliations:
  - "University of Texas at Austin"
  - "Microsoft Research"
  - "Microsoft"
  - "MIT CSAIL and Microsoft Research"
conference: osdi-2025
code_url: "https://github.com/microsoft/verified-storage"
tags:
  - verification
  - storage
  - persistent-memory
  - crash-consistency
category: verification-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PoWER reframes crash consistency as an obligation on every durable write: before issuing the write, prove that every crash state reachable by a partial persistence of that write is recoverable. The paper combines that idea with a CRC-level media-corruption model and a tiny atomic primitive, the corruption-detecting Boolean (CDB), then uses the package to verify two persistent-memory systems in ordinary verifier ecosystems. CAPYBARA KV verifies in 54 seconds on one thread or 23 seconds on eight threads and is performance-competitive with unverified PM key-value stores on many workloads.

## Problem

The paper tackles two properties that storage developers care about but verification tools handle poorly: crash consistency and corruption detection. The difficulty with crash consistency is not that developers cannot describe recovery, but that standard Hoare-style specifications only talk about a function's entry and exit states. Crashes happen in the middle, and prior verified storage systems therefore introduced specialized machinery such as Crash Hoare Logic, crash invariants, or TLA-style refinement proofs. Those techniques work, but they are verifier-specific, add a steep learning curve, and make it hard to reuse mainstream tools like Dafny or Verus as they are.

Corruption detection has a parallel problem. Existing verified work, especially VeriBetrKV, reasons about checksums under restrictive assumptions: the checksum is embedded with the data and atomically updated with it. That assumption is often false for real storage systems, and is especially awkward on persistent memory, where atomic persistence granularity is only 8 bytes. The result is a bad combination: the proof techniques are too tool-specific, the corruption model is too rigid, and the verified systems produced so far have not obviously matched the performance envelope of serious PM stores. The paper's goal is to close all three gaps at once.

## Key Insight

The central insight is that crash reasoning can be pushed into the precondition of the storage write API instead of baked into the verifier. A write call already knows the pre-state, the address being updated, the bytes being written, and the device's atomic write granularity. That is enough to quantify over every crash state that could arise if some chunk-aligned subwrites persist and others do not. If the caller proves that all such newly introduced crash states are legal before the write executes, then ordinary Hoare logic is sufficient: the verifier never needs a special language construct for "the system crashed here."

The paper applies the same style of simplification to corruption. Rather than axiomatizing one specific layout rule for data and checksums, it models the device as having a bounded corruption bitmask. Reads may return bytes with up to `c` corrupted bits, and the system gets a trusted CRC theorem stating that buffers within Hamming distance `[1, c]` have different CRCs. That makes corruption detection a statement about the physical error model, not about whether checksums sit next to data or are atomically updated with it.

## Design

PoWER exposes a storage API with `read`, `write`, and `flush`, but `write` carries a new precondition. The caller must provide a ghost permission showing that every state reachable by partial application of the write is permitted. The paper instantiates this with a prophecy-based storage model containing a `read_state` and a `durable_state`. A write updates `read_state` completely and `durable_state` with an arbitrary subset of chunk-granularity subwrites; a flush does not "perform" writes so much as confirm that the prophesized durable state now matches the readable one. Permissions can describe either a set of allowed crash states or allowed transitions between states, and they can be blanket permissions reused indefinitely or single-use permissions consumed by a mutating operation.

The paper's practical contribution is not just the API, but the proof discipline layered on top of it. It classifies durable writes into four categories. Tentative writes update bytes that are unreachable during recovery, so the proof only needs to show that the written addresses are abstractly unused. Committing writes change abstract state with one crash-atomic update, so the proof reduces to reasoning about two cases: the commit write lands or it does not. Recovery writes replay a journal or other repair procedure, so the proof relies on idempotence and the fact that later recovery overwrites any torn earlier attempt. In-place writes, which expose partially updated user-visible state, are admitted only for weak crash semantics and currently get no library support. For concurrency, the paper extends the scheme to "atomic PoWER" with durable ghost state and completion objects, which is enough for reader-writer locking and sharded regions, but not for overlapping concurrent writes to the same region.

The corruption side mirrors that structure. `read` returns a value related to the true bytes by a `maybe_corrupted` predicate, and clients must perform a CRC check before trusting the data. On PM, ordinary per-block CRC updates are not crash-atomic, so the paper introduces the corruption-detecting Boolean. A CDB is an 8-byte value that can only be one of two CRC-chosen constants, `CRC(0)` or `CRC(1)`. Because the CDB itself fits in PM's atomic write unit, it can serve as the commit point between two separately checksummed copies of a structure. The authors use this across two systems: CAPYBARA KV, a verified PM key-value store in Verus with tables, a redo journal, copy-on-write updates, and a trusted `pmcopy` crate for layout-safe PM copies; and CAPYBARA NS, a verified notary service in Dafny that atomically updates a timestamp/hash pair.

## Evaluation

The evaluation has two parts: proof effort and CAPYBARA KV performance. On proof effort, the results are concrete. CAPYBARA KV contains 14,255 lines of specification/proof, 5,531 lines of implementation, and 5,244 trusted lines, for a proof-to-code ratio of 2.6. CAPYBARA NS is much smaller at 673 lines of specification/proof, 278 lines of implementation, and 414 trusted lines. Verification time is also practical: 54 seconds for CAPYBARA KV on one thread, 23 seconds on eight threads, and 12 seconds for CAPYBARA NS. The paper also reports that porting the PM specification and supporting libraries from Verus to Dafny took hours, not weeks, which is the strongest evidence for the "tool-agnostic" claim.

For performance, CAPYBARA KV is compared against pmem-Redis, pmem-RocksDB, and Viper. The microbenchmarks show similar or better item-operation latency than pmem-RocksDB, while pmem-Redis is consistently slower because of client-server overhead. In YCSB, CAPYBARA KV clearly beats pmem-Redis and pmem-RocksDB in both single-threaded and 16-thread experiments, and is roughly competitive with Viper in the single-threaded case while often outperforming it in the sharded 16-thread configuration. The evaluation does not pretend there are no costs: CAPYBARA KV starts much more slowly than RocksDB-style systems because it rebuilds its volatile index, taking 7 seconds on an empty instance and 53 seconds on a full one, and it keeps all keys in DRAM. Overall, the evidence supports the claim that verification did not force an obviously uncompetitive PM design, though the performance section validates CAPYBARA KV more directly than PoWER itself.

## Novelty & Impact

Relative to _Chen et al. (SOSP '15)_ and the Perennial line of work, the novelty is that crash consistency is encoded using standard verifier constructs rather than new crash-specific logics exposed to application proofs. Relative to _Hance et al. (OSDI '20)_, the paper removes the need for TLA-style refinement reasoning and replaces a layout-constrained corruption axiom with a lower-level bit-flip model that tolerates noncontiguous data and separately stored checksums. The CDB is also a real systems contribution, not just a proof trick: it gives a compact, PM-specific way to make checksum-protected updates appear atomic.

This paper is likely to matter to two groups. Verified-storage builders get a method that can ride on mainstream verifiers instead of forcing them into one proof assistant and one style of crash reasoning. Persistent-memory system designers get a proof-friendly corruption/update pattern that still maps onto realistic PM behavior. The contribution is therefore both a methodology paper and a systems paper, not merely a case study.

## Limitations

PoWER is tool-agnostic only within a boundary: the verifier still needs Hoare logic, ghost state, and quantifiers. The paper explicitly says that highly automated tools such as Yggdrasil and TPot do not fit that requirement. The concurrency story is also deliberately narrow. PoWER can support concurrent reads and sharded or partitioned writes, but it cannot reason about fine-grained concurrent reads and writes to the same storage region because the caller must know the region's current logical state when issuing a write.

There are also trusted and workload-specific assumptions. The correspondence proof to Crash Hoare Logic is metalogical because PoWER is translated into Rocq rather than implemented there directly. CAPYBARA KV relies on trusted components such as `pmcopy`, the compiler, and the verifier, and its design is tuned for small fixed-size records on tens of GiB of dedicated PM. It requires static space provisioning, lacks dynamic resizing and range queries, rebuilds a volatile key index at startup, and pays noticeable startup latency. The PM model also intentionally overapproximates some reorderings, so the proofs are conservative rather than hardware-minimal.

## Related Work

- _Chen et al. (SOSP '15)_ — FSCQ introduces Crash Hoare Logic inside Rocq, whereas PoWER keeps crash reasoning in ordinary write preconditions that can be encoded in mainstream verifiers.
- _Hance et al. (OSDI '20)_ — VeriBetrKV proves crash safety by treating storage as a distributed-system refinement problem; PoWER avoids that heavier proof stack and loosens checksum-placement assumptions.
- _Chajed et al. (SOSP '19)_ — Perennial provides crash invariants and logically atomic crash specifications; PoWER shows how much of the same end-to-end effect can be packaged behind a simpler API contract.
- _Chajed et al. (OSDI '21)_ — GoJournal demonstrates verified concurrent crash-safe journaling, while this paper focuses on making similar proof obligations portable across verifier ecosystems and PM corruption models.

## My Notes

<!-- empty; left for the human reader -->
