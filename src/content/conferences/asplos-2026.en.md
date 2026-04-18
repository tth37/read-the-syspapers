---
venue: ASPLOS
year: 2026
title: "ASPLOS '26"
location: "Pittsburgh, USA"
dates: "March 22-26, 2026"
url: "https://www.asplos-conference.org/asplos2026/program/"
paper_count_expected: 152
overview_status: complete
written_by: claude-opus
summary_date: 2026-04-18
categories:
  - id: llm-inference
    title: "LLM inference"
    description: "Serving, decoding, KV-cache management, prefill/decode disaggregation, speculative decoding, and LLM-specific accelerators."
  - id: llm-training
    title: "LLM & foundation-model training"
    description: "Training systems for LLMs and other foundation models: pipeline/tensor/MoE parallelism, mixed-precision, RL rollouts, superchip offload, and training monitoring."
  - id: ml-systems-beyond-llm
    title: "ML systems beyond LLMs"
    description: "3D Gaussian Splatting, diffusion serving, graph ML, neurosymbolic, mobile and embodied AI — systems work whose primary workload is not an LLM."
  - id: memory-and-disaggregation
    title: "Memory & disaggregation"
    description: "CXL programming models, pod-scale allocators, page migration, tiered memory, disaggregated transactions, and database pushdown on disaggregated storage."
  - id: privacy-and-security
    title: "Privacy & security"
    description: "FHE algorithms and accelerators, trusted execution environments, confidential serverless, zkVMs, and privacy-preserving oversight."
  - id: quantum
    title: "Quantum computing"
    description: "Fault-tolerant architectures, QEC circuit compilation and scheduling, analog-quantum simulation, distributed quantum algorithms."
  - id: compilers-languages-verification
    title: "Compilers, languages & verification"
    description: "Tensor compilers, hardware description languages, binary translation, program analysis, formal verification, fuzzing, and LLM-assisted compilation."
  - id: hardware-and-infrastructure
    title: "Hardware & infrastructure"
    description: "Accelerators, PIM, microarchitecture, DRAM protection, SmartNIC I/O, userspace networking, storage stacks, GPU clusters, and datacenter infrastructure."
---

ASPLOS 2026 brought **152 papers** in a single track — a sprawling program that
doubles as a map of where systems, architecture, and languages communities are
actually investing. The distribution is almost shockingly AI-heavy: roughly a
third of the program is about serving or training large models, and most of the
compiler and hardware work downstream of that is shaped by AI workloads. At the
same time, ASPLOS kept its classical breadth — CXL-era memory, quantum
computing, confidential computing, and verification all show up in force.

## Themes

**LLM serving has industrialized.** 25 of the 152 papers are LLM inference
systems. The center of gravity has shifted from "how do I paged-batch
effectively" (solved) to three harder questions: how to co-schedule prefill and
decode (QoServe, Towards High-Goodput MuxWise, Shift Parallelism, TPLA,
SwiftSpec, Bullet, PAT); how to build KV-cache hierarchies across GPU / CPU /
CXL / PIM (SpeContext, MoE-APEX, STARC, REPA); and how far custom silicon can go
(Hardwired-Neuron LPU, Ouroboros wafer-scale CIM, DFVG FPGA-draft/GPU-verify).
Quantization and precision are a persistent sub-theme (M2XFP, ZipServ, oFFN,
Mugi, Tilus) — low-bit inference is now a first-class target, not an afterthought.

**Training is catching up.** Only 8 papers sit under llm-training, but they span
every axis: multimodal pipelines (DIP), MoE rebalancing (LAER-MoE), RL rollouts
(RhymeRL, Taming the Long-Tail), subbyte precision (SNIP), superchip offload
(SuperOffload), and non-intrusive SmartNIC-based monitoring. Compared to 2024,
the community has clearly moved past "can we train a big model at all" into
"which part of the training stack is the next bottleneck."

**CXL is no longer speculative.** 10+ papers treat CXL and disaggregated memory
as shipping infrastructure: a formal programming model (CXL0), model-checking
tools (CXLMC, vCXLGen), pod-scale allocators (Cxlalloc), page-granularity
migration (PIPM), criticality-first tiering (PACT), disaggregated transactions
(CREST, CPU-Oblivious), and cross-domain performance prediction (Camp). The
conversation has moved from "what would CXL enable" to "what breaks when you
actually run real workloads across coherence domains."

**Quantum computing became a full track.** 11 papers cover QEC code
scheduling (AlphaSyndrome, PropHunt, iSwitch), dirty-qubit reasoning (QBorrow),
T-gate minimization (Reducing T Gates, ACQC for qLDPC), trapped-ion architecture
(Architecting Scalable Trapped Ion), distributed QSWAP (COMPAS), and analog
compilation (QTurbo). The set has matured enough that we added a dedicated
`quantum` tag this cycle.

**Compilers and PL are the connective tissue.** 34 papers — the largest
category — sit at compiler/PL/verification. Tensor compilers continue their arc
(Trinity, RedFuser, Linear Layouts, Insum, FuseFlow, Tilus, STeP), hardware DSLs
keep improving (Anvil's timing contracts, Lilac's latency-abstract interfaces,
PDL's precise exceptions), verification now reaches out-of-order dataflow
(Graphiti) and distributed ML (It Takes Two), and LLM-assisted compilation
appears five different ways (LPO peephole, LOOPRAG loops, PF-LLM prefetching,
Once4All SMT fuzzing, CacheMind explanation).

**Reliability is everywhere.** DRAM protection (RowArmor, APT), vector SDCs at
hyperscale (SEVI), radiation (Radshield), FHE accelerator resilience (ReliaFHE),
embodied-AI undervolting (CREATE), fault injection (PrioriFI), training-cluster
monitoring — the reliability story is cross-cutting rather than concentrated in
one track.

**FHE and TEE are going to production.** 6 FHE-accelerator papers (Cheddar,
Falcon, Maverick, ReliaFHE, CHEHAB RL, a GPU framework) suggest the community
believes FHE will clear throughput/latency bars soon. On the TEE side, TeeM3
moves isolation out of CPU modes, Trust-V hardens storage for TEEs,
WorksetEnclave attacks confidential-serverless cold starts, and a verification
effort found 35 confirmed inconsistencies in Arm CCA's spec.

## Notable trends

- **Disaggregation everywhere.** GPU memory offload, CXL pods, prefill/decode
  split, draft/verify split across FPGA+GPU, SmartNIC-offloaded I/O — the
  word-of-the-year is "split it."
- **Speculative everything.** Decoding (SwiftSpec, DFVG), prefetching (EARTH),
  Protobuf parsing (SpecProto), branch extension (FastTTS). "Speculate and
  recover" became a default pattern.
- **Sparsity is first-class.** Bit-level (BitRed), dynamic (Dynamic Sparsity in
  DiT), streaming (FuseFlow), compiler-discovered (Insum indirect einsums),
  sparse SpMM (Slaws). Not a corner case anymore.
- **Energy is tagged on 20 papers.** Power/carbon/lifetime is now a design axis
  alongside throughput and latency — not only in edge papers (FlexiFlow, TierX)
  but also in datacenter accelerators.

## Must-reads

- **[Shift Parallelism](/en/papers/asplos-2026/shift-parallelism-low-latency-high-throughput-llm-inference-for-dynamic-workloads)** — preserves the KV-cache layout so LLM serving can flip between sequence and tensor parallelism at runtime; a rare "simpler is better" result.
- **[A Programming Model for Disaggregated Memory over CXL](/en/papers/asplos-2026/a-programming-model-for-disaggregated-memory-over-cxl)** — the CXL0 model gives the community a precise, propagation-aware semantics for multi-host CXL; foundational reference work.
- **[Streaming Tensor Programs (STeP)](/en/papers/asplos-2026/streaming-tensor-programs-a-streaming-abstraction-for-dynamic-parallelism)** — a clean abstraction for dynamic shapes and control flow on spatial dataflow hardware, unlocking dynamic tiling and expert time-multiplexing without hand-tuning.
- **[Compositional AI Beyond LLMs](/en/papers/asplos-2026/compositional-ai-beyond-llms-system-implications-of-neuro-symbolic-probabilistic-architectures)** — a systems-side analysis of neuro-symbolic-probabilistic workloads that names what current AI-systems stacks are not optimizing for.
- **[SuperOffload](/en/papers/asplos-2026/superoffload-unleashing-the-power-of-large-scale-llm-training-on-superchips)** — first credible LLM-training offload design that exploits coherent CPU↔GPU memory on superchips rather than fighting PCIe.

## Stats

- Papers summarized: **152 / 152**
- Categories: **8**
- Largest category: compilers-languages-verification and hardware-and-infrastructure (34 each)
- Smallest: llm-training (8)
- Tags used: 33 (added `quantum` this cycle)
