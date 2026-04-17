---
title: "A Data-Driven Dynamic Execution Orchestration Architecture"
oneline: "Compiler-programmed FSM orchestrators and time-lapsed SIMD let Canon retime one spatial fabric for sparse and dense kernels while staying close to specialized accelerators."
authors:
  - "Zhenyu Bai"
  - "Pranav Dangi"
  - "Rohan Juneja"
  - "Zhaoying Li"
  - "Zhanglu Yan"
  - "Huiying Lan"
  - "Tulika Mitra"
affiliations:
  - "School of Computing, National University of Singapore, Singapore"
  - "Lumai Ltd., Oxford, UK"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762226"
tags:
  - hardware
  - compilers
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Canon argues that a programmable accelerator does not have to choose between "hard-wired and fast" and "flexible but fragile." It combines compiler-programmed FSM orchestrators with a time-lapsed SIMD PE array so that regular structure is mapped statically while sparse or irregular events are handled dynamically at runtime. The payoff is a spatial architecture that stays near specialized accelerators on their home workloads while covering a broader mix of sparse, dense, and general kernels.

## Problem

The paper starts from a familiar architecture trade-off. Domain-specific accelerators win by baking compute and data movement into fixed datapaths, but that same specialization makes them brittle when kernels or input patterns change. CGRAs, FPGAs, and GPUs are much more programmable, yet their control overheads, compile-time routing decisions, and reliance on regular parallel structure make them lose efficiency once execution depends on runtime sparsity or irregular dependencies.

Sparse tensor kernels make this problem concrete. In SpMM and SDDMM, the hardware has to cope with irregular memory accesses, uneven work distribution across compute units, and reduction dependencies that create stalls if the execution order is too rigid. A fully static dataflow cannot adapt to those patterns, while a fully dynamic fabric pays heavily in control, buffering, and NoC complexity. The systems question is therefore how to keep the bulk efficiency of a spatial accelerator while spending dynamic control only on the parts of execution that are actually irregular.

## Key Insight

Canon's central claim is that many irregular workloads are not uniformly irregular. The high-level dataflow often remains predictable enough to place statically, while the last-mile choices, such as whether a sparse element exists, which partial sum should be accumulated, or when a reduction should be bypassed, must be made from runtime metadata. If the architecture isolates those decisions into a lightweight orchestrator rather than embedding heavy control in every PE, it can stay efficient without becoming brittle.

Time-lapsed SIMD is the second half of that idea. Instead of broadcasting one instruction to all PEs at once, Canon lets an instruction wave propagate across a row over several cycles. That staggered execution amortizes control and keeps timing deterministic: different PEs may be in different moments of the same instruction stream, but the row still behaves predictably enough that synchronization and routing can be managed by the orchestrators at the edge of the fabric.

## Design

Canon is a 2D mesh of processing elements. Each PE has a 4-wide vector lane, a router, local data memory, and a small dual-ported scratchpad; each row is managed by one programmable orchestrator. The design separates networks as well: instructions travel on a dedicated instruction NoC, while data moves on a circuit-switched NoC. That split lets Canon keep the compute fabric lightweight while still reconfiguring behavior online.

Each PE is a 3-stage pipeline (`LOAD`, `EXECUTE`, `COMMIT`). Instructions describe an operation plus operand/result addresses, and Canon uses a unified address space so the same instruction format can target registers, local memories, or router actions. Because instructions move across the row with a fixed three-cycle offset, the architecture obtains deterministic replay of compute, memory, and communication patterns from one PE to the next. The paper repeatedly leans on that determinism: it is what makes dynamic orchestration cheap enough to use per row.

The orchestrator is the real novelty. It is a compiler-programmed finite-state machine with a state register, state-meta registers, and inputs from the incoming metadata stream plus neighboring orchestrators. A LUT-backed programmable block generates instruction fields, state updates, addresses, and outgoing messages from that state. In effect, the orchestrator acts as a runtime data-to-instruction translator: sparse coordinates, row-end markers, or upstream partial-sum messages trigger different control actions without requiring a general-purpose control processor inside each PE.

The sparse-kernel mappings show how this machinery is meant to be used. For SpMM, rows of sparse matrix `A` stream through the array while tiles of dense matrix `B` stay in PE-local memory. Partial sums move vertically, and the scratchpad buffers them so a row can keep making progress even when upstream or downstream rows are imbalanced. The orchestrator decides whether a PE should continue MACs, accumulate an incoming partial sum, flush one downstream, or bypass it. For SDDMM, the mask drives sparse activation of work, and the scratchpad is repurposed to buffer and reuse streamed `A` vectors across masked positions. For regular kernels, Canon can also run in a more static spatial mode, but the paper is explicit that the compiler stack is not yet fully automated and still relies on loop analysis plus human-selected mappings.

## Evaluation

The evaluation is based on synthesis in a 22nm FDSOI process at `1 GHz` plus a cycle-accurate simulator. The default Canon configuration is an `8 x 8` INT8 array with `4`-wide SIMD lanes, `4 KB` SRAM per PE, a `64 B` dual-ported scratchpad per PE, eight row orchestrators, and `17 GB/s` LPDDR5x main memory. The baselines span the specialization spectrum: a dense systolic array, a `2:4` sparse systolic array, the ZeD sparse accelerator, and a conventional CGRA. Workloads include SpMM, unstructured and windowed SDDMM, PolyBench kernels, and sparse model components from ResNet-50, LLaMA-8B, and Mistral-7B.

The hardware cost is not hidden. Canon reports about `30%` more area than a systolic array, with scratchpads, orchestrators, and routing making up most of the delta; compared with ZeD it is about `12%` larger, and compared with the CGRA it saves about `7%` total area. On dense GEMM, that extra flexibility buys little, so the systolic design remains slightly better in performance per watt, with Canon adding less than `13%` power overhead from control and routing. But once sparsity enters, the specialized dense array can fall below `0.3x` of Canon's throughput because it cannot exploit the input pattern.

The more interesting result is that Canon is usually close to the best specialist without being locked to one pattern. It matches dense systolic behavior on GEMM, stays comparable to the `2:4` systolic variant on `2:4` sparse SpMM, and comes within `8%` of ZeD on denser unstructured sparse regimes while surpassing it at higher sparsity and on some inputs by up to `5%`. The paper also claims Canon outperforms all baselines on windowed SDDMM. Supporting evidence for the load-balancing story is fairly concrete: a scratchpad depth of `16` entries improves compute utilization by `10-20%` over a single-entry design for sparsity above `60%`, and compile-time tuning of the effective scratchpad range yields another `5%` on average. The evaluation therefore supports the main claim well: Canon really is trading a modest fixed hardware premium for much lower performance fragility across kernels and sparsity patterns, though many headline comparisons are presented as normalized plots rather than absolute throughput tables.

## Novelty & Impact

Relative to specialized sparse accelerators such as _Dangi et al. (PACT '24)_, Canon's move is not a new sparse datapath, but a new division of labor between compile time and runtime. Relative to CGRA-style fabrics, its novelty is that runtime reconfiguration happens through metadata-driven orchestrators rather than by stopping and remapping the array. And relative to dataflow-inspired general-purpose designs, it pushes that idea into a spatial accelerator where the same mechanism governs compute, routing, and buffering.

That makes Canon interesting beyond the two case studies in the paper. Anyone designing accelerators for sparse ML, irregular reductions, or mixed regular/irregular kernels can read it as a template for how to spend control budget surgically instead of uniformly. The contribution is best viewed as an architectural pattern, not just a faster SpMM engine.

## Limitations

The paper is candid that Canon is not yet a push-button platform. The compiler flow is incomplete, globally optimal mappings remain open, and the current workflow still uses polyhedral analysis plus human intervention to choose and tune dataflows. That matters because the architecture's payoff depends heavily on good mappings and on deciding when irregularity should be absorbed by the NoC versus the scratchpad.

The hardware also has clear regime boundaries. Low-DLP kernels can under-utilize the 4-lane SIMD organization, and the authors report that some low-parallelism PolyBench BLAS solvers favor the CGRA. Off-chip bandwidth pressure rises as arithmetic intensity falls; at `95%` sparsity, Canon may need roughly `7x` more bandwidth while delivering about `16x` equivalent dense throughput. Finally, the evidence comes from synthesis and simulation rather than a silicon prototype with a full software stack, so integration and programmability costs in practice are still partly unresolved.

## Related Work

- _Dangi et al. (PACT '24)_ — ZeD is a specialized accelerator for variably sparse matrix computation, whereas Canon tries to recover similar efficiency while tolerating more kernels and more sparsity structures.
- _Nguyen and Sanchez (MICRO '21)_ — Fifer handles irregularity by decomposing kernels into regular stages and queueing between them; Canon instead keeps decisions in place through orchestrator-driven execution over one fabric.
- _Wang and Kim (ASPLOS '21)_ — DiAG borrows dataflow ideas for general-purpose processors, while Canon applies runtime data-driven orchestration to a spatial PE mesh built for accelerator-style throughput.
- _Qin et al. (HPCA '20)_ — SIGMA targets sparse and irregular GEMM with flexible interconnects, but Canon aims to generalize beyond one sparse-kernel family into a broader programmable architecture.

## My Notes

<!-- empty; left for the human reader -->
