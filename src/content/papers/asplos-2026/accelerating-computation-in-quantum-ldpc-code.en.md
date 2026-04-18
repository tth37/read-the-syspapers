---
title: "Accelerating Computation in Quantum LDPC Code"
oneline: "ACQC speeds up qLDPC fault-tolerant computing with dedicated pivot modules for Pauli-product decomposition and qLDPC-native magic-state distillation."
authors:
  - "Jungmin Cho"
  - "Hyeonseong Jeong"
  - "Junpyo Kim"
  - "Junhyuk Choi"
  - "Juwon Hong"
  - "Jangwoo Kim"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790122"
tags:
  - quantum
  - hardware
  - compilers
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

ACQC asks whether qLDPC codes can be practical not just as low-overhead quantum memory, but as the place where fault-tolerant computation itself happens. Its answer is to cut the cost of Pauli-product-measurement decomposition with dedicated pivot modules, then claw back most of the added qubit cost with shared pivots and qLDPC-based magic-state distillation. Across the paper's simulator, that turns qLDPC computing from a 40-70 day proposition into an estimated 11-17 day one while staying close to the low-qubit promise that made qLDPC attractive in the first place.

## Problem

The paper starts from a genuine systems tension in fault-tolerant quantum computing. Surface codes are operationally convenient because they can execute arbitrary Pauli product measurements directly, but they pay for that convenience with enormous physical-qubit overhead. qLDPC codes, especially Bivariate Bicycle codes, look much better on qubit efficiency: the paper cites order-of-magnitude reductions versus surface codes. Unfortunately, that efficiency comes with a restrictive interface. A qLDPC module can only execute a limited family of native Pauli product measurements determined by its ancilla system, so arbitrary program measurements must be decomposed into long sequences of native ones.

That decomposition overhead is the real bottleneck. The baseline technique the paper builds on adds an average `17.4x` execution-time overhead, pushing practical chemistry and factoring workloads from a few days on fast surface-code pipelines to roughly `47.4` and `76.8` days on qLDPC. Prior attempts to escape that trap each give up something important. Complex ancilla systems can support arbitrary measurements, but they raise both connectivity degree and qubit count. Hybrid designs such as HetEC use qLDPC as memory and surface code as the compute engine, but then load/store traffic and surface-code patches erase much of the hoped-for efficiency. The paper's target is therefore sharper than "make qLDPC faster": preserve the minimal-connectivity, low-qubit character of qLDPC modules while making in-qLDPC computation fast enough to matter.

## Key Insight

The core idea is that the standard one-pivot decomposition is paying for an implementation choice, not a mathematical necessity. It serializes everything so one ancillary logical qubit can be reused, which means the same native measurements are applied repeatedly. ACQC observes that if one treats surface-code lattice surgery as an unrolled sequence rather than a monolithic operation, an arbitrary measurement can instead be expressed as a progression of distinct pivot interactions. That immediately suggests using multiple pivots so each native measurement is consumed once instead of twice.

The second part of the insight is that the qubit blowup from extra pivots is structurally manageable. Pivots do not need to live in the same qLDPC module as program logical qubits, and distillation workloads only exercise a narrow subset of measurement types. Once those two facts are exploited, ACQC can spend qubits where they buy latency, then recover much of that cost with shared pivot layouts and a distillation design tailored to qLDPC's native I/Z measurements. In short, the paper argues that qLDPC's problem is not that it lacks fast computation primitives, but that prior decompositions and factories were organized around the wrong granularity.

## Design

ACQC has three connected mechanisms. First is fast PPM decomposition. The paper replaces the baseline's one-pivot, six-native-PPM-per-round decomposition with direct decomposition that uses multiple pivots and a pivot-decoupled layout. Program logical qubits stay in one module, pivots move to a dedicated module, and physical data qubits in the pivot module are measured directly so pivot initialization and readout no longer serialize through one ancilla path. This also lets the compiler search across all native PPMs, not just single-program-qubit-plus-pivot patterns. On the gross code, the paper reports that arbitrary PPMs drop from `17.4` native PPMs on average to `3.76`, yielding about `4.6x` average speedup for decomposition itself.

Second is qubit-efficient PPM decomposition. Fast decomposition is latency-friendly but pivot-hungry, so the paper introduces a pivot-module-sharing layout where two program modules share one pivot module by exploiting the X/Z ancilla-system split across unprimed and primed blocks. It then adds a hybrid decomposition policy: use the fast method for the overwhelming majority of PPMs that need only a few rounds, and a slower pivot-efficient recursive scheme for the tiny tail that would otherwise require many pivots. For the gross code, the paper says this caps the pivot requirement at three while adding only `0.03%` execution-time overhead, effectively halving pivot-module overhead.

Third is qubit-efficient distillation. Faster execution consumes magic states faster, so the naïve answer would be "buy many more surface-code factories," which destroys the qubit story. ACQC instead implements distillation inside qLDPC modules. Two optimizations matter. In-module parallel distillation runs two sequences at once on the unprimed and primed halves of one gross code module, reducing ancilla overhead per sequence. Decomposition-free distillation then uses native I/Z PPMs that touch otherwise unused qubits, after initializing those unused qubits in the Z basis so extra Z operators become harmless. That removes pivot modules from distillation entirely and lowers distillation latency by `42.4%`.

## Evaluation

The evaluation uses a custom simulator because no current hardware can implement the full qLDPC setup directly. Benchmarks come from QASMBench and MQT Bench and include `adder`, `ising`, `multiplier`, `qft`, `qpe`, `qram`, and `square_root`. The comparisons are fairer than many architecture papers: the authors report logical error rates alongside qubit count and execution time, use both serial and parallel qLDPC baselines, compare against all-surface-code execution (`PBC` and `EDPC`), and include HetEC-style qLDPC-as-memory configurations.

The headline result is that ACQC shifts the Pareto frontier rather than merely moving along it. Relative to the baseline qLDPC compute-in-code design, ACQC improves execution time by `4.4x` in the serial setup and `5.2x` in the parallel setup while using only `4.7%` and `35.5%` more qubits, respectively. Relative to `PBC`, it cuts qubit count by `8.2x` and `5.8x` while being only `3.6x` and `2.0x` slower. The cumulative breakdown is also informative: fast decomposition adds qubits mostly in pivot modules and distillation; shared pivots shave `12.3%` and `8.6%` of total qubits back; qLDPC-aware distillation cuts another `32.2%` and `41.9%`.

I found the broader generalization evidence convincing. Across several qLDPC codes, fast decomposition reduces the native-PPM count by `4.58x` on average, and the distillation design lowers magic-state space-time cost by `61.0%` across the evaluated sequences. The practical-workload extrapolation is more speculative but still useful: multiplying the measured speedups into prior chemistry and factoring estimates yields execution times of about `11` and `17` days instead of `40` and `70`. A small real-hardware experiment on IBM's Heron processor cannot validate correctness, but it does reproduce the predicted speedup trend: `5.04x` on hardware versus `4.85x` in simulation.

## Novelty & Impact

Relative to _Stein et al. (ASPLOS '25)_, ACQC's main move is refusing to retreat to "qLDPC for memory, surface code for compute." It treats the limited native-measurement set as a compiler-and-layout problem and then redesigns the surrounding architecture so the compiler's faster decomposition does not bankrupt the system in qubits. Relative to complex-ancilla approaches such as _Cohen et al. (Science Advances '22)_, the contribution is to keep the minimum connectivity target and still recover most of the performance benefit.

That makes the paper important for the part of quantum systems research that cares about resource-balanced FTQC, not just asymptotic code properties. It is not proposing a new qLDPC family; it is showing how to organize modules, decomposition, and factories so existing qLDPC codes become a more plausible compute substrate. If later qLDPC hardware arrives, this is the kind of systems blueprint that hardware architects and compiler researchers are likely to cite together.

## Limitations

The biggest limitation is obvious and important: the paper evaluates ACQC almost entirely through simulation because the required qLDPC hardware does not yet exist. The real-hardware section only validates timing trends on remapped ESM circuits, and the authors explicitly say it cannot verify functional correctness at current physical error rates. The benchmark set is also intentionally small because today's small-distance qLDPC codes cannot support full-scale practical applications; the long-running chemistry and factoring numbers are estimates derived from average speedups rather than end-to-end executions.

There are also some narrower design constraints. ACQC's qLDPC distillation optimization is tuned to distillation sequences dominated by I/Z PPMs, and the paper notes that the third solution does not apply to cultivation-style magic-state factories. The error-rate model for the `⟦98, 6, 12⟧` pivot module is conservative but borrowed from the gross code rather than measured directly. More broadly, the whole design assumes the compiler can brute-force efficient native-PPM combinations for the chosen code family; the paper shows this works for the tested BB-style codes, but does not claim a universal method for every future qLDPC construction.

## Related Work

- _Bravyi et al. (Nature '24)_ — establishes low-overhead qLDPC memory as a credible substrate, but does not solve how to execute general computation quickly inside the code.
- _Stein et al. (ASPLOS '25)_ — HetEC uses qLDPC codes as memory and surface codes as the active compute layer, whereas ACQC tries to keep both storage and computation inside qLDPC modules.
- _Litinski (Quantum '19)_ — surface-code lattice surgery provides the "arbitrary PPMs are cheap" reference point that ACQC partially emulates by unrolling and restructuring decomposition.
- _Gidney and Fowler (Quantum '19)_ — efficient surface-code magic-state factories are the qubit/latency baseline that motivates ACQC's qLDPC-native distillation redesign.

## My Notes

<!-- empty; left for the human reader -->
