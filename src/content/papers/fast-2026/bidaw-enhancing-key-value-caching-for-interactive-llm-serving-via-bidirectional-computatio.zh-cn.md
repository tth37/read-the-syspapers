---
title: "Bidaw: Enhancing Key-Value Caching for Interactive LLM Serving via Bidirectional Computation–Storage Awareness"
oneline: "Bidaw 让调度器区分快慢 KV 加载，并用上一轮回答长度预测未来复用，让主存/SSD 两层 LLM 缓存更接近全内存上界。"
authors:
  - "Shipeng Hu"
  - "Guangyan Zhang"
  - "Yuqi Zhou"
  - "Yaya Wei"
  - "Ziyan Zhong"
  - "Jike Chen"
affiliations:
  - "Tsinghua University"
  - "China University of Geosciences Beijing"
  - "China Telecom Omni-channel Operation Center"
conference: fast-2026
category: ai-era-storage
tags:
  - llm-inference
  - caching
  - scheduling
  - memory
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Bidaw 是一个面向交互式 LLM serving 的两层 KV 缓存系统，把历史状态放在主存和 SSD 上，而不是假设有一个足够大的 DRAM 池。它的关键做法是让计算与存储交换预测信号：调度器先看每个请求的 KV 在哪一层、大小是多少，淘汰策略则利用上一轮模型回答去预测该 KV 何时会再次被访问。在作者的交互式工作负载上，Bidaw 最多把响应延迟降低 `3.58x`，把吞吐提升 `1.83x`，明显逼近“所有 KV 都在主存里”这一理想上界。

## 问题背景

这篇论文处理的是多轮交互式 serving，而不是离线批推理。每一轮用户新问题都依赖此前所有对话轮次的 KV，才能维持上下文一致性；但 GPU 显存又不足以把这些历史状态长期保留在卡上。于是，如果每轮都把整段历史重新算一遍，代价会迅速失控。论文给出的生产风格工作负载里，单个用户平均会话轮数达到 `22.4`，而重复计算最多占到总计算量的 `93.1%`。

看起来直接的替代方案，是把历史 KV 放进一个两层存储里：主存做性能层，SSD 做容量层。CachedAttention 和 FlashGen 已经这样做了，但论文表明它们离理想情况仍有很大差距。和“所有 KV 永远都能从主存命中”的模拟上界相比，现有两层方案的响应延迟最高会大 `3.8x`，吞吐最高会低 `2.0x`。问题不是 SSD 天生不适合，而是现有系统把计算调度和存储管理当成两个互不知情的模块。

这种割裂带来两类损失。第一，KV 加载时间差异很大，因为不同请求的历史长度不同，而主存和 SSD 的带宽又相差悬殊。一个 KV 只在 SSD 上的大请求，很容易把 GPU 卡住；后面那些 KV 已经在主存里的请求，也只能排队干等。第二，只看过去访问顺序的淘汰策略，看见的是很差的时间局部性。论文在 `200 GB` 主存配置上测得，`80%` 的 weighted reuse distance 都超过主存容量；即便性能层平均已经容纳了约 `40.1%` 的 KV，常见策略的命中率也只有约 `20%`。因此，这篇论文真正要解决的是：在不依赖 RDMA disaggregated memory、也不依赖有损压缩的前提下，怎样让两层 KV 缓存更像一个“全内存系统”。

## 核心洞察

论文最重要的主张是，交互式 serving 在计算和存储边界两侧都暴露了可利用的“未来信息”，系统应当双向利用这些信息。对计算侧来说，在请求真正占用 GPU 之前，调度器就已经知道这个请求的 KV 放在主存还是 SSD、加载代价大概有多高。对存储侧来说，serving 引擎掌握了普通 cache 看不到的信息：它刚刚生成的模型回答有多长，而这个长度会强烈影响同一用户下一轮请求何时到来。

后一条尤其关键。Bidaw 观察到，KV 下一次访问的 weighted reuse distance 下界，会随着上一轮回答长度增长而上升，因为更长的回答意味着用户要花更久去阅读、理解，并组织下一轮提问，在这段间隔里其他用户的请求会继续插队到前面。论文在 12 个时间窗口、多个到达率设置下，报告了 `0.94-0.98` 的 Spearman 相关系数。也就是说，这里不只是一个传统 cache replacement 问题，而是一个“人在回路中”的访问模式问题；模型自己的输出，本身就是预测下一次访问的重要线索。

## 设计

Bidaw 的控制路径从请求到达开始。计算引擎先查看该请求的历史张量当前位于哪一层，然后把请求分到两个队列里。若 KV 已在性能层中，请求进入 `ready queue`；若 KV 只在 SSD 中，请求进入 `preparing queue`，先等待被加载回主存后再提升。GPU 只从 ready queue 取任务，因此慢速 SSD 读取不会再阻塞那些 KV 已经热在主存里的请求。为了保持 FCFS 风格的公平性，Bidaw 在请求从 preparing queue 晋升时，按原始到达时间而不是晋升时间插回 ready queue。

preparing queue 需要另一套策略，因为 SSD 上请求的服务时间差异非常大。Bidaw 引入了 `disk-HRRN`，这是 Highest Response Ratio Next 的存储感知变体，优先级定义为 `1 + waiting_time / KV_size`。这个公式会优先提升较小的 KV，因为它们更快被搬回主存、能更早解除排队；同时，等待时间项又会逐步提高大 KV 请求的优先级，避免饥饿。于是整个调度器形成了混合结构：一旦 KV 就绪，按 FCFS 语义进入 GPU；在仍受存储约束时，则按大小和等待时间联合排序。

淘汰路径同样是跨层的。Bidaw 为每个用户维护过去 weighted reuse distance 的统计，并持续跟踪模型最新回答的长度。系统先根据回答长度估计下一次访问 reuse distance 的下界，再在后台维护一个 ghost cache，用过去 trace 模拟最优策略，得到不同 reuse-distance bucket 的命中率估计：一个必命中的 small bucket、若干超过主存容量但仍有命中潜力的 promising buckets，以及命中率近似为零的 extreme bucket。随后，Bidaw 把每个用户过往访问落入各 bucket 的概率分布，与“回答长度给出的下界约束”合并，得到该用户下一次访问的 overall hit potential。主存紧张时，就优先把 hit potential 最低的 KV 淘汰出去。

数据路径上还有几个很关键的实现细节。Bidaw 采用 inclusive caching，因此 SSD 中始终保留一份副本，淘汰时不会产生昂贵写流量。系统使用 continuous batching，并配套一个 mix-grained GPU allocator：历史 token 和输入 token 用 `256` token 的大块，生成 token 用 `16` token 的小块，同时支持大小块之间的拆分和回收合并，以兼顾带宽利用和碎片控制。最后，论文观察到，对 MHA-based 模型而言，“直接缓存 KV”并不总是最划算的。它在多种中间张量里找到了 saved-compute-per-byte 最高的对象，也就是“normalized activation”（文中称 `tensor 6`），于是把它作为真正写入两层存储的 history tensor，在需要时再通过一个低优先级 CUDA stream 重建出 KV。作者也明确说明，这个优化适用于 OPT、Qwen、Llama、Bloom 一类 MHA 模型；对 GQA 模型，直接缓存 KV 仍然更合适。

## 实验评估

实验同时使用了私有大规模 trace 和公开工作负载。主要结果来自一个工业合作方提供的交互式会话 trace，总计超过一百万轮对话，平均 query 长度 `36`，平均 response 长度 `45`，平均轮数 `22.4`。硬件环境是一张 `80 GB` A800、一台带 `200 GB` 主存的主机，以及经 PCIe 4.0 连接的 `1.5 GB/s` SATA SSD RAID-5 阵列。模型包括 `OPT-6.7B`、`Qwen-7B`、`OPT-13B`、`Qwen-14B` 和 `OPT-30B`。对比对象是 `vLLM`、`CachedAttention`、`FlashGen`，外加一个“所有 KV 都从主存读取”的模拟上界。

最重要的结果基本支撑了论文论点。跨不同模型，Bidaw 在相近延迟下可支撑 `1.43x-1.83x` 更高的用户到达率；在 `OPT-13B` 上，平均响应延迟最高降低 `3.58x`。机制层面的诊断也对得上：新淘汰策略相对 CachedAttention 的 queue-enhanced 策略，最多把 miss rate 降低 `57.6%`，相对常见通用策略最多降低 `69.9%`；I/O-aware scheduler 则把平均排队时间从 `5.76 s` 压到 `2.45 s`，降幅 `57.5%`。尾延迟同样改善明显：在 `OPT-30B` 上，Bidaw 相对 CachedAttention 把 P99 降低 `47.03%`，相对 FlashGen 降低 `56.81%`。

我认为这套评估总体是有说服力的，因为它确实对准了论文宣称的最优区间：低并发、真人节奏、多轮、单机交互式 serving。论文还做了一个有价值的 sanity check：即便把 SSD 在模拟中加速到 `5 GB/s`，收益也不会消失。以 `OPT-13B` 为例，FlashGen 的吞吐从 `15.18` 提升到 `20.23` 用户/分钟，但仍明显低于 Bidaw 的 `27.81` 到 `30.35`。最大的保留意见是，CachedAttention 和 FlashGen 因为闭源，作者是基于 vLLM 自行重实现的，所以这些比较虽然有参考价值，但并不是完全严格的 apples-to-apples。

## 创新性与影响

相对于 _Gao et al. (ATC '24)_ 和 _Jeong and Ahn (ASPLOS '25)_，Bidaw 的创新点不只是“又一个 KV cache”，而是明确提出调度器和淘汰器都应该消费来自另一侧栈层的信息：存储延迟要反过来影响请求顺序，而模型回答则要反过来影响 replacement decision。相对于 _Qin et al. (FAST '25)_，它瞄准的是比 RDMA-based disaggregated memory 更便宜、更本地化的部署点。相对于 _Gao et al. (EuroSys '25)_，它也不只是把 activation caching 当作恢复技巧，而是进一步把“缓存哪种历史张量”提升为一个计算节省与存储占用之间的优化问题。

因此，这篇论文对本地或私有化交互式 serving 尤其有价值，特别是在那些难以证明自己值得搭建专用 memory pool 的垂直行业里。它更可能产生的是工程上的影响，而不是概念上的重构：做 chatbot appliance、私有部署堆栈或行业大模型平台的人，可以直接借用它的跨层调度和 answer-informed eviction 思路，即使不照搬完整实现。

## 局限性

Bidaw 最强的前提，是工作负载确实具有人类交互节奏。它的 answer-length predictor 之所以有效，是因为更长的回答会推迟下一轮提问；如果请求来自自动 agent、脚本化 pipeline，或者高度突发的机器流量，这种相关性就可能明显减弱。论文在 ShareGPT 实验里其实已经暴露了这个问题：由于时间戳是按 Poisson 过程补出来的，previous-answer-based eviction 的收益就远不如真实交互 trace。

系统层面也还有边界。实验全部在单节点、单 GPU 上完成，因此对多 GPU serving、租户干扰和数据中心级调度器能说明的内容有限。storage-efficient tensor 这个优化也不是普适的，GQA 模型就应该直接缓存 KV。并且，系统需要维护后台 ghost cache 与每用户 reuse 统计，在论文的规模下开销很小，但如果用户规模更大、内存预算不同，工程复杂度会继续上升。最后，由于基线来自作者重实现，当前结果仍然残留一点“算法收益”和“实现质量收益”难完全拆分的空间。

## 相关工作

- _Gao et al. (ATC '24)_ — CachedAttention 为多轮 serving 引入了 queue-aware eviction 和 proactive loading，但 Bidaw 认为仅靠等待队列信息，仍然看不到 SSD 服务差异和回答长度带来的用户思考时间。
- _Jeong and Ahn (ASPLOS '25)_ — FlashGen 通过资源管理减少多轮对话中的重复计算，而 Bidaw 进一步加入了显式的 storage-latency-aware scheduling 和跨层淘汰预测。
- _Qin et al. (FAST '25)_ — Mooncake 用 RDMA-backed disaggregated memory pool 做 KV 复用，Bidaw 则针对成本更低的本地主存/SSD 层次结构。
- _Gao et al. (EuroSys '25)_ — HCache 从中间激活恢复 serving 状态，Bidaw 则沿着这条线继续追问：在两层 I/O 约束下，究竟缓存哪一种 history tensor 最划算。

## 我的笔记

<!-- 留空；由人工补充 -->
