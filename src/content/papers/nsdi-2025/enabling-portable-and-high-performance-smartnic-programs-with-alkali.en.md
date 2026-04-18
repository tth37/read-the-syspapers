---
title: "Enabling Portable and High-Performance SmartNIC Programs with Alkali"
oneline: "Alkali compiles one single-threaded SmartNIC program into pipelined target code, automatically choosing cuts, replicas, and state placement across heterogeneous NICs."
authors:
  - "Jiaxin Lin"
  - "Zhiyuan Guo"
  - "Mihir Shah"
  - "Tao Ji"
  - "Yiying Zhang"
  - "Daehyeok Kim"
  - "Aditya Akella"
affiliations:
  - "UT Austin"
  - "UCSD"
  - "NVIDIA"
  - "Microsoft"
conference: nsdi-2025
tags:
  - smartnic
  - compilers
  - hardware
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Alkali argues that SmartNIC programmers should not have to manually rewrite the same logic for every DPU, FPGA NIC, or ASIC-like NIC. Its answer is a NIC-specific IR, `αIR`, plus an iterative optimizer that cuts a single-threaded program into pipeline stages, decides which stages can be replicated safely, and places state into the right memory tier for the target device. Across four very different NIC architectures, the generated code stays within 9.8% of expert-tuned implementations.

## Problem

The paper starts from a practical pain point: SmartNIC programming today is both architecture-specific and performance-sensitive. Vendors expose low-level SDKs or languages that are tightly coupled to their hardware, such as Agilio’s Micro-C, BlueField’s DOCA stack, or HDL for FPGA NICs. Even after a developer gets one version working, porting it to another NIC means translating primitives, rethinking pipeline structure, changing replication counts, and re-placing state into a different memory hierarchy.

The FlexTOE example makes the issue concrete. A non-pipelined version performs best on BlueField-2, while a three-stage pipelined version performs best on Agilio and the FPGA target. Replication counts also matter, and state placement can change throughput by more than 8x. Existing frameworks such as Floem, ClickNP, or P4-based toolchains help within one architectural family, but they do not give developers a reusable compilation stack that automatically adapts the same program across heterogeneous SmartNICs. The stakes are high because datacenter operators increasingly swap NIC vendors and generations as workloads evolve.

## Key Insight

Alkali’s key claim is that SmartNIC heterogeneity is real, but the structure of SmartNIC programs is much more regular than the hardware interfaces suggest. Across these devices, the paper argues that most programs can be expressed with two kinds of parallelism, pipeline and data parallelism, and three kinds of state, local values, persistent tables, and context state passed between stages. If the compiler captures those common semantics directly, it can delay hardware-specific decisions until optimization and backend code generation.

That is why the paper introduces the stateful handler graph in `αIR`. A handler represents code that runs on one compute unit; edges between handlers represent pipelined event flow; replica counts capture data parallelism; and explicit state objects expose what may be partitioned or shared. Once the program is in that form, the compiler can search for a parallelization plan instead of forcing the programmer to hand-design one.

## Design

The frontend takes a subset of C plus an architecture specification header that defines the hardware events a target NIC supports. Developers write a single-threaded, run-to-completion packet handler. Alkali lowers that code into SSA-based `αIR`, where handlers, event controllers, and program state become explicit.

The optimization loop has two phases. First, the mapping engine decides how many replicas each handler should have and where each persistent table or context object should live in the memory hierarchy. It encodes the decision as an SMT problem constrained by compute-unit counts, memory capacities, access scope, and state-correctness rules. Replication is only allowed when state can be partitioned safely, for example when all accesses to a mutable table use the same key and the event controller can steer that key to a single replica. The performance model is deliberately simple: per-handler throughput depends on instruction time, memory latency, and inter-stage communication cost, all derived from a small vendor-supplied performance specification.

Second, the cut engine takes the current bottleneck handler and tries to split it into two stages. It builds a flow network from SSA statements and data dependencies, then applies a weighted balanced min-cut algorithm. The weights correspond to three ways pipelining can help: shrinking handler state so it fits into faster memory, reducing instructions per stage, or separating persistent tables with different keys so later iterations can replicate the resulting stages. To preserve correctness, Alkali introduces UNCUT nodes that prevent a table lookup from being separated from the update sequence that must stay consistent.

After the mapping-then-cut loop finishes, Alkali applies smaller optimizations such as common-subexpression elimination, event-controller generation, context conversion, and context-memory reuse. The prototype emits code for Agilio, BlueField-2, Alveo FPGA NICs, and PANIC’s RISC-V-based prototype NIC.

## Evaluation

The evaluation covers five applications: L2 forwarding, FlexTOE transport RX, an NF chain, RPC message reassembly, and JSQ RSS. A first useful result is programmability: the Alkali versions are 5x to 10x smaller than the baseline vendor-specific implementations, and the same Alkali-C source compiles across all targets without source changes.

Performance is strongest when the application’s state can be partitioned and the hardware offers enough useful parallelism. L2 forwarding reaches line rate everywhere. FlexTOE also reaches line rate on all evaluated targets except PANIC, where the low-frequency RISC-V cores become the bottleneck. The NF chain reaches line rate on the FPGA and Agilio. Message reassembly is slower on Agilio, BlueField-2, and PANIC because copying payloads into the aggregation buffer is inherently expensive on those SoC-style paths. JSQ RSS is limited on several targets because its table lookup and update use different keys, which blocks safe replication.

Against hand-tuned baselines, Alkali is credible rather than perfect. On Agilio, its FlexTOE code stays within about 10% of the expert implementation. On FPGA, the generated JSQ RSS matches Ringleader’s throughput, though it pays 30% higher latency and 18% higher LUT usage because the backend inserts conservative registers to meet timing. On BlueField-2, expert-written message reassembly and JSQ RSS code outperform Alkali by only 0.6% to 9.8%, despite the expert spending about 14 hours tuning target-specific versions.

The compiler-side evaluation is also important. The iterative mapping-then-cut search finds better plans over time and converges after only a few stage additions. On a reduced Agilio search space, the mapping engine finds the second-best replication plan, only 8.4% below brute-force best. Its state-placement logic beats naive "all in EMEM" or "all in CLS" placements by 1.32x to 6x.

## Novelty & Impact

The novelty is not a new SmartNIC hardware primitive. It is the combination of a reusable IR for stateful NIC execution and an optimization loop that jointly reasons about pipelining, replication, and memory placement across multiple SmartNIC classes. Prior systems usually give one of those pieces for one target family. Alkali packages them into a portable compiler architecture.

That matters for teams building NIC-resident transports, network functions, storage offloads, or request schedulers on hardware that changes faster than application logic. If vendors are willing to expose the modest architecture and performance specifications Alkali needs, the framework reduces both vendor lock-in and the amount of manual retuning required when moving across NIC generations.

## Limitations

The paper is explicit that Alkali is not a globally optimal auto-tuner. Its performance model is intentionally simple and omits effects such as fine-grained contention, richer cache behavior, and out-of-order execution. The frontend also supports only a subset of C, with no unbounded loops, pointer-heavy code, or concurrency primitives.

More importantly, Alkali currently avoids locks. It replicates handlers only when mutable state can be partitioned safely by key, which excludes some programs with inherently shared state. Workload awareness is also weak: developers must annotate branch probabilities or replication limits ahead of time, and the system does not adapt automatically when traffic shifts at runtime. Finally, some remaining gaps to expert code come from backend-specific tricks Alkali does not yet know, such as BlueField-specific buffer reuse or more aggressive FPGA timing optimization.

## Related Work

- _Phothilimthana et al. (OSDI '18)_ — Floem provides a programming system for NIC-accelerated applications, but its compiler structure and optimization assumptions are tied to on-path SoC NICs rather than a heterogeneous SmartNIC fleet.
- _Li et al. (SIGCOMM '16)_ — ClickNP raises the abstraction level for FPGA NIC packet processing, whereas Alkali tries to keep one optimization framework across FPGA, DPU, SoC, and ASIC-like NIC targets.
- _Qiu et al. (SOSP '21)_ — Clara predicts SmartNIC offloading performance on SoC NICs, complementing Alkali’s simpler cross-target model but not replacing its code transformation and automatic parallelization.
- _Xing et al. (SIGCOMM '23)_ — Pipeleon optimizes P4 packet processing on SmartNICs, while Alkali targets richer C-like stateful programs and jointly searches stage cuts, replication, and memory placement.

## My Notes

<!-- empty; left for the human reader -->
