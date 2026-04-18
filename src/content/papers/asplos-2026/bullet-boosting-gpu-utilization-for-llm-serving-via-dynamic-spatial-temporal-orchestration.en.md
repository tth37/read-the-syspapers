---
title: "Bullet: Boosting GPU Utilization for LLM Serving via Dynamic Spatial-Temporal Orchestration"
oneline: "Shares one GPU between prefill and decode by dynamically repartitioning SMs with a contention-aware model and layer-level scheduler."
authors:
  - "Zejia Lin"
  - "Hongxin Xu"
  - "Guanyi Chen"
  - "Zhiguang Chen"
  - "Yutong Lu"
  - "Xianwei Zhang"
affiliations:
  - "Sun Yat-sen University, Guangzhou, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790135"
tags:
  - llm-inference
  - gpu
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Bullet argues that the usual chunked-prefill design is leaving GPU capacity on the floor. Instead of forcing prefill and decode into one lock-step hybrid batch, it spatially shares one GPU between them, predicts how each phase slows down under different SM allocations, and repartitions SMs online to keep TTFT and TPOT within SLOs. The result is higher utilization and better end-to-end throughput than chunked-prefill baselines.

## Problem

The paper starts from a hardware-level observation: LLM serving alternates between a compute-heavy prefill phase and a memory-bound decode phase, so a single execution style rarely keeps both Tensor Cores and memory bandwidth busy at the same time. Production systems usually cope with this mismatch using chunked prefill, where prefill work is chopped into chunks and interleaved with decode tokens under a fixed token budget. That does improve decode smoothness, but it introduces a structural tradeoff. Small chunks lower TPOT but waste compute due to wave quantization and repeated KV-cache reloads; large chunks recover throughput but delay TTFT and can create long prefill queues.

The paper’s measurements make this concrete. On Llama-3.1-8B over A100, complete Transformer layers reach only about 70%-76% compute utilization in prefill, and short-sequence kernels suffer especially from wave quantization. Chunked prefill also gets worse as a long request advances: for a 16k prompt split into 1k chunks, compute efficiency drops from 71% to 61% across chunks and the last chunk takes 1.9x as long as the first. That means the standard TTFT-versus-TPOT tradeoff is not merely inconvenient; it is biased by underlying GPU underutilization. The systems question is therefore how to co-run dependent prefill and decode work on the same GPU without giving up predictability.

## Key Insight

Bullet’s key claim is that prefill and decode should not be coordinated through a shared token budget; they should be coordinated through explicit spatial-temporal resource control. Prefill is compute-bound enough, and decode memory-bound enough, that concurrent execution can raise total utilization if the system controls how many SMs each phase gets at each moment. The hard part is not the idea of sharing, but making that sharing predictable enough to satisfy TTFT and TPOT SLOs.

That leads to the paper’s central design choice: model latency as a function of execution state and SM budget, then drive a scheduler that continuously reshapes the GPU partition. Once the system can estimate how prefill and decode slow each other down under different SM splits, it can stop using coarse static partitions or chunk-size heuristics and instead make layer-level decisions about who should get more GPU at each step.

## Design

Bullet has three major components. The first is a performance estimator. The authors define an execution state using prefill sequence length, prefill batch size, prefill SM budget, decode context length, decode batch size, and decode SM budget. Exhaustively profiling that space would be infeasible, so Bullet builds an SM-scaling roofline model, calibrates it with a sparse set of measured co-execution samples, and refines it online. The model explicitly accounts for contention that survives even when kernels are isolated to different SM subsets, especially memory-subsystem interference from decode.

The second component is an SLO-aware scheduler. Prefill and decode each run their own scheduler loop, exchanging status through shared metadata. Prefill is launched in layer-sized steps so the CPU can intervene frequently; decode is issued as a CUDA Graph to avoid overhead on tiny kernels. The policy prioritizes prefill because shorter TTFT enlarges downstream decode batches and thus increases throughput, but it backs off whenever predicted TPOT would violate the decode target. Under bursts, Bullet can temporarily give prefill the full GPU, then quickly move back to a balanced split once the queue is drained.

The third component is the concurrent execution engine. Bullet runs prefill and decode in separate processes, but they share CPU-side metadata and a unified GPU memory pool for model weights and KV cache, so requests can move from prefill to decode without KV migration. For resource control, Bullet avoids heavyweight MPS reconfiguration and instead uses SM masking on CUDA streams via `libsmctrl`, letting it reassign SM subsets with microsecond-scale overhead. This control-path design is what makes the layer-level scheduling practical rather than just a modeling exercise.

## Evaluation

The evaluation is strong because it hits exactly the regime the paper claims to improve: long and bursty serving workloads where chunked prefill causes queueing collapse. On a single A100 serving Llama3.1-8B, Bullet beats SGLang-1024 across ShareGPT, Azure-Code, and arXiv-Summary, delivering 1.09x average throughput and up to 1.20x higher throughput, with a 13.5x average TTFT improvement and 1.86x end-to-end speedup. The paper is careful that TPOT does not improve uniformly against every baseline, but the overall tradeoff still moves in Bullet’s favor because dynamic SM allocation prevents TTFT from exploding.

The ShareGPT tail-latency result is particularly striking. Bullet reports mean TTFT of 0.16 s and P90 TTFT of 0.31 s, which are 54.9x and 78.5x better than SGLang-1024 on that workload. Against SGLang-2048, Bullet improves both sides of the classic chunk-size tradeoff at once: 4.2x lower TTFT and 1.20x better TPOT. The authors attribute this to concurrent prefill-decode execution rather than a better chunk heuristic, which fits the mechanism the paper proposes.

The multi-GPU and cross-model experiments broaden the claim. With Llama3.1-70B on 8xA100, Bullet reaches 173 ms/token on ShareGPT at 3.0 req/s versus 207 for vLLM and 319 for SGLang. On H20 with Qwen3-235B-A22B, Bullet achieves 110 ms/token at 4.0 req/s, with 1.4 s TTFT and 45 ms TPOT, and is comparable to a heavier 3P1D disaggregated deployment. The utilization study also lines up with the thesis: during concurrent operation Bullet sustains 86.2% active SM cycles, 11.2% above SGLang, while Tensor Core and memory-bandwidth utilization rise by 11.8% and 19.3%.

## Novelty & Impact

Relative to _Agrawal et al. (OSDI '24)_, Bullet’s novelty is not another refinement of chunked prefill, but the claim that chunking itself encodes the wrong control surface for this problem. Relative to _Duan et al. (ICML '24)_, it replaces static spatial sharing with dynamic, millisecond-scale repartitioning. Relative to _Zhong et al. (OSDI '24)_, it targets the same prefill/decode imbalance without paying the KV-cache migration costs of inter-GPU disaggregation.

That makes the paper valuable to both serving practitioners and systems researchers. Practitioners get a concrete recipe for intra-GPU phase orchestration on top of existing runtimes such as SGLang. Researchers get a useful reframing: the bottleneck is not just memory management or batching policy, but the inability to express and enforce fine-grained GPU resource splits for dependent phases.

## Limitations

The paper is candid about several limits. Bullet depends on profiling plus online calibration for each model and hardware setting, so portability is not free even if the estimator keeps profiling cost modest. On low-compute GPUs serving dense models, decode can require a large SM share just to saturate memory bandwidth, which reduces the headroom for concurrent gains. The design also assumes standard LLM architectures more than specialized ones; the authors explicitly note that architectures such as DeepSeek-MLA may favor disaggregation enough that Bullet would not match the best specialized solution.

I would add two reviewer-style caveats. First, the scheduler’s quality depends on the stability of the latency model under changing kernels, attention variants, and adapter stacks such as LoRA; the paper says extending the model is straightforward, but does not validate that claim. Second, Bullet’s control loop is evaluated inside a specific SGLang-based implementation with `libsmctrl`, so portability to other serving stacks is plausible but not demonstrated end to end.

## Related Work

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve shows why chunked prefill helps decode latency, while Bullet argues that chunking still leaves a biased utilization tradeoff and replaces it with dynamic SM partitioning.
- _Zhu et al. (OSDI '25)_ — NanoFlow overlaps kernels within a chunked-prefill pipeline, whereas Bullet removes the shared token-budget constraint and lets prefill and decode progress independently.
- _Zhong et al. (OSDI '24)_ — DistServe separates prefill and decode across GPUs to avoid interference; Bullet seeks similar phase specialization inside one GPU without KV-cache migration.
- _Duan et al. (ICML '24)_ — MuxServe multiplexes multiple LLM workloads with static spatial-temporal sharing, but Bullet adds contention-aware modeling and fast repartitioning for dependent prefill/decode phases.

## My Notes

<!-- empty; left for the human reader -->
