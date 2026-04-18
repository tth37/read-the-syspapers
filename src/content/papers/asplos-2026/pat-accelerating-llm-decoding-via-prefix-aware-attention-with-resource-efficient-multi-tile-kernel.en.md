---
title: "PAT: Accelerating LLM Decoding via Prefix-Aware Attention with Resource Efficient Multi-Tile Kernel"
oneline: "PAT packs decode queries by shared prefix, runs resource-aware multi-tile kernels, and merges partial results to cut LLM decode-attention latency."
authors:
  - "Jinjun Yi"
  - "Zhixin Zhao"
  - "Yitao Hu"
  - "Ke Yan"
  - "Weiwei Sun"
  - "Hao Wang"
  - "Laiping Zhao"
  - "Yuhao Zhang"
  - "Wenxin Li"
  - "Keqiu Li"
affiliations:
  - "Tianjin University, Tianjin, China"
  - "Stevens Institute of Technology, Hoboken, NJ, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790200"
code_url: "https://github.com/flashserve/PAT"
tags:
  - llm-inference
  - gpu
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PAT argues that decode attention should be optimized around memory traffic, not just arithmetic throughput. It packs decoding queries that share KV prefixes into the same CTA, assigns each CTA a tile shape that better matches its query count and KV length, and then uses multi-stream execution plus a lightweight merge kernel to recover final attention outputs. The paper shows that this combination materially reduces redundant global-memory loads and improves both kernel latency and end-to-end token latency.

## Problem

The paper starts from a shift that many LLM-serving papers acknowledge but do not fully solve: as prompts and generations get longer, decoding increasingly dominates inference latency, and decode attention is mostly memory-bound because every step reloads a large KV cache from global memory. At the same time, real deployments now contain substantial prefix sharing across requests. System prompts, tool templates, and retrieved context often create multi-level shared prefixes inside the same continuous-batching window. Existing systems such as vLLM and SGLang reuse those prefixes to save KV-cache space, but that logical reuse does not by itself reduce how often the attention kernel fetches the shared KV blocks from memory.

The authors argue that current attention kernels leave performance on the table in two different ways. Query-centric kernels such as FlashAttention map one query to one CTA, which means shared prefix blocks are loaded repeatedly by different CTAs. KV-centric kernels reduce some redundant loads by packing shared prefixes together, but they typically use a fixed tile shape and padding-heavy execution style. That creates wasted shared memory, register pressure, and tail bubbles when CTAs have very different KV lengths. The practical problem is therefore broader than "support prefix reuse": the kernel must exploit shared prefixes while staying efficient under dynamic batch composition and uneven query lengths.

## Key Insight

The paper's main claim is that decode attention should be treated as a memory-centric packing problem. If multiple requests share a long enough KV prefix, then it is profitable to execute them together because loading the shared prefix once is worth the extra intermediate reads and writes needed to merge partial results later. But that benefit only materializes if the kernel shape also adapts to the packed CTA instead of forcing every CTA through the same tiling regime.

That leads to PAT's pack-forward-merge design. First, pack queries by shared prefixes so a CTA can reuse KV blocks in on-chip memory. Second, forward those CTAs with a kernel family that selects tile sizes based on the CTA's actual query count and KV length. Third, merge the partial outputs with online softmax. The important idea is that packing and kernel configuration are coupled: reducing global-memory traffic without fixing resource inefficiency would simply move the bottleneck elsewhere.

## Design

PAT has three stages. In the pack stage, it turns the batch's block table into a prefix tree whose internal nodes represent shared prefixes and whose leaves represent individual queries. The scheduler uses a heuristic profit model to decide whether a node should become its own CTA, stay split, or merge with a child. The model explicitly compares saved KV loads against the overhead of writing and later reading intermediate results. Because exact search is exponential, the implementation uses a tree walk with linear complexity in the number of nodes and edges. To keep runtime overhead small, PAT also uses lazy update: it reuses a previous packing plan until the block table changes and runs scheduling asynchronously once the block table is available.

In the kernel stage, PAT abandons the one-size-fits-all tile policy used by earlier kernels. It derives feasible query-tile and KV-tile pairs offline from shared-memory limits, register limits, and a bandwidth-saturation lower bound, then compiles a suite of kernels for those tile pairs. At runtime, a tile selector chooses the smallest feasible query tile that avoids unnecessary padding and chooses the KV tile with a piecewise rule derived from profiling. Large KV tiles are favored for long sequences because they reduce execution bubbles and give each CTA more bandwidth; smaller tiles are favored for short sequences because they avoid a large compute-only tail on the last tile.

The forward stage handles another systems issue: multiple tile shapes would normally force serial kernel launches. PAT instead groups CTAs by tile configuration, launches each group on its own CUDA stream, and lets different streams overlap. It also splits extremely long-KV CTAs so that a few outliers do not dominate the tail of execution. Finally, the merge stage uses a lightweight online-softmax kernel to combine per-query partial maxima, log-sum-exp terms, and weighted sums into final outputs. PAT is implemented as a vLLM plugin, so it reuses vLLM's paged KV cache rather than redefining the serving stack.

## Evaluation

The evaluation is strong on the kernel question the paper poses. The authors benchmark on A100 and H100 GPUs and test both synthetic decode batches and end-to-end serving traces. Synthetic batches vary prefix-tree shape, prefix lengths, non-shared suffix lengths, and head layouts, which is important because PAT's value depends directly on how much prefix structure exists and how uneven the packed CTAs become. The end-to-end experiments use Qwen3-8B and Llama-3-8B on real `toolagent` and `conversation` traces, plus additional results for Qwen2.5-72B with TP/PP and Qwen3-30B-A3B under an MoE architecture.

The headline kernel result is that PAT reduces attention latency by 53.5% on average versus the state of the art under shared-prefix workloads. On A100 synthetic workloads, it reports up to `21.5x` speedup over FlashAttention, `11.7x` over FlashInfer, `3.2x` over FastTree, `11.9x` over RelayAttention, and `5.7x` over RelayAttention++. The paper's explanation is plausible: query-centric baselines pay repeated global-memory loads, while KV-centric baselines still lose to fixed tile choices or weaker packing heuristics. Even when shared prefixes are removed, PAT still gets a small average gain from its multi-tile and multi-stream machinery, suggesting the design is not entirely dependent on prefix reuse.

For end-to-end serving, PAT reduces mean TPOT by `17.2-68.1%` over RelayAttention++, `17.0-89.5%` over FlashAttention, and `32.2-93.1%` over FlashInfer at the same request rate. TTFT also drops substantially because faster decode drains the queue sooner. The ablation study is especially useful: replacing the memory-oriented packer with a compute-oriented one, using naive packing, forcing a fixed tile size, or disabling multi-stream execution all measurably hurt latency. That does a good job supporting the paper's central argument that PAT's benefit comes from the combination of prefix-aware packing and resource-aware execution, not from a single isolated trick.

## Novelty & Impact

Relative to _Kwon et al. (SOSP '23)_, PAT does not propose a new KV-cache abstraction; it assumes paged KV caches already exist and asks how the decode kernel should execute on top of them. Relative to _Pan et al. (MLSys '25)_, its main difference is the cost model: PAT explicitly optimizes for memory traffic in a memory-bound phase, whereas FastTree's compute-oriented packing is presented as mismatched to decode attention. Relative to _Zhu et al. (ACL '24)_, PAT generalizes beyond a single system-prompt prefix and builds a kernel family rather than relying on a fixed forward kernel.

That makes the paper valuable to both kernel implementers and serving-system builders. It is not merely another faster attention kernel; it reframes shared-prefix execution as a joint scheduling-and-kernel-design problem. Papers on LLM serving, KV-cache reuse, or GPU decode kernels are likely to cite it when they need a stronger primitive for prefix-heavy workloads.

## Limitations

PAT's gains depend on workload structure. The paper is explicit that small batches or workloads without shared prefixes leave less room for improvement, and its own no-prefix experiments show only modest gains in that regime. The tile configurations also depend on offline derivation for each GPU architecture, and the runtime selector depends on profiling-based rules rather than a fully analytic model.

There are also deployment boundaries. PAT is implemented for the decode stage and plugs into vLLM's existing paged KV cache, so it does not solve the broader serving problems of admission control, routing, or multi-model scheduling. Multi-stream execution reduces but does not eliminate residual GPU scheduling bubbles, which the discussion section calls out as the remaining gap to the theoretical optimum. Finally, the evaluation is thorough for attention latency and online serving, but it is still centered on a single serving substrate and a small set of model families.

## Related Work

- _Kwon et al. (SOSP '23)_ — PagedAttention makes KV-cache reuse practical in serving systems, while PAT focuses on how the decode kernel should exploit that reuse to cut memory traffic.
- _Dao et al. (NeurIPS '22)_ — FlashAttention establishes IO-aware fused attention, but its query-centric execution does not exploit cross-request shared prefixes during decoding.
- _Pan et al. (MLSys '25)_ — FastTree also targets tree-structured prefix sharing, but PAT argues for a memory-oriented packing objective and adds multi-tile, multi-stream execution.
- _Zhu et al. (ACL '24)_ — RelayAttention reduces redundant loads for long system prompts, whereas PAT extends the idea to multi-level shared prefixes and dynamic CTA shapes.

## My Notes

<!-- empty; left for the human reader -->
