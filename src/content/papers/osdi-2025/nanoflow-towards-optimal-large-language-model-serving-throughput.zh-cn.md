---
title: "NanoFlow: Towards Optimal Large Language Model Serving Throughput"
oneline: "NanoFlow 把 LLM serving batch 切成自动搜索出的 nano-batch，让 compute、memory 与 network kernel 在单 GPU 内重叠执行，而不是顺序互相等待。"
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

NanoFlow 的核心判断是：现代多 GPU LLM serving 从端到端看通常是 compute-bound，而不是很多人直觉里的 memory-bound，哪怕 decode attention 很吃带宽、tensor parallel 也会引入通信。它因此把一次 serving iteration 拆成更小的 nano-batch，让来自不同 nano-batch 的 compute、memory 和 network kernel 在同一张 GPU 上重叠执行。对 8xA100 上的 LLaMA-2-70B，这样做把吞吐显著拉高到现有 serving engine 之上，并达到论文推导最优值的 68.5%。

## 问题背景

这篇论文面对的是高并发在线 LLM serving。这里 throughput 直接决定单位 token 成本，也决定平台要为同样请求量准备多少稀缺 GPU。此前系统通常围绕最显眼的瓶颈做优化：模型参数很大、KV cache 很大、decode attention 每轮都要读取请求私有状态，所以人们自然会把 LLM serving 看成一个 fundamentally memory-bound 的问题。相应地，很多方案把主要精力放在 KV 管理、chunked prefill、batching policy 或离线缓存上。

NanoFlow 的起点是，这个叙事只看单个 kernel，没看完整的一次 serving iteration。现实部署里，KQV projection、FFN GEMM 这类 dense transformer operation 往往运行在由 prefill token 和 decode token 共同组成的大 batch 上，因此权重加载被摊薄，dense operation 反而变成 compute-bound。tensor parallel 带来的 all-gather/all-reduce 以及 decode attention 当然仍然存在，但在带有 NVLink 级互联的现代 accelerator 上，它们通常不是全局最慢的那一环。论文的 cost model 和在 LLaMA-2-70B 上的测量都显示，现有系统之所以吞吐不高，不是因为每个 kernel 本身写得很差，而是因为 compute-bound、memory-bound、network-bound 阶段在设备内被顺序执行。

这种顺序执行会制造大量空洞。decode attention 可能已经把 memory bandwidth 用得不错，collective 也可能把互联链路打满，但它们运行时 tensor core 却基本闲着。于是像 vLLM、DeepSpeed-FastGen、TensorRT-LLM 这样的系统，都会明显落在硬件理论上限以下。NanoFlow 要解决的，不是“让某个 operation 更快”，而是“让真正限制总吞吐的资源在整个 pipeline 里尽量一直有活干”。

## 核心洞察

论文最值得记住的一句话是：如果 serving 从整体上看是 compute-bound，那么为了换取更多 overlap，适度增加一些重复工作是值得的。NanoFlow 的做法，就是把原本的大 batch 切成多个更小的 nano-batch，再把原本的大 operation 复制成多个 nano-operation。因为这些 nano-batch 彼此独立，一个 nano-batch 上的 compute-heavy GEMM，就可以和另一个 nano-batch 上的 memory-heavy decode attention、或者 network collective 同时执行。

这是一个很有意识的 tradeoff。nano-batching 会削弱大 batch 的摊销效应，也会让部分权重被重复加载；如果 memory traffic 才是真正瓶颈，这当然是坏事。但如果 compute 才是全局瓶颈，那么更合理的目标就不是让每一步都最省，而是让 compute 尽可能一直忙碌，并把新增的 memory/network 工作隐藏在它后面。换句话说，NanoFlow 把优化目标从“最小化每个 stage 的代价”改成了“最大化限制整条 pipeline 的那种资源的利用率”。

## 设计

NanoFlow 先从一个 serving cost model 出发。论文把 dense projection 与 FFN 归类为主要 compute-bound，把 decode attention 归类为 memory-bound，把 tensor parallel collective 归类为 network-bound。基于最大可容纳的 dense batch size，它分别推导 memory、compute、network 三种视角下的 latency，并据此说明：在采用 GQA、能够形成较大 dense batch 的现代模型里，常见 workload 往往落在 compute-bound 区间。作者随后在 8 张 A100 上对 LLaMA-2-70B 做了验证：大多数 operation 的实测时间和模型判断基本一致，总体上也是 compute time 大于 memory 与 network time。

系统的核心机制是 nano-batching。一个原本在整个 dense batch 上运行的 parent operation，会被拆成两个或更多 nano-operation，每个只处理一段不重叠的 token 区间。只有当两个 parent operation 本来存在依赖，并且它们操作的 token 区间相交时，对应 nano-operation 才保留依赖。这给调度器带来了新的自由度：它不再需要等一个 full-batch stage 整体结束，才能开始下一个 stage，而是可以在同一设备内重叠不同资源类型的工作。对 70B 量级模型，自动生成的 schedule 通常会在 KQV 和 decode attention 附近使用四个 nano-operation，因为那里 compute、memory、network 三种压力同时存在；到后半层结构更简单时，再收缩成两个 nano-operation。

真正困难的是怎么找到这样的 schedule。NanoFlow 的主要系统贡献，就是一个两阶段、基于 MILP 的 auto-search。第一阶段忽略 kernel interference，只决定 nano-operation 的数量、batch size 和执行顺序，同时保持依赖正确、限制无意义的同类资源重叠，并探索 AG/AR 之间的等价变换。第二阶段把结构固定下来，再引入实测 interference 重新分配资源。由于 GPU 并不直接暴露 compute、memory、network 的可分数控制，NanoFlow 用 compute kernel 的 slowdown 作为代理资源份额 `R`，离线 profile GEMM、GEMV、network kernel 的两两重叠，把每个 `R` 映射到真实可得到的性能 `P`。这样一来，搜索器就能在不穷举所有 kernel 组合的前提下，处理非线性的 overlap 取舍。

运行时部分负责把搜索结果真的落到 CUDA stream 上。系统维持固定大小的 dense token batch，优先服务尚未完成的 decode request，再用 chunked prefill 填满剩余容量。CPU 侧的 batch formation 会提前一个 iteration 异步执行，因此 GPU 不需要等调度器做完 bookkeeping。对多轮对话场景，NanoFlow 还会在 KQV generation 之后立刻把新增 KV vector 异步下刷到 host/SSD 层级缓存，之后再先加载到一段连续的 GPU staging buffer 中，再 scatter 回 paged KV layout。

## 实验评估

核心评估平台是一个 8xA100 80 GB DGX 节点，使用 FP16 推理，主模型是 LLaMA-2-70B，比较对象为 vLLM、DeepSpeed-FastGen 和 TensorRT-LLM。工作负载既包含固定输入输出长度，也包含来自 Splitwise、LMSYS-Chat-1M、ShareGPT 的真实 trace。论文还额外评估了 LLaMA-3-70B、LLaMA-3-8B、Qwen2-72B、Deepseek-67B、Mixtral 8x7B，用来说明方法并不局限于单一模型结构。

最重要的结果是 throughput。在 trace-driven workload 上，NanoFlow 的平均吞吐分别达到 vLLM 的 4.18x、DeepSpeed-FastGen 的 3.45x，以及 TensorRT-LLM 的 1.91x；后者也是论文里最强的 baseline。对主设置 LLaMA-2-70B，它在最佳情况下拿到 1212 tokens/s/GPU，而论文推导的理论最优值是 1857 tokens/s/GPU，也就是达到 68.5% 的 optimal throughput。消融实验也让机制显得可信：单独使用 nano-batching 会让吞吐下降 13.2%，但一旦把 network-bound work 重叠进去，这部分损失不仅能补回来，还能继续提升；同时重叠 network 和 memory work 时，相对不做 overlap 的 nano-batch baseline 还能再快 1.17x。资源轨迹进一步解释了原因：compute utilization 从顺序 pipeline 下的大约 40% 提升到了 NanoFlow 下的大约 68.5%。

论文也没有回避 latency。由于 NanoFlow 为了吞吐会坚持较大的 dense batch，所以在低负载下它的 latency 会略高于最优 baseline。但随着请求率上升，它能在同样的 normalized-latency 目标下承受更高负载。以 LMSYS-Chat-1M 为例，在论文采用的 200 ms/token SLO 下，NanoFlow 能承受的 request rate 是 TensorRT-LLM 的 1.64x。接近峰值负载时，它的 99 分位延迟也只有平均值的 1.07x，这和固定 batch 的执行方式有关。对其他模型，论文报告 NanoFlow 自动生成的 pipeline 大致能达到理论最优值的 50% 到 72%。

## 创新性与影响

和 Orca、vLLM、Sarathi-Serve 这一类工作相比，NanoFlow 把优化粒度推进到了 serving iteration 的内部。此前系统会在请求层做 continuous batching、在内存层做 PagedAttention、或者在 prefill/decode 层做解耦，但大多仍把每个 operation 当作一个不可拆分的 full-batch stage。NanoFlow 则把“同一设备内异构 kernel 的重叠执行”提升成首要优化目标。

这点之所以重要，是因为它把一个系统层面的论点和一个可执行 runtime 真正接上了。论文不只是说“LLM serving 常常是 compute-bound”，而是先给出 throughput bound，再解释为什么现有 engine 达不到，再给出一套 search + runtime，把差距明显缩小。后续做 throughput-oriented LLM inference 的工作，很可能都会引用 NanoFlow 的两个贡献：一是它对 compute-bound serving 的重新定性，二是它证明了 intra-device scheduling 的重要性并不低于 cluster-level batching 和 routing。

## 局限性

NanoFlow 的前提是 workload 确实处在 compute-bound 区间。论文自己的分析也给出了反例：对较小模型配合很长 decode 的 workload，系统会重新逼近 memory-bound，此时重复加载权重就更难被隐藏。这意味着 NanoFlow 并不是对所有 serving 场景都优于 memory-centric 优化；它最适合的是大模型、可形成大 batch、运行在数据中心级 GPU 上的场景。

它的 auto-search 也依赖若干 profile 假设。系统用两两 interference 来近似真实重叠行为，并假设 `R` 到 `P` 的映射在很多 shape 上都足够稳定。这是务实的工程近似，不是形式化保证。如果未来 GPU 调度机制变化，或者 workload 分布明显漂移，NanoFlow 就需要重新 profile、重新搜索。最后，即便引入了这么多机制，主设置里它仍只达到论文理论最优值的大约三分之二，说明 interference、调度开销和剩余 pipeline bubble 依然没有被完全解决。

## 相关工作

- _Yu et al. (OSDI '22)_ - Orca 把 generative serving 的 continuous batching 做到了请求/iteration 粒度；NanoFlow 则进一步深入到单设备内部，在 operation 粒度重叠异构 kernel。
- _Kwon et al. (SOSP '23)_ - vLLM 的 PagedAttention 主要解决 KV-cache 的内存效率问题；NanoFlow 接受类似的 paged 前提，但重点是消除顺序执行留下的 compute bubble。
- _Li et al. (OSDI '23)_ - AlpaServe 研究的是跨请求、跨副本的 statistical multiplexing 和 model-parallel serving；NanoFlow 优化的则是单个 serving instance 内部的执行 pipeline。
- _Sheng et al. (ICML '23)_ - FlexGen 依赖激进的 offloading 让受限硬件也能跑大模型推理，而 NanoFlow 假设数据中心 GPU 资源充足，追求的是在线 serving 的最大吞吐。

## 我的笔记

<!-- 留空；由人工补充 -->
