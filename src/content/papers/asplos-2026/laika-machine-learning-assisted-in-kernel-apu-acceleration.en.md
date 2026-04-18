---
title: "LAIKA: Machine Learning-Assisted In-Kernel APU Acceleration"
oneline: "Moves in-kernel ML from PCIe-attached dGPUs to an APU iGPU, using tri-domain shared memory and a persistent kernel to cut latency and power."
authors:
  - "Haoming Zhuo"
  - "Dingding Li"
  - "Ronghua Lin"
  - "Yong Tang"
affiliations:
  - "School of Computer Science, South China Normal University, Guangzhou, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790181"
tags:
  - kernel
  - ml-systems
  - gpu
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

LAIKA argues that in-kernel ML is usually limited by data movement, not arithmetic throughput. It therefore replaces PCIe-attached dGPU offload with an APU iGPU, combines a tri-domain shared-memory substrate with a lightweight HIP proxy and a persistent GPU kernel, and reports up to `9.7x` lower inference latency plus substantially lower system power than a LAKE-style dGPU design.

## Problem

The paper starts from a tension that shows up across several lines of "learned OS" work. ML policies can outperform fixed heuristics for scheduling, filesystem prefetching, and I/O management, but putting inference on the CPU creates its own problems: SIMD-heavy code raises context-switch overhead, can trigger frequency throttling, and in Linux often runs in a preemption-unfriendly environment. User-space control loops avoid putting ML runtimes into the kernel, but they add syscall, context-switch, and data-movement overhead that is hard to justify for event-driven kernel paths.

LAKE, the closest predecessor, tries to solve this by forwarding kernel requests to a user-space proxy and then to an NVIDIA dGPU. LAIKA's key empirical observation is that this path is dominated by data logistics rather than GPU compute. In the paper's MLLB profiling, the kernel-to-user copy, PCIe transfers, and return path consume more than `93%` of end-to-end latency, leaving the dGPU compute kernel active for only `7%` of the total time. That means the dGPU only becomes worthwhile at relatively large batches, often above `256`, whereas many kernel decisions are inherently small-batch or even one-event-at-a-time. The practical problem is therefore not "how do we expose a GPU to the kernel?" but "how do we accelerate small, latency-sensitive kernel inference without paying a round-trip I/O tax that overwhelms the useful work?"

## Key Insight

The central claim is that for this workload class, unified memory matters more than peak FLOPs. An integrated GPU on an APU is weaker than a laptop or desktop dGPU in raw compute terms, but it shares DRAM with the CPU and can therefore avoid the three-domain copy chain that sinks dGPU offload. If the system can present one shared region to the kernel, user space, and the iGPU, then the dominant cost in LAKE disappears.

That insight only pays off if the control path is redesigned as well. LAIKA separates a zero-copy data plane from a lightweight control plane. A small proxy process is still needed because HIP remains a user-space runtime, but the proxy now mostly relays commands rather than shuttling payloads. For the smallest jobs, LAIKA goes further and avoids repeated launches altogether through a persistent GPU kernel. The result is a design where the iGPU wins not by computing faster, but by making "do one tiny inference now" cheap enough to fit kernel hot paths.

## Design

LAIKA has four major pieces. `AProxy` bridges privilege domains. Kernel code cannot safely call HIP directly, so the framework forwards requests through a minimal user-space process that translates them into standard AMD HIP runtime calls. The point is not to bypass the existing ROCm stack, but to reuse it without modifying vendor drivers.

`AShm` is the main architectural contribution. At boot, LAIKA allocates a physically contiguous memory pool with `dma_alloc_coherent`, then registers that region with HIP so the same underlying pages are mapped into kernel space, user space, and the iGPU. Features and results live in this shared pool, which turns data exchange into address sharing rather than copying.

The execution engine then offers two iGPU modes. In the Per-Launch path, the kernel dispatcher forwards a request to `AProxy`, which launches a conventional GPU kernel that reads inputs and writes outputs directly in `AShm`. The paper says the control-path round trip is about `10 us`, which is acceptable once batches are no longer tiny. For latency-sensitive cases, LAIKA uses `APK`, an APU Persistent Kernel that stays resident on the iGPU, polls an `AShm` task queue, executes requests in place, and updates completion state in memory. This removes both repeated API remoting and repeated launch overheads.

Because no single backend wins everywhere, LAIKA adds an in-kernel dispatcher with a lightweight cost model. It estimates latency for three options: CPU-local execution, persistent-kernel iGPU execution, and per-launch iGPU execution. Small jobs stay on the CPU, small-to-moderate batches use `APK`, and large batches switch back to the Per-Launch path once synchronization overhead inside the persistent kernel starts to dominate.

## Evaluation

The evaluation uses an AMD Ryzen 7 8845HS APU with a Radeon 780M iGPU, and compares against LAKE on two NVIDIA dGPUs: an RTX 4060 Laptop GPU and an RTX 4090 desktop GPU. The workload suite is well chosen for the paper's thesis: LinnOS-style I/O latency prediction, MLLB load balancing, KML-style filesystem prefetching, and AES-GCM filesystem encryption to show the substrate is not limited to neural inference.

The most direct evidence comes from the low-batch latency studies. For MLLB, LAIKA is consistently `3x-5x` faster than the optimized dGPU baseline and lowers the batch size at which GPU acceleration becomes worthwhile from `128` to `32`. For filesystem prefetching, the paper reports up to `9.67x` lower latency than the dGPU solution in the iGPU sweet spot. For I/O latency prediction, the story is more nuanced: LAIKA wins for the smaller baseline model, but the advantage narrows as the authors deepen the network by `8.8x` and `16.5x` MACs. That result is important because it supports the paper's main claim while also exposing its boundary condition: once the workload becomes compute-bound rather than I/O-bound, the dGPU's raw throughput matters again.

The system-level experiments strengthen the argument. Under host-side DRAM contention, all backends slow down, but the persistent-kernel iGPU path degrades least; even at `100%` contention, LAIKA still beats the dGPU by `3.5x` at small batches (`7 us` vs. `26 us`) and `2.9x` at large batches (`26 us` vs. `83 us`). The power results are also striking. In periodic-inference experiments, total system power with the iGPU is only `28.9%-39.5%` of the dGPU baseline, and the power attributable to inference itself is just `6.8%-27.3%` of the dGPU case. Overall, the evaluation supports the paper's central claim for the small and moderate batches that dominate kernel control paths, while clearly showing that LAIKA is not a universal replacement for faster discrete accelerators.

## Novelty & Impact

Relative to _Fingler et al. (ASPLOS '23)_, LAIKA's novelty is not merely "HIP instead of CUDA." The substantive move is to retarget in-kernel ML acceleration from a remote-memory dGPU architecture to a unified-memory APU architecture, then rebuild the software stack around that choice with tri-domain zero-copy sharing and a persistent-kernel fast path. Relative to _Chen et al. (APSys '20)_ and _Hao et al. (OSDI '20)_, which show why learned kernel policies are useful, LAIKA asks what hardware/software substrate makes those policies viable at microsecond-scale decision points.

That makes the paper useful to two audiences. Systems researchers working on learned OS policies can cite it as a concrete answer to the deployment question, while kernel and platform engineers can read it as an argument that APUs are not just "smaller GPUs," but a distinct design point for low-latency kernel assistance.

## Limitations

The paper is careful enough to reveal several limits. First, LAIKA's advantage is workload-dependent: deeper models and larger batches progressively favor dGPUs, so the design is strongest when inference is small-batch and latency-sensitive. Second, the dispatcher relies on offline profiling thresholds for a given APU and model, which raises portability and retuning costs. Third, the prototype is AMD-specific because it depends on ROCm/HIP and on the practical openness of AMD's software stack; the discussion explicitly says Intel and Apple platforms are not yet equally ready for this style of kernel integration.

There are also reviewer-style concerns. Because CPU and iGPU share DRAM channels, memory contention does not disappear; it just hurts LAIKA less than it hurts the alternatives in the evaluated setup. More importantly, the trust model assumes a benign `AProxy`. The paper acknowledges that a compromised proxy could inject bogus results or launch denial-of-service attacks, and leaves stronger validation and fail-safe handling to future work.

## Related Work

- _Fingler et al. (ASPLOS '23)_ — LAKE established API-remoted in-kernel ML acceleration on NVIDIA dGPUs; LAIKA keeps the remoting idea but removes the PCIe copy chain by targeting unified-memory APUs.
- _Chen et al. (APSys '20)_ — MLLB shows that learned load balancing can beat Linux's heuristic scheduler; LAIKA uses that style of workload to argue that deployment overhead is now the real bottleneck.
- _Hao et al. (OSDI '20)_ — LinnOS demonstrates value from per-I/O latency prediction, while LAIKA contributes a lower-latency execution substrate for running that kind of model inside the kernel.
- _Akgun et al. (HotStorage '21)_ — KML applies in-kernel neural prediction to filesystem readahead; LAIKA is complementary because it accelerates the inference path rather than proposing a new readahead policy.

## My Notes

<!-- empty; left for the human reader -->
