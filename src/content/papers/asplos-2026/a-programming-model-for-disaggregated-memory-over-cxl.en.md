---
title: "A Programming Model for Disaggregated Memory over CXL"
oneline: "Defines CXL0, a formal CXL programming model for propagation-aware shared memory, then adapts FliT so linearizable objects stay durable under partial crashes."
authors:
  - "Gal Assa"
  - "Moritz Lumme"
  - "Lucas Bürgi"
  - "Michal Friedman"
  - "Ori Lahav"
affiliations:
  - "Technion, Israel"
  - "ETH Zürich, Switzerland"
  - "Tel Aviv University, Israel"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790121"
code_url: "https://www.github.com/cores-lab/cxl0"
tags:
  - disaggregation
  - persistent-memory
  - pl-systems
  - verification
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CXL makes shared memory look familiar while changing the failure model underneath it. CXL0 formalizes that change by tracking how far writes and flushes propagate, then uses that abstraction to adapt FliT so linearizable objects remain durable under partial crashes.

## Problem

CXL promises a coherent, disaggregated memory space that heterogeneous devices can access with ordinary loads and stores. But it breaks two assumptions behind ordinary shared-memory reasoning: there is no longer one local memory model, and there is no longer one failure domain. A remote node can cache a value, then crash independently of the machine that issued the write. That makes both legacy concurrent code and prior persistent-memory results hard to transfer. A write may already be visible remotely without being durable, and a locally adequate flush may still be too weak for a remotely owned line.

## Key Insight

The paper's key claim is that CXL should be modeled by propagation state, not by the prose names of low-level packets. Under partial crashes, the important question is whether a value reached only the issuer's cache, the owner's cache, or physical memory. Once that boundary is explicit, the surprising behaviors of disaggregated memory become explainable rather than ad hoc.

That is why CXL0 distinguishes `LStore`, `RStore`, and `MStore`, and similarly separates `LFlush` from `RFlush`. In a single-machine setting those might look like performance variants. Under disaggregation they encode different crash postconditions. The same distinction also makes FliT portable: local-persistence assumptions are replaced by `LStore` plus `RFlush`.

## Design

CXL0 models a system as multiple machines, each with a cache and an attached memory, communicating through CXL while sharing a coherent address space. Every address belongs to exactly one owner's memory. System state is a pair `(C, M)`: cache contents across machines and the owners' physical memories. Silent propagation steps move values between caches or from an owner's cache into memory, while crash steps wipe a machine's cache and volatile memory.

The abstraction exposes one load, three stores, and two flushes. `LStore` completes at the issuer's cache, `RStore` reaches the owner's cache or memory, and `MStore` reaches physical memory. `LFlush` pushes a line one level farther; `RFlush` forces propagation all the way to the owner's memory. The paper proves expected strength relations among these primitives and then uses litmus tests to show the unintuitive cases that matter: for example, one node can observe a write and another node's later crash can still erase it, unless the writer used a strong enough primitive such as `MStore` or `RFlush`.

The model is broad enough to describe host-device pairs, partitioned pools, and a future coherent shared pool. The authors also sketch two variants: one with cache-line poisoning on crash, and one where remote loads implicitly write back.

The second half of the design is the FliT adaptation. Original FliT assumes x86 persistent memory in one failure domain, so its flush discipline is too weak for CXL. The replacement is simple: stores become `LStore`, persistence is enforced with `RFlush`, and `completeOp` is empty because `RFlush` is already synchronous in the model.

## Evaluation

The evaluation asks two practical questions: which abstract CXL0 primitives can current hardware realize, and how much do those choices cost? The setup is an x86 host, an FPGA configured as a CXL Type 2 device using Intel's CXL IP, and a Teledyne LeCroy protocol analyzer.

Two results matter most. First, the mapping is incomplete: several CXL0 primitives exist semantically, but not all are directly exposed as useful ISA-level operations. The host cannot directly generate `RStore` or `LFlush`, and the device also lacks a practical `LFlush`. Second, the primitives have meaningfully different costs. Remote `Read` and `MStore` are about `2.34x` slower than local accesses from the host side and `1.94x` slower from the device side. On device writes to host-attached memory, `MStore` is `1.45x` slower than `RStore`, which is `2.08x` slower than `LStore`. `RFlush` is roughly as expensive as `MStore`.

That is enough to support the paper's main claim: propagation distance is a real hardware and performance distinction.

## Novelty & Impact

Relative to _Izraelevitz et al. (DISC '16)_, the paper extends durable-linearizability thinking from single-node persistent memory to coherent disaggregated memory with partial crashes. Relative to _Wei et al. (PPoPP '22)_, it shows why FliT stops being sound once visibility and durability can diverge across machines, then repairs it with CXL-aware primitives. Relative to CXL systems papers such as _Li et al. (ASPLOS '23)_, it contributes the semantic contract those systems would need for stronger correctness arguments.

This is likely to matter to CXL runtime builders, PL and verification researchers, and designers of concurrent libraries. It is best understood as a formalization plus a reusable transformation, not as a workload-optimization paper.

## Limitations

CXL0 assumes cache coherence and a shared-memory interface, so today's non-coherent shared pools fall outside its envelope unless software emulates coherence. The model also abstracts away each node's internal memory model and focuses on safety rather than liveness, so real implementations may still need architecture-specific fences and non-blocking algorithms.

The hardware validation is intentionally narrow: a host-FPGA CXL 1.1 setup rather than a full CXL 4.0 fabric, and isolated primitive latency rather than end-to-end applications. Some useful CXL0 primitives are not yet available as directly controllable operations, and the paper does not follow the FliT adaptation with a large application case study.

## Related Work

- _Izraelevitz et al. (DISC '16)_ — Introduces durable linearizability for persistent memory under full-system crashes; this paper reuses that correctness lens but changes the failure model to independent machine crashes over CXL.
- _Wei et al. (PPoPP '22)_ — FliT gives a general persistence transformation for linearizable objects on x86; CXL0 shows why its local flush assumptions are insufficient under disaggregation and replaces them with `LStore`/`RFlush`.
- _Li et al. (ASPLOS '23)_ — Pond is a practical CXL memory-pooling system, whereas this paper supplies a semantics-level model for reasoning about concurrent correctness on top of such deployments.

## My Notes

<!-- empty; left for the human reader -->
