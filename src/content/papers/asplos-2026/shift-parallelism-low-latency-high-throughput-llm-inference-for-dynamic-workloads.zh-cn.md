---
title: "Shift Parallelism: Low-Latency, High-Throughput LLM Inference for Dynamic Workloads"
oneline: "在不搬动 KV cache 的前提下于 sequence parallelism 与 full tensor parallelism 之间切换，让同一套 LLM 服务同时兼顾低负载低延迟和高负载高吞吐。"
authors:
  - "Mert Hidayetoglu"
  - "Aurick Qiao"
  - "Michael Wyatt"
  - "Jeff Rasley"
  - "Yuxiong He"
  - "Samyam Rajbhandari"
affiliations:
  - "Snowflake, Menlo Park, California, USA"
  - "Snowflake, Bellevue, Washington, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790219"
code_url: "https://github.com/snowflakedb/ArcticInference"
tags:
  - llm-inference
  - gpu
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Shift Parallelism 抓住了 LLM serving 里一个很难回避的现实：tensor parallelism 给单请求延迟，data parallelism 给纯吞吐，而现有系统通常只能二选一，或者把两套部署长期并存。论文的做法是把 sequence parallelism 适配到 inference，令它与 tensor parallelism 共享同一种 KV-cache 布局，然后根据 batch size 在线切换。结果是，同一套部署在低负载时能接近 TP 的延迟，在高负载时又能逼近 SP/DP 一侧的吞吐。

## 问题背景

这篇论文针对的是不会长期停留在单一工作点上的生产 LLM 推理负载。交互式 chatbot 或 agent loop 往往并发很低，更关心 `TTFT` 和 `TPOT`；而摘要、翻译之类 batch 作业会突发到来，更关心单位时间内总共处理多少 token。现实里的同一个模型服务，可能一天内同时经历这两种模式，甚至一分钟里就来回切换。

现有多 GPU 推理并行方式会把系统逼进一个不舒服的选择。Tensor parallelism（TP）把每层拆开，因此能降低单个请求的延迟，但层层都要做 all-reduce，综合吞吐会下降。Data parallelism（DP）跨请求天然并行，所以高流量下单位 token 成本最低，但它无法加速单个请求，对交互式场景并不友好。最直接的工程补丁是同时维护 TP fleet 和 DP fleet，再按请求类型路由，但这会重复占用容量，也会让生产运维复杂得多。

更值得追问的是：为什么不能让一套部署在 TP 和 DP 之间来回切换？论文的回答是，attention state 对不上。两者的 KV-cache 布局不兼容，中途切换意味着昂贵的数据搬运与同步。这就把问题限定得更具体了：不是“挑一个最优并行方式”，而是“找到一对性能互补、且共享 KV-cache 布局的推理并行方式”，这样系统才能在不重建请求状态的前提下动态切换。

## 核心洞察

论文最关键的洞察是：原本用于训练的 sequence parallelism（SP，也就是 Ulysses）恰好具备做这件事的结构条件。它像 DP 一样，比 TP 更有希望提升吞吐，因为它避开了 TP 那种 all-reduce 很重的 attention 路径；它又不像 DP 那样只能跨请求并行，而是也能在单个请求内部并行，因此对长 prompt 的 `TTFT` 有帮助。最重要的是，只要设计得当，它和 TP 可以共享不变的 KV-cache 布局，于是同一个请求状态可以在两种模式间直接存活下来。

但这并不意味着 SP 在所有时候都最好。低流量 decode 阶段的 batch 很小，SP 会因为负载不均衡而吃亏，甚至需要 padding 才能让所有 GPU 都有活干，这会拖慢 `TPOT`。因此 TP 仍然是小 batch、逐 token 生成延迟最关键时的正确模式。论文真正的命题不是“用 SP 替代 TP”，而是“把 SP 当成高 batch 下的 base mode，把 TP 当成低 batch 下的 shift mode，然后按 batch size 切换”。让这一切成立的关键，就是 KV-cache invariance：只要 cache 和 head ordering 在两种模式间保持一致，系统就能响应流量变化而不用为 cache 重排付出大代价。

## 设计

这套设计分成两层。第一层是一个更通用的 inference-time SP 实现。作者把训练场景里的 Ulysses 扩展到推理环境，让它支持 Grouped Query Attention（GQA），在 SP 度数超过 KV head 数量时复制 KV cache，并处理低流量下的负载不均衡。对于装不进单卡、或者虽然能装进但留不出足够 KV-cache 空间的模型，作者还支持混合 `(SP, TP)` 的 base 配置。此时 TP 负责把模型放进显存，SP 则用剩下的 GPU 扩大有效 KV-cache 容量并抬高吞吐。

第二层才是 Shift Parallelism 本身。运行时同时维护两种配置：一个 base 配置，使用全 SP 或混合 `(SP, TP)`；一个 shift 配置，使用覆盖整节点的 full TP。每次 forward 时，系统先看当前 batch size 是否超过阈值。若 batch 大，就使用 base 配置，以优化 `TTFT` 和 combined throughput；若 batch 小，就切到 TP，以压低 `TPOT`。

想让切换真正便宜，关键在于数据布局控制。论文指出，即便名义上切的是同一组 attention heads，任意 `(SP, TP)` 与 full TP 的组合也不会自动保留 head ordering。为了解决这个问题，shift 配置在加载 QKV shard 时，会遵循 base 配置里的 SP-aware head 顺序。这样，KV cache 在两种模式之间就是一致的。对模型权重，作者最终选择的是显式复制，而不是运行时按需切片：base model 和 shift model 各自独立加载，但共享同一份 KV cache。额外内存成本是 base model 权重的 `1/SP`，因此 base 模式里的 SP 度数越高，这部分复制成本越低。

实现上，这不是一个全新的推理 runtime，而是通过 plug-in 方式集成进 vLLM。两套模型分别做编译与 CUDA graph capture，再按当前模式回放。这一点很重要，因为论文的目标不是只展示一个算法，而是证明动态并行切换可以现实地嵌进现有 serving 栈。

## 实验评估

实验主要围绕单节点 `8xH200` 部署展开，软件基线是 vLLM 加上作者实现，主力模型是 FP8 的 `Llama-70B` 和 `Qwen-32B`，另外还扩展到两个稀疏 MoE 风格模型。最干净的 latency-throughput 对比来自 Figure 12。对于 `Llama-70B`，Shift Parallelism 的 TTFT 是 `102 ms`，而 TP 是 `159 ms`，DP 是 `614 ms`。它的 TPOT 是 `10.1 ms`，几乎贴着 TP 的 `9.34 ms`，但明显优于 DP 的 `22.5 ms`。在 combined throughput 上，它达到 `37.4k tok/s`，远高于 TP 的 `24.7k tok/s`，但仍低于 DP 的 `45.9k tok/s`。这恰好对应论文的主张：它不是在所有指标上全面压过 DP，而是在单一部署里把 TP 和 DP 的取舍明显拉平。

合成 bursty trace 更能体现实际价值。在那个实验里，Shift Parallelism 的 median TTFT 是 `148 ms`，而吞吐优化的 DP 是 `1,355 ms`，延迟优化的 TP 甚至达到 `3,930 ms`；与此同时，它的 peak throughput 仍有 `69,147 tok/s`，接近 DP 的 `75,535 tok/s`，明显高于 TP 的 `51,162 tok/s`。换句话说，系统愿意为纯 batch 场景下略逊于 DP 的峰值吞吐付出一点代价，换来在 burst 和 interactive 请求混合时避免延迟彻底爆炸。

真实 trace 的结论也一致。Azure code trace 上，Shift Parallelism 在 TTFT、TPOT 和 completion-time 分布上都是最好的。Mooncake conversation trace 上，TP 和 DP 在单节点内都跟不上请求，队列等待时间会不断累积；只有 SP 和 Shift 在启用 FP8 KV cache 后还能把工作负载维持住。我认为这组实验对论文核心论点的支撑是充分的，尤其因为对比是在同一个 vLLM 系统底座上完成的。不过作者也坦承 vLLM 本身有明显框架开销，因此高吞吐场景下与 DP 之间剩余的差距，并不全是并行机制本身造成的。

## 创新性与影响

和把 prefill、decode 拆到不同 worker 的 serving 工作相比，Shift Parallelism 走的是另一条路：保留单一部署，保留本地 KV cache，不去改阶段放置，而是改节点内部的并行方式。和 Ulysses 本身相比，这篇论文的创新也不只是“把 SP 搬到 inference”；真正的新意在于，它证明了 inference-time SP 可以被扩展到足够通用，并且能与 TP 共享 KV 状态，从而组成一对可动态切换的并行模式。

因此，这篇论文最可能影响两类人：一类是做生产级多 GPU LLM serving 的工程团队，另一类是研究动态需求下延迟-成本权衡的系统研究者。它是机制论文，但同时也有很强的部署观点：动态流量不应该迫使运维团队永久维护两套分离的 TP/DP fleet。

## 局限性

论文并不声称 Shift Parallelism 在所有指标上都优于所有基线。纯高流量吞吐仍然是 DP 最强，因为 Shift 依旧要做并行 attention，因此仍然承担通信开销。除此之外，这个设计也带来额外内存与工程成本：shift model 复制了 `1/SP` 的权重，两套配置都要单独编译和 graph capture，还需要人为选定切换阈值。

实验范围也主要集中在单节点和稠密模型。稀疏模型部分的结果很有希望，但作者明确表示 expert parallelism 仍是未来工作。同样，最强的结果都建立在 `8xH200` 与作者的 vLLM plug-in 栈之上。论文并没有真正研究多节点 serving、fleet-level routing，或者阈值应该如何随着流量分布漂移而在线调整。论文也没有给出一个能自动学习阈值的控制器。

## 相关工作

- _Patel et al. (ISCA '24)_ — Splitwise 通过把 prefill 和 decode 拆到不同 worker 来分别优化两个阶段，而 Shift Parallelism 保持单节点 serving 栈不变，改的是多 GPU 并行方式而不是阶段放置。
- _Qin et al. (FAST '25)_ — Mooncake 采用以 KV cache 为中心的 disaggregated 架构，而 Shift Parallelism 刻意避免远程 KV 传输，依赖的是 SP 与 TP 之间共享的本地 KV 布局。

## 我的笔记

<!-- 留空；由人工补充 -->
