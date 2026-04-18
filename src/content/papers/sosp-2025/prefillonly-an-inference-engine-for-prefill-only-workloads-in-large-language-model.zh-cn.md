---
title: "PrefillOnly: An Inference Engine for Prefill-only Workloads in Large Language Model Applications"
oneline: "PrefillOnly 用 hybrid prefilling 缩小单输出 token LLM 请求的活跃推理显存，再按持续更新的 prefill 时间估计调度队列。"
authors:
  - "Kuntai Du"
  - "Bowen Wang"
  - "Chen Zhang"
  - "Yiming Cheng"
  - "Qing Lan"
  - "Hejian Sang"
  - "Yihua Cheng"
  - "Jiayi Yao"
  - "Xiaoxuan Liu"
  - "Yifan Qiao"
  - "Ion Stoica"
  - "Junchen Jiang"
affiliations:
  - "University of Chicago"
  - "TensorMesh, Inc."
  - "Tsinghua University"
  - "LinkedIn"
  - "UC Berkeley"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764834"
tags:
  - llm-inference
  - memory
  - caching
  - scheduling
  - gpu
category: llm-serving
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PrefillOnly 认为 recommendation、verification、embedding，以及 prefill/decode disaggregation 里的 prefill 节点，并不是 chat serving 的小变体，而是独立的 prefill-only 工作负载。它用 hybrid prefilling 降低活跃推理显存，保留可复用 prefix cache 的同时丢弃或转移 suffix KV，再用持续重估的 shortest-prefill-first 调度请求。论文在四种 2-GPU 配置上报告，相比通用基线可把可持续 QPS 提高 1.4x-4.0x，同时不恶化平均延迟和 P99 延迟。

## 问题背景

现有 LLM inference engine 基本都是按“可能生成任意长输出”来设计的。因此系统默认要保留所有层的 KV cache，给后续 decode 继续复用；调度器也不能太依赖 JCT，因为输出长度事先不确定。对 prefill-only 请求来说，这两条前提都不成立。

论文关心的场景包括 post recommendation、credit verification、data labeling，以及 embedding generation 和 prefill/decode disaggregation 里的 prefill 节点。这些请求的输入往往很长，评估里模拟的 recommendation user profile 有 11k-17k tokens，credit history 有 40k-60k tokens，但模型真正需要的只是一个 next-token 概率分布，或者某个位置的最终 hidden state。现有引擎却仍然为不会发生的后续 decode 支付显存和调度代价。

看起来最直接的替代方案也都不理想。chunked prefilling 确实能容纳更长输入，但会把 attention kernel 做慢。tensor parallelism 和 pipeline parallelism 能把 KV 状态分摊到多张 GPU 上，却分别带来 all-reduce 通信和 pipeline bubble。另一方面，单 token 输出让服务时间比生成式请求更可预测，可现有引擎大多还是用 JCT-agnostic 的队列策略，于是既拿不到更低延迟，也拿不到更好的 prefix-cache locality。

## 核心洞察

对 prefill-only workload，系统应该优化“执行中的活跃状态”，而不是为未来 decode 复用预留一整套状态。一旦请求在生成一个 token 后就结束，大部分 prefill 阶段产生的 KV 都没有必要长期常驻，队列也可以按 prefill 时间的良好代理量来排序。

难点在于真正吃掉显存的并不只是 KV。PrefillOnly 证明，哪怕只保留当前层 KV，收益也有限，因为峰值显存主要来自 MLP 中间张量：在 Llama-3.1-8B 中，两个主要临时张量分别是 28,672 和 14,336 floats/token，而单层 KV 只有 2,048。换句话说，这篇论文最值得记住的命题是：应当激进地压缩 linear-layer intermediates，同时保持 attention 不被 chunking 拖慢，然后把“只输出一个 token”带来的确定性用于调度。

## 设计

PrefillOnly 先做一次 profiling run。给定用户配置的 maximum input length，它会用一个同长度 synthetic request 跑完整个模型，测出峰值 GPU memory，再把剩余显存预算留给 prefix KV cache。运行时，系统提供兼容 OpenAI API 的前端，请求经由 scheduler 逐步选出，再分发给构建在 vLLM 之上的 executor。

第一部分是 hybrid prefilling。PrefillOnly 对 non-attention layers 做 chunk-by-chunk 处理，但让 attention layers 保持 unchunked。它借助 `torch.compile` 改写计算图，把一串连续的 linear operators 视为一个 virtual layer，再逐块执行这个 virtual layer，最后拼回完整输出。这里有两个关键实现细节：一是预先分配完整 output tensor，避免 concat 时显存翻倍；二是当输入输出形状一致时做 in-place reuse，把输出 chunk 直接写回输入 buffer。因为整个 prefill 依然在一次 forward pass 内完成，系统就能安全地丢弃或转移部分 KV，而不用在后续 chunk 中重新生成或重新加载它们。

第二部分是 suffix KV discarding/offloading。PrefillOnly 尽量把未来可能复用的 prefix KV 留在 GPU 中，只在请求长度超过预算时丢弃或转移 suffix KV。和 vLLM 那类“请求结束后再做 suffix eviction”的方案不同，它是在请求执行过程中就开始处理 suffix，因此能把 maximum input length 推得更高。论文原型目前只实现了 discarding，但作者明确指出可以接入 LMCache 或 Mooncake 这类 offload 系统。

第三部分是带持续重估的 shortest-prefill-first 调度。作者认为这类 workload 在上下文还没有长到把显存完全压满之前，通常是 compute-bound，因此 PrefillOnly 不做 batching，而是一次只跑一个请求。每次调度前，它都会为所有等待请求重新计算 `estimated_prefill_time - lambda * queue_time`，其中 prefill time 的代理量不是输入长度本身，而是 cache-miss tokens。持续重估很关键，因为 prefix-cache hit 会随时间出现和消失；如果不重算，最短作业优先也可能错过那些刚刚因为缓存而变便宜的请求。

## 实验评估

PrefillOnly 在 vLLM 之上新增约 4.6k 行 Python 代码，测试平台包括 2x L4、2x A100、2x H100 PCIe 和 2x H100 NVLink，模型涵盖 Llama-3.1-8B、Qwen-32B FP8 和 Llama-3.3-70B FP8。工作负载来自模拟而非生产 trace，这确实削弱了外部有效性，但两类 trace 至少对应了论文真正想解决的两件事：recommendation 侧重 prefix reuse，credit verification 侧重超长输入。

结果基本支撑了中心论点。跨不同硬件和 workload，PrefillOnly 相比 PagedAttention、chunked prefilling、tensor parallelism 和 pipeline parallelism，报告了 1.4x-4.0x 更高的可持续 QPS，同时没有抬高平均延迟或 P99 延迟。在 recommendation 场景里，主要收益来自调度：continuous prefill time estimation 能避免 FIFO 和 naive shortest-job policies 出现的 prefix-cache thrashing。在 credit verification 里，主要收益则来自绕开 inference parallelization 所需的通信和 pipeline bubbles。

maximum input length 的结果也很关键。PrefillOnly 在 L4/A100/H100 上分别达到 130k/87k/97k tokens；对应地，PagedAttention 只有 24k/11k/15k，chunked prefilling 只有 46k/17k/25k。tensor parallelism 和 pipeline parallelism 在某些机器上能支持更长上下文，但那正是论文想避免的吞吐代价。论文还验证了调度代理量的合理性：在 Qwen-32B FP8 配置上，cache-miss tokens 与实测 prefill time 的 Pearson 相关系数达到 0.987。

## 创新性与影响

这篇论文最有价值的地方首先是系统视角，而不是某一个新 kernel。它把 prefill-only serving 提升为一类一等工作负载，而不是 generative serving 的边角情形，再围绕这个视角重写显存管理和 queueing discipline。最扎实的具体机制是 hybrid prefilling，因为它说明了如何在不承担 chunked attention 代价的前提下真正压低活跃显存。对 recommendation、verification、embedding，以及 disaggregated serving 这类今天仍继承 chat-oriented runtime 假设的系统来说，这个 framing 很可能会被后续工作引用。

## 局限性

这篇论文最大的限制是外部有效性。两套数据都是模拟出来的，因此没有展示真实生产流量、真实租户混部或长时间运行下的运维特征。它也有明确的失利区间：如果瓶颈是 prefix-cache capacity，而不是单请求执行时的活跃显存，那么 tensor parallelism 或 pipeline parallelism 可能更合适，因为每张 GPU 只需保存一部分 KV。当前原型只会丢弃 suffix KV，不会真正 offload，所以潜在的未来复用会丢失；调度策略也只在单个 engine instance 内生效，论文自己也承认大规模部署下全局 shortest-prefill-first routing 可能更好。最后，在低 QPS 场景里，parallelized baselines 的单请求延迟也可能更低，因为 PrefillOnly 有意避免把一个请求拆到多张 GPU 上。

## 相关工作

- _Kwon et al. (SOSP '23)_ — PagedAttention/vLLM 提高了通用 LLM serving 的显存管理效率，但仍默认保留全层 KV，而且基本不利用单 token 请求更可预测的 JCT。
- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve 用 chunked prefilling 优化生成式 serving 的吞吐-延迟折中，而 PrefillOnly 保持 attention unchunked，只对线性部分做 chunking。
- _Zhong et al. (OSDI '24)_ — DistServe 把 generative workload 的 prefill 和 decode 分离到不同资源池；PrefillOnly 研究的是 prefill 本身就是全部 workload 的极端情形。
- _Yu et al. (OSDI '22)_ — Orca 依赖 continuous batching 提升生成式 serving 吞吐，而 PrefillOnly 认为对 compute-bound 的 prefill-only 请求，batching 往往不是合适抽象。

## 我的笔记

<!-- empty; left for the human reader -->
