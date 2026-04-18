---
title: "HedraRAG: Co-Optimizing Generation and Retrieval for Heterogeneous RAG Workflows"
oneline: "HedraRAG 将异构 RAG 工作流表示成图，并通过子阶段切分、相似性感知重排与部分 GPU 索引缓存，把检索和生成更紧密地协同起来。"
authors:
  - "Zhengding Hu"
  - "Vibha Murthy"
  - "Zaifeng Pan"
  - "Wanlu Li"
  - "Xiaoyi Fang"
  - "Yufei Ding"
  - "Yuke Wang"
affiliations:
  - "Computer Science and Engineering, UCSD"
  - "Nano and Chemical Engineering, UCSD"
  - "RegAilator Inc"
  - "Computer Science, Rice University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764806"
tags:
  - llm-inference
  - scheduling
  - caching
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HedraRAG 将 RAG serving 视为图调度问题，而不是固定两阶段流水线。它把检索和生成切成细粒度子阶段，利用语义局部性重排执行顺序，并只把最热的 IVF cluster 缓存在 GPU 上。论文报告，在多种异构 RAG 工作流上，它相对现有框架取得了超过 `1.5x`、最高 `5x` 的吞吐提升。

## 问题背景

现代 RAG 请求已经高度异构：有 multistep reasoning，有 HyDE 式的 pre-retrieval generation，也有 RECOMP 式的 post-retrieval processing；不同工作流的阶段数量和阶段时长都不一样。现有框架虽然能在 API 层把这些组件拼起来，但在 runtime 层仍然只是“LLM engine + vector search backend”的松耦合组合。

这会带来三个问题。第一，GPU 上的生成偏好 continuous token-level batching，而 CPU 上的检索偏好更大的固定 batch，直接串接后很容易出现 pipeline stall。第二，多轮工作流内部明明存在语义局部性，但系统通常把每个 stage 当成独立工作来做，重复付出计算代价。第三，retrieval access 往往有明显 skew，可 GPU 内存已经被模型权重和 KV cache 挤满，无法把整份索引都常驻在设备上。

## 核心洞察

论文的核心判断是：异构性应该被表示为图结构，而不是被粗粒度 stage 掩盖掉。只要把请求表示成节点和依赖关系，runtime 就能用同一种抽象同时利用三类机会：跨请求重叠 generation 与 retrieval、在单个请求内部复用语义相似性、以及跨请求加速最热的 retrieval 区域。

之所以有效，是因为真正的瓶颈来自被隐藏的结构信息。长 retrieval 可以被切开，后续 query 常常在 embedding 空间里接近前一轮 query，而当前真正活跃的 IVF cluster 只占很小一部分。一旦这些事实被显式化，调度器就可以重写执行计划，而不是被原始 stage 边界绑死。

## 设计

HedraRAG 提出 `RAGraph`，其中节点是 Generation 或 Retrieval，边表示数据流和控制流。系统随后在图上执行 node splitting、reordering、edge insertion 和 dependency rewiring 等变换。

第一类变换是细粒度子阶段流水化。Generation 节点被拆成若干 decoding step，Retrieval 节点被拆成一个或多个 IVF cluster 的搜索，而且 retrieval 的切分边界由 time budget 决定，而不是固定 cluster 数。这样一来，CPU 侧检索与 GPU 侧 decoding 更容易对齐，不会让单个长 retrieval 卡住整条请求流。

第二类变换利用请求内语义相似性。HedraRAG 会缓存上一轮 retrieval 的较大 top-`k` 结果，在下一轮先搜索这些更可能命中的区域，并重排后续 query 的 cluster 顺序，让 ANN search 更早终止。随后系统再做 speculative execution：可以用部分 retrieval 结果先启动 generation，也可以用部分生成文本先启动 retrieval，只有投机失败时才回滚。

第三类变换是部分 GPU 索引缓存。系统持续跟踪最热的 IVF cluster，只把这些 cluster 放进 GPU cache，其他 cluster 仍留在 CPU 上。每个 retrieval 子阶段会被拆分到 GPU-cached cluster 和 CPU-resident cluster 两侧并行执行，最后再合并结果。wavefront scheduler 则不断收集活跃请求里的可执行节点，重写图，并把任务派发给独立的 vLLM worker 和 Faiss worker。

## 实验评估

实验运行在 AMD EPYC 9534 64-core + NVIDIA H100 80 GB 上，使用 Llama 3.1-8B、约 `38M` 文档的 Wikipedia corpus、`e5_large` embedding，以及 `IVF4096` 索引，`nprobe` 从 `128` 到 `512`。工作流包括 One-shot、HyDE、RECOMP、Multistep 和 IRG。baseline 包括 LangChain、FlashRAG、更强的异步 vLLM+Faiss baseline，以及已有 speculative 方法。

HedraRAG 在相同到达率下可把请求延迟降低 `2.2x` 到 `18.2x`，吞吐提升超过 `1.5x`、最高 `5x`；而且工作流越复杂、retrieval 越昂贵，收益越明显。分项实验也解释了这些收益的来源：细粒度 partitioning 可把 vector search latency 降低 `1.09x` 到 `1.77x`，相似性感知重排加 speculative execution 额外带来 `1.06x` 到 `1.62x`，部分 GPU indexing 再带来 `1.12x` 到 `1.49x`。在混合并发工作流中，延迟最多降低 `5.5x`，吞吐最多提高 `3.3x`。这些结果基本支撑了论文对瓶颈来源的判断。

## 创新性与影响

与 LangChain 或 FlashRAG 相比，HedraRAG 的贡献不只是把 retrieval 和 generation 拼在一起，而是把异构 RAG 作为图调度问题来统一优化。与只解决某一类 speculative 或 cache 问题的点式方案相比，它给出了更一般的优化表面。因此，这篇论文对 RAG serving runtime、hybrid CPU-GPU retrieval 系统，以及需要调度不规则多阶段工作流的 agentic LLM runtime 都有参考价值。

## 局限性

实现和评估都局限在单机场景。系统还依赖若干经验性策略，例如 retrieval 的 time budget、speculation threshold 和 GPU cache sizing，因此工作负载漂移时行为可能变化。若生成成为绝对主瓶颈，或 retrieval skew 不明显，收益也会减弱；speculative execution 失败时仍需承担 rollback 成本。最后，评估重点是服务效率，而不是覆盖所有优化组合的答案质量研究。

## 相关工作

- _Lewis et al. (NeurIPS '20)_ - Retrieval-Augmented Generation 定义了算法层面的 RAG 范式，而 HedraRAG 关注的是如何高效服务这种越来越异构的工作流。
- _Yu et al. (OSDI '22)_ - Orca 说明了 continuous batching 对 LLM serving 的价值，而 HedraRAG 需要进一步把这种生成侧模型与偏好另一种 batching 规律的检索阶段协调起来。
- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention 让 GPU 上的 generation 更高效，但它并不负责 generation 与 vector search 的协同，也不处理多轮 RAG 的结构异构性。
- _Zhang et al. (NSDI '24)_ - Reordered Pipelining 关注超出 GPU memory 的向量查询加速，而 HedraRAG 将类似问题嵌入到了端到端的混合 RAG runtime 里。

## 我的笔记

<!-- 留空；由人工补充 -->
