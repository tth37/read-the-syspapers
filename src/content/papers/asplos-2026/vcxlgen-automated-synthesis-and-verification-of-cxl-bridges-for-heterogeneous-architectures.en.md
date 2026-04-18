---
title: "vCXLGen: Automated Synthesis and Verification of CXL Bridges for Heterogeneous Architectures"
oneline: "Synthesizes CXL bridges from coherence-protocol specs, then verifies they preserve host memory semantics and scale liveness checking by composition."
authors:
  - "Anatole Lefort"
  - "Julian Pritzi"
  - "Nicolò Carpentieri"
  - "David Schall"
  - "Simon Dittrich"
  - "Soham Chakraborty"
  - "Nicolai Oswald"
  - "Pramod Bhatotia"
affiliations:
  - "Technical University of Munich, Munich, Germany"
  - "TU Delft, Delft, Netherlands"
  - "NVIDIA, Santa Clara, US"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790245"
code_url: "https://github.com/TUM-DSE/vCXLGen"
project_url: "https://doi.org/10.5281/zenodo.17939343"
tags:
  - disaggregation
  - hardware
  - verification
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

vCXLGen synthesizes CXL bridges directly from coherence-protocol specifications, then verifies that the resulting heterogeneous system preserves host memory semantics and still makes progress at scale.

## Problem

CXL 3.0 makes coherent multi-host memory plausible, but it only defines the fabric side. It does not tell a CPU or accelerator vendor how to reconcile CXL.mem with the host's existing local coherence protocol and memory consistency model. That gap matters because real systems are heterogeneous: x86, Arm, and accelerator-style protocols may all expose coherent memory while disagreeing on message semantics, race handling, and ordering rules.

Handwritten glue is risky because superficially similar protocols still differ in corner cases. CXL.mem adds handshakes such as `BIConflict`, while relaxed protocols may tie coherence effects to acquire/release events rather than plain loads and stores. A bad bridge can therefore silently change a host's original MCM. Prior synthesis work also does not fit cleanly: it assumes a more fixed hierarchy than CXL's local/global split, and whole-system verification quickly hits state-space explosion once several clusters and bridges are present.

## Key Insight

The paper's key claim is that interoperability should be expressed as a synthesized bridge between two coherence domains rather than as a host-specific protocol rewrite. The bridge keeps a compound state made of the host-side local directory state and the CXL-side global cache state, so it can tell when a local action must become globally visible and when a global event must be translated back into local effects.

That becomes tractable because vCXLGen enforces three rules: delegation, nesting atomicity, and selective stalling. Propagated operations are re-issued as native remote flows; the local flow completes only after the remote one completes; and only ordering-relevant requests are stalled, while necessary CXL snoops are still allowed to pass. This turns Compound MCM-style reasoning into a concrete synthesis recipe without requiring a handwritten semantic model for every protocol pair.

## Design

vCXLGen starts from ProtoGen specifications for a local protocol `LP` and a global protocol `GP` such as CXL.mem. A static flow-analysis pass builds translation tables from stable state plus first transition label to the underlying requester access, for example `S + GetM -> store`, and also detects global forwarded requests that imply permission downgrades back into the host domain.

The bridge state space is the Cartesian product of local-directory stable states and global-cache stable states. Transactions that need no propagation are copied directly. For propagated transactions, the generator searches the remote protocol for subtrees beginning with an equivalent access type, translates access vocabularies when necessary with ArMOR-style mappings, and nests the remote subtree inside the origin-domain flow. In effect, the bridge behaves as both a local directory and a CXL cache client.

Concurrency is the subtle part. vCXLGen synthesizes transient bridge states so origin-domain conflicts stall while a nested remote transaction is in flight, but it still lets CXL-side snoops that establish global serialization interleave; otherwise the bridge could block the very event needed to complete the outstanding request. The same bridge IR then feeds both SLICC controllers for gem5 and Murphi/Rumur models for verification, alongside an axiomatic `SC-vCXLGen-RC` model explaining why each host keeps its native ordering rules.

## Evaluation

The evaluation is broad for a synthesis paper. On generality, the authors synthesize bridges across MSI, MESI, MOESI, CXL, RCC, and RCC-O combinations, with CXL as the global protocol and both SWMR and relaxed-consistency protocols as locals. On extensibility, the specifications stay compact: roughly 650 lines of ProtoGen DSL for CXL.mem, around 350 for MSI-family protocols, and about 200 for RC protocols.

Correctness is checked in two layers. For safety, the authors generate 216 litmus-test models across SC/RC combinations and report that all match the intended compound MCM behavior. For liveness, they verify deadlock freedom and an extended liveness condition. The compositional result is the headline: compared with whole-system verification, memory drops by 92% on a medium setup and by more than 98% on a larger one, bringing a 2-cluster, 3-cache-per-cluster model under 60 GB where the full-system model runs out of memory even on a 1.8 TB server.

Performance is measured in gem5 on 35 PARSEC, Phoenix, and SPLASH applications, plus a distributed in-memory KVS using YCSB. A generated homogeneous bridge design, `MESI-Br`, stays within about plus or minus 2% of gem5's homogeneous `MOESI` baseline for most workloads, with a worst reported gap of 10%. `CXL-Br` is also usually close, but in seven applications its average overhead reaches up to 20.3%, which the paper attributes to CXL.mem's own handshakes and blocking transient states rather than to the synthesis machinery. In the KVS, `CXL-Br` stays within 1% of baseline throughput and `MESI-Br` is 6-8.8% higher.

## Novelty & Impact

Relative to _Oswald et al. (HPCA '22)_, the novelty is synthesis specialized for CXL's split local/global hierarchy rather than heterogeneous protocol fusion in the abstract. Relative to _Goens et al. (PLDI '23)_, it operationalizes compound memory-model ideas with concrete protocol synthesis, litmus-test checking, and a gem5 execution path. Relative to manual host-accelerator adapters such as _Olson et al. (ASPLOS '17)_, it turns one-off glue logic into a reusable generator plus a verification pipeline.

## Limitations

The bridge design assumes the global protocol is not weaker than the host protocols it connects, so SWMR-style globals such as CXL.mem are the main fit. The method also depends on machine-readable coherence specifications rich enough for static flow analysis and access-class mapping. Full-system liveness still does not scale without decomposition, compilation of the generated Rumur models is expensive, and the performance evidence comes mostly from gem5 rather than silicon. The paper diagnoses rather than fixes the handshake overheads imposed by CXL.mem, and its synchronous nesting design deliberately trades some protocol-specific latency optimization for generality and safety.

## Related Work

- _Oswald et al. (HPCA '22)_ — HeteroGen synthesizes heterogeneous coherence protocols by fusing protocol components, while vCXLGen focuses specifically on the local/global split and bridge semantics required by CXL multi-host coherence.
- _Goens et al. (PLDI '23)_ — Compound Memory Models provides the abstract guarantee that heterogeneous threads can retain their native memory-model views; vCXLGen instantiates that idea with concrete bridge generation and verification.
- _Tan et al. (ASPLOS '25)_ — Formalising CXL Cache Coherence clarifies CXL's formal semantics, whereas vCXLGen tackles the engineering problem of connecting host protocols to CXL.mem and proving the resulting whole system makes progress.

## My Notes

<!-- empty; left for the human reader -->
