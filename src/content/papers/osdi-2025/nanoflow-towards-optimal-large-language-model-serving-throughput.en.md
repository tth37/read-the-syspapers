---
title: "NanoFlow: Towards Optimal Large Language Model Serving Throughput"
oneline: "NanoFlow splits LLM serving into auto-searched nano-batches so compute, memory, and network kernels overlap inside each GPU instead of stalling one another."
authors:
  - "Kan Zhu"
  - "Yufei Gao"
  - "Yilong Zhao"
  - "Liangyu Zhao"
  - "Gefei Zuo"
  - "Yile Gu"
  - "Dedong Xie"
  - "Tian Tang"
  - "Qinyu Xu"
  - "Zihao Ye"
  - "Keisuke Kamahori"
  - "Chien-Yu Lin"
  - "Ziren Wang"
  - "Stephanie Wang"
  - "Arvind Krishnamurthy"
  - "Baris Kasikci"
affiliations:
  - "University of Washington"
  - "Tsinghua University"
  - "UC Berkeley"
  - "University of Michigan"
conference: osdi-2025
tags:
  - llm-inference
  - gpu
  - scheduling
  - caching
category: llm-systems
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

NanoFlow argues that modern multi-GPU LLM serving is usually compute-bound end to end, even though decode attention is memory-heavy and tensor parallelism adds communication. It therefore splits each iteration into smaller nano-batches and overlaps compute-, memory-, and network-bound kernels from different nano-batches on the same GPU. On LLaMA-2-70B over 8xA100, that lifts throughput well above current serving engines and reaches 68.5% of the paper's derived optimum.

## Problem

The paper targets high-volume online LLM serving, where throughput directly determines cost and the number of scarce GPUs needed to sustain demand. Prior systems largely optimize the obvious pain points: model weights are huge, KV caches are huge, and decode attention repeatedly reads request-specific state, so the common story is that serving is fundamentally memory-bound. That story motivates designs centered on memory management, chunked prefills, and batching policies.

NanoFlow's starting point is that this story is incomplete once one looks at an entire serving iteration rather than a single kernel. In realistic deployments, dense transformer operations such as KQV projection and FFN GEMMs run on large mixed batches of prefill and decode tokens, so weight loading is amortized and those kernels become compute-bound. Network collectives from tensor parallelism and decode attention still matter, but they are not usually the global bottleneck on modern accelerators with NVLink-class interconnects. The paper's cost model and measurements on LLaMA-2-70B show that current engines still use only about 40% of available compute, not because each kernel is inefficient, but because compute-bound, memory-bound, and network-bound stages are run sequentially inside the device.

That sequential structure creates long bubbles. A decode-attention kernel may use memory bandwidth well, and an all-gather may use the interconnect well, yet both leave tensor cores underused while they run. The practical consequence is that popular engines such as vLLM, DeepSpeed-FastGen, and TensorRT-LLM land far below the throughput the hardware should allow. The problem NanoFlow solves is therefore not "make one kernel faster," but "keep the globally bottlenecked resource busy across the whole pipeline."

## Key Insight

The paper's central claim is that, in the common compute-bound regime, it is rational to do a little more work per request if that extra work exposes more overlap and raises overall compute utilization. NanoFlow implements that idea by splitting each large serving batch into smaller nano-batches and duplicating the original operations into nano-operations. Because different nano-batches are independent, a compute-heavy GEMM from one nano-batch can run at the same time as a memory-heavy decode attention or a network collective from another.

This is a deliberate tradeoff. Nano-batching reduces the batching effect and reloads some weights more often, which would look wasteful if memory traffic were the dominant constraint. But if compute is the true bottleneck, then the right objective is to maximize utilization of compute while hiding the extra memory and network work behind it. The paper therefore reframes serving optimization from "minimize the cost of every stage" to "maximize usage of the resource that limits throughput for the whole workload."

## Design

NanoFlow begins with an analytical model of serving cost. It classifies dense projections and FFN layers as mostly compute-bound, decode attention as memory-bound, and tensor-parallel collectives as network-bound. Under the maximum feasible dense batch size, it derives simple latency estimates for memory, compute, and network time, then shows that modern models with GQA and large dense batches typically fall into a compute-bound regime. The authors validate that result empirically on LLaMA-2-70B with 8 A100 GPUs: per-operation timings mostly align with the model, and aggregate compute time dominates memory and network time.

The core mechanism is nano-batching. A parent operation over a dense batch is split into two or more nano-operations over disjoint token ranges. Dependencies remain only when the original parent operations depend on each other and the token ranges overlap. This creates new scheduling freedom: NanoFlow can overlap different resource types inside one device instead of waiting for one full-batch stage to finish before starting the next. For 70B-class models, the generated schedule often uses four nano-operations around KQV and decode-attention, where compute, memory, and network pressure coincide, then two nano-operations later in the layer where the pipeline is simpler.

Finding that schedule is the paper's main systems contribution. NanoFlow uses a two-stage MILP-based auto-search. Stage I searches for the number, sizes, and ordering of nano-operations assuming no interference, with constraints on dependency preservation, allowed overlap, and equivalent collective transformations such as replacing an all-gather with an all-reduce-based formulation. Stage II keeps that structure fixed and re-optimizes resource allocation using measured kernel interference. Because GPUs do not expose direct fractional controls for compute, memory, and network bandwidth, NanoFlow uses compute-kernel slowdown as a proxy resource share `R`, profiles pairwise overlap between GEMM, GEMV, and network kernels, and converts each chosen `R` into a predicted realized performance `P`. This lets the search reason about non-linear overlap tradeoffs without exhaustively exploring all kernel combinations.

The runtime then executes the chosen pipeline across CUDA streams. It maintains a fixed dense token batch, prioritizes unfinished decode requests, and fills remaining capacity with chunked prefills. CPU-side batch formation is done asynchronously one iteration ahead so the GPU does not idle waiting for scheduler work. For multi-round conversations, NanoFlow also offloads freshly produced KV vectors immediately after KQV generation into a host/SSD hierarchy, later reloading them into a contiguous GPU staging area and scattering them into the paged KV layout.

## Evaluation

The main evaluation uses LLaMA-2-70B on one 8xA100 80 GB DGX node with FP16 inference, compared against vLLM, DeepSpeed-FastGen, and TensorRT-LLM. Workloads include fixed-length synthetic settings and traces derived from Splitwise, LMSYS-Chat-1M, and ShareGPT. The paper also evaluates LLaMA-3-70B, LLaMA-3-8B, Qwen2-72B, Deepseek-67B, and Mixtral 8x7B to show the method is not specific to one architecture.

The headline result is throughput. For the trace-driven workloads, NanoFlow averages 4.18x the throughput of vLLM, 3.45x that of DeepSpeed-FastGen, and 1.91x that of TensorRT-LLM, the strongest baseline. In its best LLaMA-2-70B setting, it reaches 1212 tokens/s/GPU versus a derived optimum of 1857 tokens/s/GPU, or 68.5% of optimal. The paper's ablations also make the mechanism plausible rather than magical: nano-batching alone costs 13.2% throughput, but overlapping network-bound work recovers that loss and more, while overlapping both network- and memory-bound work yields a 1.17x gain over a non-overlapping nano-batch baseline. Resource traces show why: compute utilization rises from about 40% in the sequential pipeline to about 68.5% under NanoFlow.

Latency is not ignored. Because NanoFlow keeps a large dense batch to stay throughput-efficient, its low-load latency is slightly worse than the best baseline. But as the request rate rises, it sustains meaningfully more load within the same normalized-latency target. On LMSYS-Chat-1M, for example, it handles 1.64x the request rate of TensorRT-LLM under the paper's 200 ms/token SLO. Near peak load, its 99th-percentile latency is only 1.07x the average, helped by the fixed-batch execution style. For other models, the paper reports NanoFlow-generated pipelines delivering roughly 50% to 72% of the derived optimum.

## Novelty & Impact

Relative to work such as Orca, vLLM, and Sarathi-Serve, NanoFlow moves the optimization granularity inside a serving iteration. Prior systems continuously batch requests, manage KV memory better, or separate prefill and decode scheduling, but they still mostly treat each operation as an indivisible full-batch stage. NanoFlow instead treats the overlap of heterogeneous kernels within one device as the primary optimization target.

That shift is important because it couples a systems argument with a concrete runtime. The paper does not merely claim that serving is often compute-bound; it derives a throughput bound, shows why existing engines miss it, and then produces a search-and-runtime stack that closes much of the gap. Future LLM serving work is likely to cite NanoFlow both for the compute-bound reframing and for the idea that intra-device scheduling can matter as much as cluster-level batching and routing.

## Limitations

NanoFlow depends on the workload really being in the compute-bound regime. The paper's own analysis shows at least one counterexample: long-decode workloads on smaller models can move toward memory-boundedness, where repeated weight loading becomes harder to hide. That means the design is not a universal replacement for memory-centric serving optimizations; it is strongest for large batched models on datacenter GPUs.

The auto-search also depends on profiling assumptions. It models overlap using pairwise interference and assumes the `R`-to-`P` mapping is stable enough to reuse across many shapes. That is a practical simplification, not a proof. If hardware scheduling behavior changes across GPU generations or if workloads shift substantially, NanoFlow must re-profile and re-search. Finally, even after all this machinery, the system still reaches only about two-thirds of the paper's own optimum on the primary setting, so interference, scheduling overheads, and pipeline bubbles remain materially unsolved.

## Related Work

- _Yu et al. (OSDI '22)_ - Orca introduced continuous batching for generative serving, but it schedules at the request/iteration level rather than overlapping heterogeneous kernels within one device.
- _Kwon et al. (SOSP '23)_ - vLLM's PagedAttention makes KV-cache management much more memory-efficient, while NanoFlow accepts the same paged setting and attacks the compute bubbles left by sequential execution.
- _Li et al. (OSDI '23)_ - AlpaServe studies statistical multiplexing and model-parallel serving across requests and replicas; NanoFlow instead optimizes the execution pipeline inside one serving instance.
- _Sheng et al. (ICML '23)_ - FlexGen relies on aggressive offloading to make large-model inference feasible on constrained hardware, whereas NanoFlow assumes datacenter GPUs and focuses on maximum online throughput under abundant demand.

## My Notes

<!-- empty; left for the human reader -->
