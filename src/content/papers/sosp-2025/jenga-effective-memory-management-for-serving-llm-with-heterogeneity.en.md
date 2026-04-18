---
title: "Jenga: Effective Memory Management for Serving LLM with Heterogeneity"
oneline: "Jenga combines LCM-sized pages with attention-aware cache policies so heterogeneous LLMs waste less GPU memory and keep larger serving batches."
authors:
  - "Chen Zhang"
  - "Kuntai Du"
  - "Shu Liu"
  - "Woosuk Kwon"
  - "Xiangxi Mo"
  - "Yufeng Wang"
  - "Xiaoxuan Liu"
  - "Kaichao You"
  - "Zhuohan Li"
  - "Mingsheng Long"
  - "Jidong Zhai"
  - "Joseph Gonzalez"
  - "Ion Stoica"
affiliations:
  - "Tsinghua University"
  - "UC Berkeley"
  - "University of Chicago"
  - "Independent Researcher"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764823"
code_url: "https://github.com/heheda12345/Jenga-SOSP25-AE"
tags:
  - llm-inference
  - memory
  - caching
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Jenga argues that PagedAttention's one-page-format design no longer matches modern LLMs, whose layers can have different per-token state sizes and different token-dependency patterns. It replaces that homogeneous allocator with an LCM-based two-level page allocator and layer-specific prefix-cache policies. In vLLM, this lets heterogeneous models fit larger batches and raise serving throughput by 1.39x-2.16x without hurting low-load latency.

## Problem

The paper starts from a mismatch between serving engines and newer model architectures. PagedAttention assumes each layer stores the same per-token state and needs the same amount of prefix history. That fit early full-attention Transformers, but it breaks on today's heterogeneous models: VLMs mix text KV cache with differently sized vision or cross-attention state, Gemma-3 and Ministral interleave full and sliding-window attention, and Jamba/Hymba add much larger recurrent state. Under these models, a homogeneous page layout wastes memory badly: the paper reports 79.6% waste for Llama 3.2 11B Vision on MMMU-pro and 73.6% waste for Gemma-3 on a real trace-derived workload. Prefix caching also gets harder because the overall hit rate is capped by the least reusable layer type.

## Key Insight

Jenga's central claim is that memory management should track layer properties rather than treating all cached state as interchangeable KV pages. The paper reduces each layer type to three behaviors: its `page_size`, which pages remain `active_pages` for future generation, and which cached-token patterns form a valid `possible_prefix` hit. Once those properties are explicit, the runtime can choose a large-page size as the least common multiple of all layer page sizes, carve type-specific small pages out of those large pages, and define eviction and hit rules per attention mechanism while still balancing cache retention across layers.

## Design

Jenga has three main pieces. First, a global allocator manages large pages whose size is the LCM of all page sizes seen in the model, and per-layer allocators split those large pages into small pages for full attention, sliding window, Mamba state, vision embeddings, and so on. Because each layer exposes `active_pages`, Jenga can free memory as soon as a token stops mattering for future computation instead of retaining all historical KV state.

Second, Jenga changes the physical layout from "layer then page" to "page then layer," but preserves the interface expected by existing attention kernels through per-layer metadata such as `KV_cache_start_ptr`, effective page size, and page IDs. That lets the system reuse vLLM/PagedAttention workers with small worker-side changes.

Third, prefix caching becomes layer-specific. Jenga updates last-access timestamps only for pages that are active in the current generation step, so sliding-window layers naturally age out old tokens while full-attention layers keep their whole live prefix hot. Cache-hit rules are also customized: sliding-window layers require only the relevant suffix, local-attention layers require the current chunk, and Mamba layers cache every 512th state. A separate common-page pool keeps pages predicted to recur soon.

## Evaluation

The implementation is about 4 KLOC of Python inside vLLM. Evaluation uses H100 80 GB and L4 24 GB GPUs, several heterogeneous models including Llama 3.2 Vision, Gemma-3, Ministral, Llama 4, Jamba, and PyramidKV, and workloads from MMMU-pro, MMLU-pro, and arXiv-QA. The main baseline is vLLM v0.8.3 with only the memory manager replaced, plus two simpler heterogeneous extensions of PagedAttention called Static Partition and Max Page, which makes the core comparison reasonably clean.

The headline results are strong. Jenga improves end-to-end throughput by up to 1.73x on H100 and 2.16x on L4, averaging 1.46x and 1.65x respectively, while matching vLLM closely at low load: for Llama 3.2 Vision, average latency differs by only 4.2% when request rate is low. Under higher load, lower waste translates into much lower queueing delay, including up to 23.4x lower time-to-first-token. The breakdowns support the mechanism: on a Ministral trace, vLLM wastes 38.2% of KV memory on average, while Jenga reduces that to 0.04%; average decode batch size rises to 5.39 requests versus about 2.5-2.7 in vLLM, SGLang, and TGI; prefix-cache customization raises hit rate by up to 1.60x and throughput by up to 1.77x on arXiv-QA. Llama 4's maximum context on one 8xH200 node also grows from 3.7M tokens in vLLM to 14.7M with Jenga.

## Novelty & Impact

Relative to prior serving work, Jenga's novelty is not another cache heuristic. It generalizes page-based LLM serving from a homogeneous KV abstraction to a typed memory substrate where allocation, reclamation, eviction, and cache-hit semantics all depend on layer behavior. That should matter to runtime builders who need one engine to support VLMs and hybrid-attention models, and to researchers adding new attention or KV-compression mechanisms without rewriting the serving stack.

## Limitations

The paper leaves some important boundaries. Full multi-model serving beyond speculative decoding is future work. The prefix predictor assumes short-term repetition of common prefixes, so the common-page pool helps less on weak-locality workloads. Some reported workloads are simulated rather than production traces, which limits external validity. Jenga is also evaluated mainly as a vLLM modification; the paper does not provide full end-to-end comparisons against SGLang or TGI because those engines support only a subset of the models. Hamba is not evaluated because the necessary kernels were unavailable in vLLM, and some policy choices, such as caching every 512th Mamba state, remain heuristic.

## Related Work

- _Kwon et al. (SOSP '23)_ - PagedAttention/vLLM makes continuous LLM serving practical, but it assumes one uniform page format and one uniform prefix-cache semantics across layers.
- _Agrawal et al. (OSDI '24)_ - Sarathi-Serve improves the throughput-latency tradeoff with chunked prefills, while Jenga changes the memory substrate underneath such schedulers for heterogeneous models.
- _Zhong et al. (OSDI '24)_ - DistServe separates prefill and decode across resources; Jenga is orthogonal and focuses on how one engine stores and reuses heterogeneous cached state.
- _Yu et al. (OSDI '22)_ - Orca popularizes continuous batching for transformer serving, but leaves heterogeneous per-layer memory behavior outside the batching abstraction.

## My Notes

<!-- empty; left for the human reader -->
