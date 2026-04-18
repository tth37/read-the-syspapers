---
title: "Bullet: Boosting GPU Utilization for LLM Serving via Dynamic Spatial-Temporal Orchestration"
oneline: "Bullet 通过 contention-aware 延迟建模与动态 SM 重分配，让同一张 GPU 上的 prefill 和 decode 并发执行并同时守住延迟目标。"
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
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Bullet 的核心判断是，传统 chunked prefill 不是只在“吞吐和延迟之间做权衡”，而是在错误的控制面上做权衡。它不再把 prefill 和 decode 塞进同一个 lock-step hybrid batch，而是在单张 GPU 上让两者并发执行，并用 contention-aware 的延迟模型与在线 SM 重分配去守住 TTFT 和 TPOT SLO。这样做能把原本闲置的 Tensor Core 和内存带宽重新吃满，从而获得更好的整体吞吐。

## 问题背景

论文从一个很扎实的硬件事实出发：LLM serving 的 prefill 是计算密集型，decode 是内存带宽受限型，因此单一执行模式很难同时把两类资源都用满。工业界常用的办法是 chunked prefill，也就是把 prefill 拆成若干 chunk，再和 decode token 按固定 token budget 混合执行。这个方法确实能稳住 decode 侧的延迟，但代价是引入一个带偏置的结构性 tradeoff。chunk 太小，会因为 wave quantization 和反复重载 KV cache 造成严重算力浪费；chunk 太大，又会拖长 TTFT，并把后续请求堵在 prefill 队列里。

作者没有把这个问题停留在概念层面，而是做了硬件测量。对 A100 上的 Llama-3.1-8B 来说，prefill 阶段完整 Transformer layer 的计算利用率只有大约 70%-76%，短序列 kernel 尤其容易受 wave quantization 影响。更关键的是，chunked prefill 会随着长请求推进而越来越差：对一个 16k prompt，如果用 1k chunk，compute efficiency 会从 71% 逐步掉到 61%，最后一个 chunk 的处理时间是第一个的 1.9x。也就是说，现有系统里的 TTFT-TPOT tradeoff 不是一个“干净”的算法权衡，而是被 GPU 低利用率和重复工作扭曲过的结果。论文真正要解决的是：如何在同一张 GPU 上联合运行存在依赖关系的 prefill 和 decode，同时又保持时延可预测。

## 核心洞察

Bullet 最值得记住的洞察是：prefill 和 decode 不该靠共享 token budget 来协调，而该靠显式的 spatial-temporal 资源控制来协调。prefill 足够 compute-bound，decode 足够 memory-bound，只要系统能精确控制每个阶段在每个时刻拿到多少 SM，两者并发其实可以把总体利用率拉高。真正困难的不是“共享”这个想法，而是如何让这种共享仍然可预测，足以满足 TTFT 和 TPOT 的 SLO。

因此，Bullet 选择的中心路径是：先把延迟建模成 execution state 与 SM budget 的函数，再让调度器持续重塑 GPU 分区。一旦系统能估计 prefill 和 decode 在不同 SM 划分下会如何互相拖慢，就不必继续依赖静态分区或 chunk-size heuristic，而可以在 layer 级别决定当前该把更多 GPU 给谁。

## 设计

Bullet 的设计有三个核心部分。第一部分是 performance estimator。作者把 execution state 定义为六个维度：prefill sequence length、prefill batch size、prefill SM 数、decode context length、decode batch size、decode SM 数。这个空间如果全量 profile 几乎不可行，所以 Bullet 提出 SM-scaling roofline model，再用少量共执行样本做校准，并在运行时持续在线修正。这个模型不只预测单独执行时的缩放，还显式考虑即便分到不同 SM 子集后仍然存在的干扰，尤其是 decode 带来的 memory subsystem contention。

第二部分是 SLO-aware scheduler。prefill 和 decode 各自有独立的调度循环，并通过共享元数据交换状态。prefill 以 layer-sized step 的方式发射 kernel，让 CPU 能频繁插手；decode 则用 CUDA Graph 提交，以消除小 kernel 的 launch overhead。策略上，系统优先照顾 prefill，因为更短的 TTFT 会扩大后续 decode batch，从而提升总体吞吐；但只要模型预测 TPOT 可能违约，就会立刻回收部分 SM 给 decode。负载突发时，Bullet 甚至会暂时把整张 GPU 都给 prefill，等队列回落后再迅速切回平衡点。

第三部分是 concurrent execution engine。Bullet 把 prefill 和 decode 放在两个独立进程里运行，但共享 CPU 侧元数据和统一的 GPU memory pool，用来放模型权重与 KV cache，因此请求从 prefill 迁移到 decode 时不需要搬运 KV。资源控制方面，它不采用代价较高的 MPS 重新配置，而是通过 `libsmctrl` 对 CUDA stream 做 SM masking，以微秒级开销重划 SM 子集。正是这个 control path 设计，让 layer-level 调度变成现实系统，而不只是一个纸面上的优化器。

## 实验评估

这篇论文的实验之所以有说服力，是因为它确实打在作者声称的瓶颈上：长 prompt、突发流量、以及 chunked prefill 容易排队失控的 serving 场景。在单张 A100 上服务 Llama3.1-8B 时，Bullet 在 ShareGPT、Azure-Code 和 arXiv-Summary 三类工作负载上都优于 SGLang-1024，平均吞吐提升 1.09x，最高达到 1.20x；平均 TTFT 提升 13.5x，端到端速度提升 1.86x。论文也比较诚实，没有宣称它对所有 baseline 的每个指标都绝对更好，而是强调通过动态 SM 分配避免 TTFT 爆炸，最终把整体 tradeoff 往更优方向推。

ShareGPT 的 tail-latency 结果尤其亮眼。Bullet 报告的 mean TTFT 是 0.16 s，P90 TTFT 是 0.31 s，相比 SGLang-1024 分别好 54.9x 和 78.5x。与 SGLang-2048 相比，Bullet 甚至同时改善了传统 chunk-size tradeoff 的两边：TTFT 降低 4.2x，TPOT 也提升到 1.20x。作者把这一点归因于 prefill 和 decode 的并发执行，而不是更聪明的 chunk heuristic，这和它的机制主张是吻合的。

多 GPU 与跨模型结果也把结论往外推了一步。对 8xA100 上的 Llama3.1-70B，Bullet 在 ShareGPT、3.0 req/s 时达到 173 ms/token，而 vLLM 与 SGLang 分别是 207 和 319 ms/token。对 H20 上的 Qwen3-235B-A22B，Bullet 在 4.0 req/s 下做到 110 ms/token，同时给出 1.4 s TTFT 和 45 ms TPOT，效果接近更重型的 3P1D disaggregated deployment。利用率分析也支撑了论文的中心论点：在并发执行期间，Bullet 的 active SM cycles 达到 86.2%，比 SGLang 高 11.2%，同时 Tensor Core 利用率和内存带宽利用率分别提升 11.8% 和 19.3%。

## 创新性与影响

和 _Agrawal et al. (OSDI '24)_ 相比，Bullet 的创新点不是继续微调 chunked prefill，而是指出“chunking 本身就是错误的控制面”。和 _Duan et al. (ICML '24)_ 相比，它把静态 spatial sharing 变成了毫秒级动态重分配。和 _Zhong et al. (OSDI '24)_ 相比，它想解决的是同一个 prefill/decode 失衡问题，但不愿意承担跨 GPU disaggregation 带来的 KV-cache 迁移成本。

因此，这篇论文对两类人都有价值。对工程团队，它给出了一条可落地的 intra-GPU phase orchestration 路线，而且能接在 SGLang 这样的现有运行时之上。对系统研究者，它提供了一个更准确的问题表述：瓶颈不只是 batching policy，也不只是内存管理，而是系统缺乏一种能够表达并执行“依赖阶段之间细粒度 GPU 资源切分”的机制。

## 局限性

论文对局限性的交代是比较清楚的。Bullet 需要针对具体模型和硬件做 profiling 再配合在线校准，因此移植成本不为零。对算力偏弱、但服务 dense model 的 GPU，decode 可能必须占用更大比例的 SM 才能把内存带宽吃满，这会压缩并发收益。它也更适合标准 LLM 架构；作者明确承认像 DeepSeek-MLA 这样特别适合 disaggregation 的体系结构，可能让 Bullet 无法达到最优专用方案的峰值性能。

从审稿视角看，我还会补两点。第一，调度器质量依赖延迟模型在不同 kernel、attention 变体和 LoRA 适配器下的稳定性；论文说扩展模型不难，但没有真正验证。第二，Bullet 的完整控制回路是在特定的 SGLang 加 `libsmctrl` 实现中评估的，因此它对其他 serving stack 的可移植性是可信的推测，但还不是论文已证明的事实。

## 相关工作

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve 说明了 chunked prefill 为什么能改善 decode latency，而 Bullet 进一步指出这种方法仍然带着偏置严重的利用率 tradeoff，并用动态 SM 分区替代之。
- _Zhu et al. (OSDI '25)_ — NanoFlow 在 chunked-prefill pipeline 内部做 kernel overlap；Bullet 则去掉共享 token-budget 约束，让 prefill 与 decode 真正独立推进。
- _Zhong et al. (OSDI '24)_ — DistServe 通过跨 GPU 拆分 prefill 与 decode 来规避干扰；Bullet 想在单 GPU 内部实现类似的阶段专门化，同时避免 KV-cache 迁移。
- _Duan et al. (ICML '24)_ — MuxServe 提供静态的 spatial-temporal sharing，而 Bullet 额外加入了 contention-aware 建模和快速重分区，以处理存在依赖关系的 prefill/decode 阶段。

## 我的笔记

<!-- 留空；由人工补充 -->
