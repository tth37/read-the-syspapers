---
title: "When P4 Meets Run-to-completion Architecture"
oneline: "P4RTC adapts P4 to run-to-completion ASICs with background pipelines, in-dataplane table updates, and load-aware compilation, enabling 50M-flow monitoring near line rate."
authors:
  - "Hao Zheng"
  - "Xin Yan"
  - "Wenbo Li"
  - "Jiaqi Zheng"
  - "Xiaoliang Wang"
  - "Qingqing Zhao"
  - "Luyou He"
  - "Xiaofei Lai"
  - "Feng Gao"
  - "Fuguang Huang"
  - "Wanchun Dou"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University, China"
  - "Huawei, China"
conference: nsdi-2025
tags:
  - networking
  - smartnic
  - compilers
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`P4RTC` asks what happens if `P4` targets a high-speed run-to-completion (RTC) ASIC instead of a fixed pipeline switch. The answer is a new RTC-oriented architecture model, externs for background work and in-data-plane table mutation, an RTC-aware compiler, and a SystemC performance model. On a 1.2 Tbps Huawei chip, the stack enables exact 50M-flow monitoring near line rate, cuts development effort sharply versus microcode, and helps tune one program from 39.4 to 569.5 Mpps.

## Problem

The paper starts from a structural limitation of today's P4 ecosystem: the language is portable, but the dominant hardware model is still the pipeline ASIC. That model gives deterministic high throughput by forcing packets through a fixed set of stages with isolated memories. The cost is programmability. Some operations are awkward or impossible unless the design uses recirculation, approximations, or heavy compromises. The paper's motivating example is "update the minimum among several counters": on a pipeline chip, once the packet has moved past the stage that holds the current minimum, revisiting it is difficult without another trip through the pipeline.

The obvious fallback is to use RTC hardware directly, because RTC devices can execute longer logic and access shared memory repeatedly. But existing high-speed RTC platforms are programmed with proprietary C-like or microcode-level interfaces that expose hardware details and make porting research ideas hard. Existing P4 adaptations for CPUs do not solve this, because they do not target specialized Tbps-class RTC packet processors. The real problem, then, is not just "P4 is too restrictive" or "RTC is hard to program." It is the absence of a public abstraction layer that brings P4's programming model to RTC hardware without throwing away the hardware's flexibility.

## Key Insight

The core claim is that P4's stable core language does not need to change if the target-specific architecture model changes. `P4RTC` keeps the familiar parser / ingress / egress / deparser structure, but reinterprets it as a logical per-core pipeline running on many RTC cores rather than as a sequence of physical stages. Once that shift is made, the architecture-specific layer can expose the missing RTC capabilities as externs and annotations instead of as new core syntax.

That insight has a second half: flexibility is only useful if the compiler and developer can reason about performance. RTC hardware removes stage-length limits, but it introduces shared-resource contention across cores, memories, and table-search engines. So the paper treats "P4 for RTC" as a full-stack problem: language abstractions, a compiler that places tables and lowers code to microcode safely, and a performance model that predicts when a legal program will still run badly.

## Design

`P4RTC` introduces a new architecture model in which packets are dispatched to idle cores, each core runs a logical P4 pipeline, and shared on-chip or off-chip memory can be accessed multiple times during one packet's processing. The model preserves familiar P4 programmable blocks, but differs from pipeline switches in three important ways: it is many-core rather than single-pipeline, it has effectively unlimited logical length because a core runs microcode rather than traversing fixed stages, and it relies on a shared memory subsystem rather than per-stage isolated memories.

To expose that flexibility, the paper adds several RTC-specific externs. `Foreach` lets a background pipeline iterate over table entries without adding a new `for` syntax to `P4`. `Sleep` controls background-core activation frequency. `Queue<T>` provides parallel-safe communication between foreground and background pipelines, which the authors use to hand finished-flow notifications from packet processing to a background aging path. `TableOperation` allows entry insertion, deletion, and lookup directly in the data plane for both on-chip and off-chip tables. The paper also adds `lastRowIndex()` so code can attach counters or locks to the exact table row just touched, plus a `Lock` extern to serialize read-modify-write sequences that would otherwise race across cores.

Table design is also extended. Tables may be on-chip or off-chip, exact/LPM content-addressed (`CAT`) or linear-addressed (`LAT`), and can be annotated with directives such as `@linear` and `@offchip(x4)`. The hardware can fragment a table across multiple banks, which improves both capacity usage and load balance but consumes limited address-mapping entries in the table-search engines. The compiler therefore solves table deployment as an ILP: it places table fragments so each table fits, bank capacities are obeyed, mapping-entry limits are respected, and the maximum bank load is minimized. Because actual table loads depend on workload, the compiler layers on profile-guided optimization (PGO), re-profiling after deployment and re-solving when the traffic mix changes.

On code generation, the authors reuse `P4C` but replace the backend. Their main compiler lesson is to lower `P4` IR into an intermediate `Microcode IR` before emitting final instructions. That middle IR lets the compiler represent RTC-specific control flow, such as the loop structure behind `Foreach`, while still checking dependencies, ordering, and target constraints. Separately, the performance model uses SystemC to simulate cores, the traffic manager, table-search engines, memory subsystem, queues, and back-pressure. It does not execute the real function of each packet; instead, it replays probabilistic microcode paths derived from a functional run and estimates throughput, latency, and component utilization under a given workload.

## Evaluation

The prototype runs on a Huawei NetEngine 8000 F1A-C router chip with 1.2 Tbps bandwidth and 8 GB HBM. The first case study shows what the extra programmability buys. The authors build exact per-flow monitoring with an off-chip flow-measurement table, in-data-plane table insertion, and a background aging/reporting pipeline. With 4 GB of memory, the system tracks up to 50 million concurrent flows and runs near line rate. Compared with `TurboFlow`, a Tofino-based design that evicts old records on hash conflict, `P4RTC` cuts report bandwidth overhead by 86% to 90%. Even the failed-packet traffic from row-lock contention during simultaneous flow creation stays below 0.2% of the input traffic.

The second case study asks whether P4 actually lowers RTC development burden. Across five projects, including accurate flow monitoring, `SpaceSaving`, `CocoSketch`, AES encryption, and `ONTAS`, the P4 versions use 4.6x to 7.7x fewer lines of code than microcode implementations. For three prior P4 designs (`CocoSketch`, `ONTAS`, and AES encryption), migrating to `P4RTC` requires changing only 4.3% to 13.0% of the code, mostly to replace architecture-specific externs. That is solid evidence that the authors are not merely proposing a different vendor SDK; they are making existing P4 work easier to reuse on RTC hardware.

The third case study validates the performance model. Starting from a baseline program that achieves only 39.4 Mpps in the model and 38.3 Mpps on hardware, the authors first rebalance table fragments across banks (283.9 vs. 279.4 Mpps), then rebalance table-search-engine bindings (392.7 vs. 401.9 Mpps), and finally cache hot table entries on-chip (569.5 vs. 561.0 Mpps). The overall error stays below 3%, which is enough for the optimization workflow the paper claims. The evaluation supports the central thesis well, though it is still case-oriented and tied to one vendor chip rather than a broad cross-platform study.

## Novelty & Impact

The novelty is not one isolated extern or one compiler trick. The paper contributes a coherent P4 stack for RTC hardware: an architecture model that preserves the P4 programming surface, externs that expose RTC-specific capabilities without changing the core language, a compiler strategy for shared-memory table placement and microcode lowering, and a performance model for tuning code before deployment.

That matters because it offers a concrete path beyond the traditional pipeline-switch assumption that dominates P4 work. If adopted more broadly, `P4RTC` could make post-Tofino programmable dataplanes less dependent on closed microcode tooling and more hospitable to complex functions such as exact monitoring, richer in-network algorithms, and background maintenance tasks. This is a new mechanism and a new framing of what a programmable P4 target can be.

## Limitations

The prototype is still vendor-specific and the paper is candid about that. The hardware is a Huawei RTC chip, support for higher-throughput chips is still ongoing, and `P4 Runtime` integration is only planned. The language design is also not final: the authors note that additional specialized extensions already exist internally and that an open-community discussion is still needed to decide what a clean RTC-targeted P4 surface should look like.

The performance model is useful, but not omniscient. Because it replays probabilistic code paths rather than simulating every detailed interaction, it cannot yet model complex locking behavior or scenarios where packet ordering itself is the critical variable. More broadly, RTC programmability creates new performance hazards. The paper notes that some early applications achieved less than 100 Gbps until developers learned how to avoid bank imbalance, TSE imbalance, or excessive locking. So `P4RTC` expands what can be built, but it does not make RTC hardware easy in the same deterministic way that a fixed pipeline can be.

## Related Work

- _Bosshart et al. (SIGCOMM '13)_ - `RMT` established programmable pipeline switching, while `P4RTC` argues that RTC hardware is needed when stage length and isolated memories become the real bottleneck.
- _Hogan et al. (HotNets '20)_ - `P4ALL` stretches expressiveness within pipeline switches, whereas `P4RTC` changes the target architecture itself and exposes RTC-specific capabilities through externs.
- _Yang et al. (SIGCOMM '22)_ - `Trio` shows a programmable RTC chipset, while `P4RTC` contributes a public P4 architecture model, compiler experience, and performance-modeling methodology for such hardware.
- _Salim et al. (EuroP4 '23)_ - `P4TC` brings P4 to the Linux traffic-control stack, but it retains a pipeline-oriented view instead of the many-core RTC model and in-data-plane table operations of `P4RTC`.

## My Notes

<!-- empty; left for the human reader -->
