---
title: "BlitzScale: Fast and Live Large Model Autoscaling with O(1) Host Caching"
oneline: "BlitzScale 通过计算网络多播模型参数，并让部分加载完成的实例先执行已就绪层，把 LLM 扩缩容从停机式加载变成只需每个模型一份 host 缓存的活体扩容。"
authors:
  - "Dingyan Zhang"
  - "Haotian Wang"
  - "Yang Liu"
  - "Xingda Wei"
  - "Yizhou Shan"
  - "Rong Chen"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Huawei Cloud"
conference: osdi-2025
code_url: "https://github.com/blitz-serving/blitzscale"
tags:
  - llm-inference
  - gpu
  - networking
  - datacenter
  - caching
category: llm-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

BlitzScale 的做法是把已部署 GPU 和集群内唯一一份 host 缓存都当成参数源，通过 RDMA 与 NVLink 多播权重，而不是等 SSD 加载或赌每台机器都命中本地缓存。它进一步把扩容从“等整实例装满再上线”改成“哪几层先到就先用哪几层”：新实例只要拿到前几层，就能先执行这些层，再把 activation 交回旧实例继续算。这样做在真实 trace 上显著降低了 ServerlessLLM 的 TTFT，同时也减少了为维持同等服务质量所需的 GPU 时间。

## 问题背景

论文关注的是同时托管许多大模型的 model-as-a-service 平台。这类平台不可能长期按峰值预留 GPU，只能在大多数时候维持平均所需实例数，再在突发流量到来时快速扩容。难点在于，真正伤人的不是缓慢的日周期变化，而是秒级突发。作者引用的工作负载中，请求率可以在两秒内增长 5 倍，而 LLM 的显存需求也会因为 decode 长度不可预测而大幅摆动。对聊天这类交互场景来说，哪怕只有几百毫秒的额外等待，也足以把尾延迟推过 SLO。

现有 autoscaling 方案主要输在两个地方。第一，数据面太慢。作者调查的 GPU 服务器里，SSD 到 GPU 的有效带宽只有每 GPU 2-10 Gbps，所以即便是 8B 模型，在 10 Gbps SSD 上也要 12.8 秒才能装入一张 GPU。第二，更快的 host-memory 加载又高度依赖本机缓存命中，而这在同时服务成百上千个模型的平台上很难稳定做到。ServerlessLLM 自己报告 host cache hit rate 只有 40%-75%；BlitzScale 在 BurstGPT 上进一步测到 miss rate 达到 20%-46%，而且一旦扩容涉及多台机器，miss 还会更多。更根本的问题是，这些方案全都是 stop-the-world：新实例必须等所有权重都到齐才能开始服务。对 72B 模型，论文指出若想把 SLO violation 压到 60% 以下，至少要有约 220 Gbps 的每 GPU 加载带宽；若想把停机时间压到 500 ms 以内，则需要 576 Gbps 每 GPU，这已经超出典型部署的能力。

## 核心洞察

论文的核心主张是，autoscaling 应该重用集群已经拥有的两样东西：一是平时没有被打满的计算网络，二是模型天然按层执行的结构。第一点成立，是因为 RDMA 和 NVLink 明显快于 SSD，而且作者测到，即便在 PD disaggregation 这种网络压力很高的 serving 场景里，计算网络的占用仍然很低。如果某个模型已经在别处运行，就可以直接从这些在线实例多播参数；如果当前没有运行实例，也只需要在整个集群里保留一份 host 缓存，因为网络多播可以把这一份同时发给多个新实例。

第二点成立，是因为推理本来就是逐层前进的。一个还没装完模型的新实例，不必等到“整模型齐备”才有价值；只要前几层已就绪，它就可以先执行这部分前缀，再把 activation 交还给旧实例去跑后续层。这样一来，原本纯粹的加载时间就被转化成了部分吞吐。换句话说，论文真正改变的不是“把整实例装得更快”，而是把扩容的最小进度单位从“完整实例”降成了“已加载层数”。

## 设计

BlitzScale 在原有 serving 栈上加入了四个关键控制组件：load monitor、global parameter pool、scale planner 和 live-execution scheduler。parameter pool 负责追踪每个模型当前位于哪些在线 GPU 和哪些 host DRAM。系统初始化时，会把每个模型的一份拷贝分散存到集群中的 host 上，保证任何时刻至少存在一个 host-backed 参数源。负载超过阈值时，monitor 决定要扩多少实例，planner 选择参数源和目标 GPU，scheduler 则负责扩容期间的请求执行。

网络侧设计建立在一个简化但够用的拓扑模型上。通过 NVLink 相连的 GPU 被视为一个 scale-up group，因为组内广播极快；跨机流量则被抽象成 leaf-spine RDMA 网络，并记录每个 GPU 的带宽与 leaf 标识。planner 首先剔除那些会和在线 serving 流量发生冲突的 source，然后贪心地构造若干 serial forwarding chain。之所以用 chain，是因为它天然适合大体量广播：中间节点一收到第一层，就能立刻往下一个节点转发，而源节点同时可以继续发第二层，从而把传输过程流水化。必要时，planner 会构造多条 chain，以绕开较慢的 inter-leaf 链路；在 PD disaggregation 场景下，多条 chain 还能避免参数流量与 KV-cache 流量撞在一起。如果 source 与 target 两侧都存有重复分片，BlitzScale 还会让每块 GPU 只发送自己的那一份，再由接收端用 NVLink AllGather 拼回完整参数，从而进一步缩短扩容时间。

live scaling 是另一半设计重点。BlitzScale 把过载的旧实例和一个仍在加载的新实例配对。系统会立刻把排队中的请求和新到请求都重定向到新实例；一旦第一层加载完成，新实例就先执行这一层，再把 activation 发回旧实例继续后续层。简单的 best-effort 做法仍会让旧实例成为瓶颈，因此论文提出了 ZigZag scheduling。它会有意识地延后旧实例上的部分工作，让新实例等更多层到齐后再承担更长的前缀，从而让流水线更平衡。作者既给出了一个 ILP 形式化，也给出了更实用的队列近似算法。对 LLM 的 PD disaggregation，BlitzScale 还引入了两个特化：一是当 prefill 需要扩容时同步预扩 decode；二是当直接 live-scale decode 一定会和 KV-cache 传输冲突时，先把部分 prefill instance 临时转成 decode，再补足 prefill 容量。

## 实验评估

系统实现大约 24 KLOC Rust/C++，底层 kernel 使用 FlashInfer。评估覆盖两套 GPU 集群、三种真实 trace，以及三种模型规模。Cluster A 是带 NVLink 的 A800 集群并配有 100 Gbps RDMA，适合跑 72B 的 tensor-parallel 实例；Cluster B 是 A100 PCIe 服务器。工作负载来自 BurstGPT、AzureCode 和 AzureConv；比较对象包括 ServerlessLLM、始终命中 host cache 的 AllCache 变体、DistServe，以及 vLLM。作者还把同一套 scaling policy 同时用于 BlitzScale 和 ServerlessLLM，并校准了 DistServe 在关闭 autoscaling 时与 BlitzScale 的表现，这让比较更可信。

最有说服力的结果，是 BlitzScale 在真正需要扩容的 bursty trace 上始终把延迟压得更低。以 72B 的 BurstGPT 为例，TTFT 相比 ServerlessLLM 缩短 75.5%，相比 AllCache 缩短 21.1%；TBT 分别缩短 7.4% 和 5.1%。论文还给出一个把 24B 模型扩到 6 个 prefill instance 的细粒度时间线。该实验显示，BlitzScale 在大约 500 ms 时就已经开始产出 token，因为 live path 已经能做有效工作；整个扩容在约 1.2 秒完成，而 AllCache 大约需要 2.0 秒。消融实验也基本支撑作者的论点：更快的网络加载在所有工作负载上都有帮助；多播优化在多实例同时扩容时收益更大；而 ZigZag 在网络较慢的 Cluster B 上最有价值，因为 live overlap 有更长时间发挥作用。

资源利用率方面，结论也与论文的中心论点一致。对比全量 over-provision 的 DistServe，BlitzScale 在满足同一 5x-SLO 目标的同时，只用了大约一半的 GPU 时间；对比平均配置的 DistServe，TTFT 和 TBT 分别缩短 95.8% 和 1%。相对 ServerlessLLM，BlitzScale 的 GPU 时间又少了 19.46%，host cache 使用也更低，因为它不需要把同一模型复制到许多 host 上。整体看，这些结果说明“集群级参数流动”加上“加载期间协作执行”确实同时改善了延迟和利用率，而不是单纯把压力从一个资源挪到另一个资源。

## 创新性与影响

和 ServerlessLLM 相比，BlitzScale 不是“更激进的缓存策略”。它真正的新机制，是用 cluster-wide parameter pool 加网络多播来替代对 per-host cache 的依赖，再通过按层协作执行，把加载时间转成可用吞吐。和 PipeSwitch 这类 loading overlap 相比，区别在于 BlitzScale 让新实例在尚不能独立完成请求时，就已经能为系统带来吞吐增益。这代表了一种不同的 autoscaling 抽象。

它的影响也相当直接。只要一个平台已经具备现代 LLM serving 集群常见的高速 GPU 互联，却又不愿意长期按峰值预留资源，BlitzScale 就提供了一条现实可行的路径。对 model-as-a-service 运营者、LLM serving 研究者，以及未来研究 elastic disaggregated inference 的系统工作来说，这篇论文都很可能成为重要参照，因为它把资源管理与推理执行结构真正耦合了起来，而不是把实例启动当成一个黑盒 cold start。

## 局限性

这套设计依赖若干并非处处成立的前提。它的 planner 建立在简化的 leaf-spine 网络模型上，并利用目标集群里“反向流量互不干扰”的性质来规避冲突；若真实部署的 fabric 行为不同，所谓 interference-free plan 的效果就可能打折。它的收益还依赖于集群里确实存在 spare GPU，以及计算网络平时没有被完全占满；在资源持续拉满的场景里，这些前提都可能失效。

一些限制则更贴近 LLM 本身。论文明确承认，在 PD disaggregation 下，decode instance 无法直接做无冲突的 live scaling，因此只能借助“把部分 prefill instance 变成 decode，再补 prefill”的绕路方案。autoscaling policy 也基本不在本文重点之内：阈值来自已有工作与离线 profiling，作者把更细致的策略设计留给了未来工作。最后，当一次只能扩很少的大实例时，多播优化的收益会变窄；例如 72B 的实验就无法充分覆盖“很多接收端同时扩容”这一最适合多播的情况。

## 相关工作

- _Bai et al. (OSDI '20)_ - PipeSwitch 可以把参数加载与执行重叠起来，但新实例在模型完全加载之前仍不能独立完成请求；BlitzScale 则进一步实现了加载过程中的协作式 live execution。
- _Jeong et al. (EuroSys '23)_ - Direct-host-access 加速的是 host-to-GPU 加载，而 BlitzScale 尽量避免反复走 host 路径，优先从在线 GPU 或集群内唯一一份 host 副本经多播装载参数。
- _Sun et al. (OSDI '24)_ - Llumnix 关注的是在已有实例之间动态调度和迁移 LLM 工作负载；BlitzScale 解决的问题则是如何把新实例上线得足够快，从而不必长期 over-provision。
- _Zhong et al. (OSDI '24)_ - DistServe 展示了 PD disaggregation 及其带来的重 KV-cache 网络流量；BlitzScale 则是在这一设定上继续加入 autoscaling，并显式处理扩容流量与 serving 流量之间的干扰。

## 我的笔记

<!-- 留空；由人工补充 -->
