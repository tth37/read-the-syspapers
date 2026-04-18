---
title: "Chips Need DIP: Time-Proportional Per-Instruction Cycle Stacks at Dispatch"
oneline: "DIP samples dispatch slots rather than tagged uops, producing time-proportional dispatch cycle stacks that expose pipeline-ingress bottlenecks conventional profilers miss."
authors:
  - "Silvio Campelo de Santana"
  - "Joseph Rogers"
  - "Lieven Eeckhout"
  - "Magnus Jahre"
affiliations:
  - "Norwegian University of Science and Technology, Trondheim, Norway"
  - "Ghent University, Ghent, Belgium"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790139"
tags:
  - hardware
  - observability
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper argues that instruction-level performance analysis needs a second view besides commit-time cycle stacks. Its mechanism, DIP, samples dispatch slots and attributes each sampled slot to the uop currently exposing dispatch latency, yielding time-proportional `PICS_D` that explain pipeline ingress bottlenecks. On SPEC CPU2017, DIP cuts average dispatch-profile error from `26.9%` for conventional dispatch tagging to `5.2%`, and the resulting `PICS_D` help find a `fotonik3d` optimization worth `8.5%`.

## Problem

The motivation is straightforward but important: even in an accelerator-heavy world, single-thread CPU performance still matters because whatever code cannot be offloaded grows in relative importance. Developers therefore need instruction-level profiles that identify which static instructions actually dominate time and why. Existing work such as TEA gives accurate per-instruction cycle stacks at commit, which the paper calls `PICS_C`.

The problem is that commit only shows how instructions leave the out-of-order window. That is enough for egress bottlenecks such as long-latency loads blocking the reorder buffer, but it misses many ingress bottlenecks that prevent useful uops from entering the window in the first place. Branch mispredictions, front-end bubbles, serialization, and back-end resource stalls can all manifest as dispatch latency concentrated on specific instructions even when commit-side profiles point somewhere else.

State-of-the-art dispatch-tagging profilers such as AMD IBS, Arm SPE, and IBM RIS do not solve this. They tag one uop at dispatch and later report its events, but that policy is not time-proportional at dispatch for two reasons: one sampled cycle may expose multiple dispatch slots at once, and samples that land on misspeculated uops are typically discarded. The result is systematic bias, especially for control-flow-heavy code. The paper's claim is that accurate instruction-level optimization requires both `PICS_D` and `PICS_C`, so the missing piece is a dispatch-time profiler that is time-proportional rather than merely dispatch-triggered.

## Key Insight

The core proposition is that dispatch latency can be profiled with the same time-proportional principle previously used for execution time, provided attribution happens at the granularity of dispatch slots instead of individual tagged uops. In any sampled cycle, the profiler should attribute each dispatch slot to the uop whose latency that slot is currently exposing.

That becomes practical because every dispatch slot falls into one of four fundamental states: `Base` for unavoidable correct-path dispatch, `Stall` for correct-path uops blocked by back-end resources, `Front-End` for empty slots caused by supply-side disruption, and `Misspeculation` for slots consumed by wrong-path work or by the refill after a flush. Once the profiler classifies slots this way, it can both assign time proportionally and explain why the lost dispatch bandwidth occurred. This is the paper's real conceptual move: dispatch profiling should explain ingress the way commit profiling explains egress, not merely collect events from a sampled instruction.

## Design

The paper first defines a BOOM-specific golden reference for `PICS_D`. It attributes all dispatch slots in all cycles to the responsible uops, including partial cycles when some slots dispatch while later slots stall. That reference is too expensive to implement directly, but it provides ground truth and, more importantly, clarifies the exact attribution rule DIP must approximate with sampling.

DIP itself sits in the PMU and tracks sampled dispatch slots until they either commit or get squashed. Its main structure is a Dispatch Information Table (`DIT`) with one entry per dispatch slot. Each entry records the slot state, a multi-hot encoded cause, the ROB index of the tracked uop, and the static instruction address. A small Last Misspeculation Record remembers the latest flush-causing instruction so slots observed during a refill can still be charged to the branch, exception, or serializing instruction that created the bubble.

This design lets DIP recover the attribution policies the golden reference needs. A stalled slot is charged to the oldest not-yet-dispatching uop and labeled with causes such as full ROB, full issue buffer, full load/store queue, rename stall, or serialization. An empty slot caused by the front-end is charged to the next uop to dispatch, with causes such as I-cache or I-TLB miss or a generic front-end bubble. Wrong-path slots and refill slots are charged to the misspeculating instruction. Because the accounting is per slot, DIP handles dispatch parallelism correctly, which is exactly what dispatch tagging misses.

The hardware cost is intentionally small. For the evaluated 4-wide BOOM, the paper reports less than `49 bytes` of extra storage, `0.065 mm^2` area, and about `1.08%` runtime overhead at a `4 kHz` sampling rate, with the data exposed through a read-only CSR and post-processed into visual `PICS_D`.

## Evaluation

The evaluation uses FireSim with a 4-wide BOOM core and 22 SPEC CPU2017 benchmarks, each traced for the first `150` billion cycles. The comparison is against three profiles: conventional dispatch tagging (`DT`), an improved variant that retroactively accounts for misspeculation (`DT-M`), and DIP. Accuracy is measured with profile error relative to the golden-reference `PICS_D`.

The headline result is strong. DIP reaches `5.2%` average profile error, versus `26.9%` for `DT` and `16.8%` for `DT-M`; even DIP's worst case is `20.9%` on `gcc`, while `DT` peaks at `55.1%`. The qualitative figures matter as much as the averages. On `gcc` and `deepsjeng`, DIP recovers essentially the same hottest instructions and component breakdowns as the golden reference, whereas `DT` misses control-flow-heavy hot spots and `DT-M` still misattributes refill time after flushes. The sensitivity study also shows that `4 kHz` is a reasonable sweet spot: higher rates reduce random error only gradually while overhead scales roughly linearly.

The broader architectural claim is also well supported. Comparing DIP's `PICS_D` with TEA's `PICS_C`, the authors find that `18` of `22` SPEC benchmarks show simultaneous ingress and egress issues. In other words, needing both views is the rule rather than the exception. The `fotonik3d` case study is especially persuasive: `PICS_D` points to a load instruction whose dispatch cost comes from repeated memory-ordering exceptions caused by an avoidable spill/reload sequence near a branch target, while `PICS_C` mainly highlights unrelated cache-missing floating-point loads. Rewriting that sequence removes the worst ingress issue and improves performance by `8.5%`. That is exactly the kind of missed optimization opportunity the paper says commit-only analysis leaves behind.

## Novelty & Impact

Relative to _Dean et al. (MICRO '97)_ and later commercial dispatch-tagging facilities, the novelty is not that the paper samples at dispatch, but that it makes dispatch profiling time-proportional and therefore trustworthy as an instruction-level attribution method. Relative to _Gottschall et al. (MICRO '21)_ and _Gottschall et al. (ISCA '23)_, the contribution is to extend the same philosophy from commit-time execution and events to dispatch-time ingress.

That makes the paper valuable to both microarchitectural tooling researchers and practitioners doing last-mile CPU tuning. It contributes a new measurement mechanism, a cleaner way to think about ingress versus egress bottlenecks, and concrete evidence that commit-side profiles alone are often incomplete.

## Limitations

DIP is implemented and validated on BOOM inside FireSim, not on commercial silicon, so the exact cause taxonomy and storage costs are architecture-specific. The paper argues the mechanism scales to wider cores and features such as fusion or replay, but that remains an engineering argument rather than a demonstrated deployment.

The method also does not replace commit-side profiling. DIP reveals ingress bottlenecks, but the paper itself shows that egress bottlenecks still require `PICS_C`. Finally, because DIP is a sampling profiler, colder instructions still converge slowly; the paper's own `gcc` result shows that unbiased profiling can still have noticeable random error when hotness is spread across tens of thousands of static instructions.

## Related Work

- _Dean et al. (MICRO '97)_ - ProfileMe adds hardware support for instruction-level profiling, whereas DIP focuses specifically on time-proportional attribution of dispatch latency in out-of-order cores.
- _Gottschall et al. (MICRO '21)_ - TIP makes instruction profiling time-proportional at commit; DIP generalizes that principle to dispatch-time latency.
- _Gottschall et al. (ISCA '23)_ - TEA provides accurate `PICS_C`, and this paper argues TEA's commit-side view must be paired with `PICS_D` to see both ingress and egress.
- _Eyerman et al. (ISPASS '18)_ - Multi-Stage CPI Stacks distinguish pipeline stages at application scope, while DIP attributes ingress costs to specific static instructions.

## My Notes

<!-- empty; left for the human reader -->
