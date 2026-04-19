---
title: "Fast State Restoration in LLM Serving with HCache"
oneline: "HCache 把状态复用对象从整份 KV cache 换成每层 hidden state，再把加载与 KV 重建流水化，使 LLM 状态恢复 TTFT 相比 KV offload 最多降低 1.93x。"
authors:
  - "Shiwei Gao"
  - "Youmin Chen"
  - "Jiwu Shu"
affiliations:
  - "Tsinghua University"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696072"
tags:
  - llm-inference
  - caching
  - gpu
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HCache 的判断很直接：状态化 LLM 服务里的 cache miss，不该靠整段 prompt 重跑，也不该靠整份 KV cache 回搬。它改存每层 hidden state，再用投影 GEMM 加上 RoPE 把 KV 还原出来，并把这段计算和存储读取并起来做。论文在 ShareGPT4 和 L-Eval 上报告，相比 KV offload，TTFT 最多降低 1.93x；相比 token recomputation，最多降低 5.73x，而且 TBT 额外开销不到 4%。

## 问题背景

这篇论文面对的是 stateful LLM serving：新请求不是孤立的，而是要接着历史上下文继续推理。多轮对话、长文问答、代码理解、RAG 都属于这一类。问题在于，历史上下文虽然值得复用，但 GPU 放不下太多。作者估算，一张 A100-40GB 大致只能常驻 7-20 个会话，或者 1-3 个长上下文，所以 cache miss 不是偶发事件，而是常态。

现有两条恢复路径都很贵。Token recomputation 要把历史 token 再 prefill 一遍，attention 和 FFN 全部重算，长序列下会被 quadratic attention 拖垮。KV offload 虽然不重算，但要把先前保存的整份 KV cache 从主机侧搬回 GPU，而它在典型模型里大约比原始 token 大 105 倍。论文在 L-Eval 上的测量也说明了这个代价：相对理想的无恢复系统，recomputation 的 TTFT 会慢 20.0-26.0 倍，KV offload 也还要慢 6.5-13.0 倍。

## 核心洞察

HCache 的核心洞察是：需要复用的状态，并不一定非得是 KV cache 本身。对每一层 transformer 来说，`K` 和 `V` 本来就是由该层输入的 hidden state 线性投影出来的，所以系统完全可以把 hidden state 当作持久化对象，在 cache miss 时再把它投影回 KV。

这一步同时省掉了 I/O 和计算。Hidden state 的体积只有 KV cache 的一半，所以传输量直接减半；而从 hidden state 恢复 KV，只需要做投影，不必重跑 attention 和 FFN。论文的代价分析给出的结论是，这部分计算至少比 token recomputation 便宜 6 倍，而且复杂度随历史长度线性增长。再加上 hidden state 加载吃的是存储带宽、KV 重建吃的是 GPU 计算，两者天然适合做流水线。

## 设计

HCache 的第一步是改写状态保存方式。在原始请求执行时，系统把每层 hidden state 转存起来，供之后复用。等到后续请求发生 cache miss，系统按层把 hidden state 读回 GPU，用 cuBLAS 做投影生成原始 `K`、`V`，再用自定义 kernel 补上 RoPE，最后写入运行时 KV cache。

真正难的是如何让传输和计算尽量没有空泡。作者用 bubble-free restoration scheduler 按层切分模型状态，让大多数层走 HCache，同时让少数层走互补路径补平资源失衡。若平台算力更强、I/O 更弱，就让前几层走 token recomputation，同时预取后面层的 hidden state；若平台 I/O 更快、算力相对弱，就让一部分层直接回搬 KV cache。论文最终选的是 layer-wise partition，而不是 token-wise partition，因为后者会形成不规则的小 GEMM。存储侧则把每层状态切成 64-token 的 chunk，按 round-robin 分散到多块 SSD；保存时先用一次 `cudaMemcpy` 把 hidden state 快照到主机 DRAM，再由后台线程重组并批量刷到 NVMe。多 GPU 场景下，各卡按 token 分片读取，再通过 NVLink all-gather 拼回完整状态。

## 实验评估

作者在 DeepSpeed-MII 上实现了 HCache，总计 5731 行 CUDA、C++ 和 Python。主实验平台是 4 张 A100-40GB SXM4、两颗 AMD EPYC 7642、256 GB 内存，以及 4 块 Samsung PM9A3 4 TB SSD。模型覆盖 Llama2-7B、Llama2-13B、OPT-30B；工作负载用 ShareGPT4 模拟多轮对话，用 L-Eval 覆盖长上下文任务。

结果基本撑住了论文主张。在 ShareGPT4 上，HCache 相比 KV offload 带来 1.27-1.90x 的 TTFT 提升，相比 token recomputation 则是 2.21-3.57x；对 7B 和 30B 模型，它还能把可承载请求数再抬高最多 11%。TBT 与理想系统相比最多只高 4%。在 L-Eval 的代表性任务上，HCache 相比 KV offload 有 1.62-1.93x 的 TTFT 改善，相比 recomputation 有 2.66-5.73x。存储占用也明显下降：7B、13B、30B 的每 token 状态大小分别从 256/400/672 KiB 降到 132/210/280 KiB，也就是 1.92-2.40x 的下降。消融也说明系统细节确实重要：没有 bubble-free scheduler 的 HCache-O，在 I/O 充足的平台上会比 KV offload 慢 13%；若直接把 hidden state 写 SSD，Llama2-7B 在 batch size 16 时 TBT 会高出 34%。

## 创新性与影响

这篇论文真正新的地方，不在于又做了一个 tiered cache，而在于它先改了 cache miss 时要恢复的状态表示。过去很多 stateful LLM 系统默认 KV cache 就是唯一该保存、该搬运的对象，优化主要集中在 placement；HCache 则把问题改写成：能不能先保存一种更便宜的状态，再在最后一步把 KV 还原出来？这是机制层面的变化，而 scheduler 与 chunk layout 则让它变成可用系统。对多轮对话、长上下文助手、SSD-backed LLM serving 来说，这个视角都很有价值。

## 局限性

HCache 的收益建立在 cache miss 足够多这一前提上。如果 GPU 侧热数据已经被 LRU 缓住，大部分请求根本不需要恢复，那么它能发挥的空间自然会变小。论文自己的 Zipfian 实验里，当 hit ratio 升到 94% 时，HCache 仍比 KV offload 快，但优势只剩 1.15x。另一个现实约束是，它不是一个固定配方；调度器依赖离线 profiling，不同 GPU 与存储带宽配比下，hidden state、KV offload、token recomputation 的分层方案都得重新算。再加上实现建立在 DeepSpeed-MII 上、实验模型只有三种、主打场景集中在 16K 上下文，说明它离通用结论还有一段距离。GPU 缓存管理、压缩和 admission policy 也都仍是正交问题。

## 相关工作

- _Gao et al. (ATC '24)_ - AttentionStore/CachedAttention 直接把整份 KV cache 放到分层存储里；HCache 的区别在于先把保存对象改成 hidden states，再在 miss 时重建 KV。
- _Gim et al. (MLSys '24)_ - Prompt Cache 优化的是 GPU 常驻命中路径里的 prompt 复用，而 HCache 解决的是状态已经离开 GPU 之后的 cache-miss 恢复路径。
- _Jin et al. (arXiv '24)_ - RAGCache 关注检索型工作负载里的多层 KV placement；HCache 则假设 miss 迟早会发生，并把恢复动作本身做得更便宜。
- _Liu et al. (SIGCOMM '24)_ - CacheGen 通过压缩和流式传输来降低 KV 搬运成本；HCache 是无损方案，它避免了一开始就去搬完整 KV 对象。

## 我的笔记

<!-- 留空；由人工补充 -->
