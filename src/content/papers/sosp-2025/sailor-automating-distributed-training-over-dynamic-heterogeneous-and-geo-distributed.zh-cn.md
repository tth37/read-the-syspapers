---
title: "Sailor: Automating Distributed Training over Dynamic, Heterogeneous, and Geo-distributed Clusters"
oneline: "Sailor 把 GPU 分配、3D 并行计划与跨 zone 放置联合求解，并在资源动态变化时无杀进程地重配置 Megatron 训练。"
authors:
  - "Foteini Strati"
  - "Zhendong Zhang"
  - "George Manos"
  - "Ixeia Sánchez Périz"
  - "Qinghao Hu"
  - "Tiancheng Chen"
  - "Berk Buzcu"
  - "Song Han"
  - "Pamela Delgado"
  - "Ana Klimovic"
affiliations:
  - "ETH Zurich"
  - "MIT"
  - "HES-SO"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764839"
code_url: "https://github.com/eth-easl/sailor"
tags:
  - llm-training
  - gpu
  - scheduling
  - datacenter
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Sailor 的核心观点是：异构 GPU 和跨地域 GPU 只有在“资源选取、并行切分、阶段放置”被联合优化时，才真正能提升训练效率。它把 straggler 感知的 planner、更准确的内存/运行时间/成本 simulator，以及可执行异构计划并支持动态重配置的 Megatron-DeepSpeed 运行时组合成一个完整系统。

## 问题背景

论文从一个非常现实的云环境问题出发：高端 GPU 的大规模同构集群既稀缺，又会随时间波动。如果用户在一个 zone 里拿不到 32 张 A100，最直接的退路就是把 A100 和 V100 混用，或者把训练铺到多个 zone 上。但这个退路很容易适得其反。较慢的 GPU、更弱的链路和额外的数据传输费用，都会让“更多资源”变成更低吞吐或者更高成本。

现有系统并没有解决完整问题。许多 planner 假设资源分配已固定，只在 DP、PP、TP 上搜索。像 Metis、FlashFlex 这样的异构感知系统并不擅长处理多 zone 放置，而 DTFM、Atlas 这样的 geo-distributed 系统又没有把异构 GPU 类型与完整 3D parallelism 联合优化起来。结果要么是搜索空间过大，需要几分钟甚至几小时；要么是模型过于简化，无法正确处理 straggler、OOM 风险和通信成本。现有训练框架也不匹配：Megatron-DeepSpeed 假设全局统一的并行度，且不支持当资源增减时快速弹性重配置。

## 核心洞察

论文最重要的论断是，异构训练必须被视为一个耦合的联合优化问题，而不是“先选 GPU、再选并行计划”的两个独立决策。正确计划同时取决于 stage 级别的内存上限、不同 GPU 的计算速度、链路带宽、pipeline straggler，以及云上的跨区传输价格。只要这些因素建模得足够准确，就可以在真正部署前剪掉大量坏配置，并用 dynamic programming 配合少量领域启发式，把剩余搜索压缩到可接受时间内。

同样关键的是，这个计划必须真的能被执行。为此，Sailor 不只做 planner，还配套了一个训练运行时：它允许不同 pipeline stage 使用不同 tensor parallel 度，并且能在不整作业推倒重来的前提下重新规划。正是这种“planner + runtime”的结合，才把异构算力变成了可用算力。

## 设计

Sailor 由 profiler、planner、simulator 和修改后的训练框架四部分组成。profiler 会针对每种 GPU 节点类型，在单节点上测量每层在不同 microbatch size 和 tensor parallel 度下的 forward、backward、update 时间，同时记录参数规模、activation、中间状态内存，以及不同机器类型和消息大小下的带宽曲线。

planner 接收资源配额、当前可用资源、目标函数（例如最大吞吐或最小成本）以及可选约束（例如预算上限）。它会在 microbatch size、pipeline 度和 data parallel 度之间搜索，同时为每个 stage / GPU 类型预先计算避免 OOM 所需的最小 tensor parallel 度。为控制搜索规模，Sailor 使用了一组启发式：tensor parallelism 限制在单节点内；明显会 OOM 的配置提前剪枝；data parallel 度按目标函数隐含的顺序搜索；data parallel 副本限制在单 region 内；同一 region 内的多个 zone 在搜索中合并处理，因为它们的带宽相近。

在固定 pipeline 形状后，Sailor 用 dynamic programming 为每个 stage 选择资源组合。每个 stage 会得到若干副本，每个副本由 GPU 类型、tensor parallel 度和 region 构成。递推式会把当前 stage 与剩余 pipeline 一起评估，显式考虑 stage straggler、同步瓶颈，以及与下一 stage 之间的 pipeline 通信。若目标带预算约束，Sailor 会先近似假设当前 stage 是 straggler，在剩余预算下求解后续 stages；如果这个假设不成立，再用新 straggler 修正预算并迭代。

simulator 是 planner 的打分器。它按 worker 逐个估算内存，而不是假设所有 stage 都相同，并把参数、optimizer state、gradient、activation 以及通信相关内存都算进去。运行时间则采用 1F1B pipeline 模型，覆盖 warmup、steady state、cooldown，再加上 gradient synchronization 和 update 时间。它还会把 GPU 租用费用与跨 zone / 跨 region 的流量费用合并成单次迭代成本。最后，Sailor 扩展了 Megatron-DeepSpeed，使其支持不同 stage 使用不同 TP，并实现 kill-free elasticity：controller 监控资源变化、重新调用 planner、销毁通信组、重分区模型，然后从异步 checkpoint 恢复训练。

## 实验评估

simulator 的结果很强。对 GH200 同构集群上的 OPT-350M，Sailor 把平均内存估计误差压到 5.56%，运行时间误差压到 6%；而基线的平均内存误差大约在 12.5%-74%，运行时间误差在 10%-20%。在 Titan-RTX / RTX-2080 / RTX-3090 的异构集群上，Sailor 的平均运行时间误差为 4.5%，Metis 约为 28%，FlashFlex 约为 69%。

这些精度提升确实转化成了更好的计划。在 A100-only 的同构实验里，Sailor 的吞吐比最接近基线高 1.15x，对 Aceso 的优势最高可到 5.7x。在 A100+V100 的异构场景中，当两者数量相等时，Sailor 相对 AMP、FlashFlex、Metis 的吞吐优势达到 1.15x-2.03x；当 V100 更充足时，优势仍有 1.39x-1.57x。由于能避开负载不平衡和无效资源使用，它还把单次迭代成本最多降低了 2.67x。对 geo-distributed A100 训练，Sailor 在小规模真实集群上比 DTFM 快 1.9x-2.45x；在更大规模模拟里，吞吐提升达到 5.9x，同时单次迭代成本降低 9.48x。

不过，这些证据更有力地支持了 planner/simulator 的中心论点，而不是“已经在超大规模生产完全验证”的论点。论文确实提供了真实硬件验证和重配置微基准，但许多最大规模结果仍来自模拟，而且模型只覆盖 OPT-350M 和 GPT-Neo-2.7B。即便如此，它已经充分证明了一点：如果系统能把内存、straggler 和传输成本建模准确，那么异构与跨 zone 训练是可以变成收益而不是混乱的。

## 创新性与影响

相较前作，Sailor 的贡献在于端到端耦合。Varuna、Piper、Aceso 主要面向固定、同构集群上的并行优化；Metis 和 FlashFlex 进一步支持异构 GPU；DTFM 和 Atlas 则开始处理 geo-distributed 放置。Sailor 的独特之处在于它把这些能力合在一个系统里：异构 GPU 类型、多 zone 放置、带目标与约束的规划、按 worker 估算内存的 simulator，以及能够执行异构计划并在线重配置的运行时。

因此，这篇论文更重要的价值在于系统整合，而不是某个单点算法技巧。它为云训练平台和集群调度器提供了一张很具体的蓝图，告诉它们如何把碎片化的 GPU 供给转化为真正可用的训练容量，而不需要用户手工设计每一种退化配置。

## 局限性

论文有明显的范围边界。profiler 和 simulator 目前只面向 dense model，MoE 被留到未来工作。运行时间模型只支持 1F1B pipeline schedule，也没有纳入 activation offloading 或 rematerialization。随着异构度继续增加，搜索时间也会明显恶化：论文报告在单 zone、每种 GPU 256 张的情况下，1 种 GPU 类型耗时 0.3 秒，2 种是 6.2 秒，3 种则上升到 4900 秒。

此外，planner 模型与真实运维环境之间仍有距离。大规模结果往往来自模拟，而不是在数百 GPU 上真实部署。框架仍然依赖 NCCL 风格的 collective，论文也承认在超大规模时 NCCL 初始化本身可能耗费数分钟。至于跨厂商加速器、跨协议网络和更不稳定的 geo-distributed 链路，论文只是把它们列为未来挑战，而不是已经解决的问题。

## 相关工作

- _Athlur et al. (EuroSys '22)_ — Varuna 面向固定同构资源上的大模型训练自动化，而 Sailor 进一步把资源分配与并行计划联合起来，并显式建模异构内存约束。
- _Um et al. (USENIX ATC '24)_ — Metis 面向异构 GPU 训练，但 Sailor 进一步加入了 geo-distributed 放置、成本感知规划，以及面向动态资源变化的更快搜索。
- _Yan et al. (arXiv '24)_ — FlashFlex 支持异构环境中的 LLM 训练，而 Sailor 强调只有准确的内存/运行时间模拟和拓扑搜索，才能避免低吞吐或无效计划。
- _Yuan et al. (arXiv '23)_ — DTFM 关注异构环境中的去中心化 foundation model 训练，而 Sailor 处理的是同步式 3D parallel training，并显式计入计算租金与跨区通信成本。

## 我的笔记

<!-- 留空；由人工补充 -->
