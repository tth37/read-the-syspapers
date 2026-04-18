---
title: "Making Serverless Pay-For-Use a Reality with Leopard"
oneline: "Leopard 在 serverless 计费里显式区分 reserved/spot CPU 与 preemptible memory，并把这些语义接进 cgroups 和调度器，以更低成本换来更高吞吐。"
authors:
  - "Tingjia Cao"
  - "Andrea C. Arpaci-Dusseau"
  - "Remzi H. Arpaci-Dusseau"
  - "Tyler Caraza-Harter"
affiliations:
  - "University of Wisconsin–Madison"
conference: nsdi-2025
tags:
  - serverless
  - scheduling
  - datacenter
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

主流 serverless 计费卖的主要仍是“固定内存规格实例乘以墙钟时间”，而不是真实 CPU 与内存使用。Leopard 提出 Nearly Pay-for-Use (NPFU) 计费，并配套内核和调度器改造来转卖闲置保留资源，在保持提供商收入不变的前提下把平均吞吐提升 2.3 倍，同时降低用户成本。

## 问题背景

商业 FaaS 平台宣传自己是 “pay for use”，但论文指出它们实际更接近 SLIM：static、linear、interactive-only model。用户只设置一个内存旋钮，CPU 按固定比例导出，计费按执行时间乘以配置规格，而且所有调用都等价于为“立刻得到服务”付费。

只有四个假设同时成立时，SLIM 才能近似 strict pay-for-use：单次调用内部资源使用恒定，不同调用之间差异很小，CPU 与内存线性绑定，而且所有调用都对延迟敏感。作者构建了一个包含 22 个函数的套件，覆盖编译、视频、分析、数据库、推理与训练，结果发现四个假设全部失效：CPU 与内存会在一次调用内部波动，不同输入规模需要不同资源，多数函数不符合固定 CPU/内存比例，而且很多函数天然存在 batch 场景。结果就是用户为闲置 reservation 持续付费，集群资源也被大量搁浅。

## 核心洞察

论文的关键命题是：billing 与资源管理必须协同设计。提供商只有知道哪些资源是硬保证、哪些资源是机会性资源，才可能安全地转卖闲置 reservation。

因此，NPFU 把函数需求拆成四个旋钮：`cpu-cap`、`spot-cores`、`mem-cap` 和 `preemptible-mem`。它把 CPU 的最大需求与紧急需求分开，也把受保护内存与可通过杀掉并重排队 batch 工作来回收的内存分开。只要这些区分存在，系统就可以对“借出闲置保留资源”的函数给予抵扣，并向“借入资源”的函数收费，从而去掉 SLIM 默认的那个隐藏前提：每次调用都同样紧急、同样资源形状。

## 设计

NPFU 采用 used-lent model。对 CPU，函数要为 reserved CPU time 付费，为借来的 spot CPU time 按更低价格付费，而当自己的保留核空闲并被别人使用时会获得抵扣。对内存，non-preemptible 函数按 `mem-cap` 付费，但会因为借出闲置内存而获得抵扣；preemptible 函数则按实际平均内存使用付费，若在执行中被抢占则重排队且不收费。

Leopard 是让这些旋钮真正可执行的运行时支撑。它建立在 OpenLambda 之上，并新增 cgroup 接口 `cpu.resv_cpuset` 与 CFS 改造，让 reserved task 能立即拿回自己的保留 CPU，同时允许别的 cgroup 在这些 CPU 闲置时运行 spot work。这样避开了 Linux 原生的两难：CPU pinning 能保 reservation 但会浪费核，weighted sharing 能提高利用率却保护不好延迟敏感工作。

Leopard 还增加了 billing-aware OOM 处理。默认 OOM killer 不知道哪些 sandbox 是 preemptible，也不知道杀掉哪个 victim 会损失最少收入，所以 Leopard 让用户态监听器参与选 victim，优先驱逐 cached sandbox，再选择最便宜的 active preemptible sandbox。除此之外，Leopard 还重写了 admission control 与 load balancer：interactive 调用只有在存在足够未保留受保护资源时才会被接纳，batch 调用则在当前空闲资源和历史平均值都表明抢占风险较低时才会进入；集群对 interactive 与 batch 也分别使用不同的负载指标。

## 实验评估

实验使用 BilliBench：它把 Azure 的 serverless trace 与论文自己的函数套件结合起来，让每次调用同时具备真实的到达模式和真实的资源阶段。作者在八个 worker 上实现了四种计费模型：SLIM、SIM、SPFU 与 NPFU。

面向提供商的核心结果是，NPFU 相比 SLIM 平均把吞吐提升 2.3 倍。仅仅去掉固定 CPU/内存比例，就能让系统从 SLIM 到 SIM 获得 1.3 倍提升；再加入 spot CPU 与 preemptible memory，则从 SIM 到 NPFU 再提升 1.6 倍。利用率曲线也吻合这一点：在 SLIM 下，超过一半的 CPU 和约四分之三的内存都被浪费，而 NPFU 把内存利用率推到约 90%，CPU 利用率推到约 80%。

对用户来说，论文先调节价格系数，使提供商收入与 SLIM 相同，再比较账单。NPFU 把 interactive 调用平均成本降低 34%，把 batch 调用平均成本降低 59%。在高负载下，interactive job completion time 也更好，因为 Leopard 对 reserved resource 的保护强于原生 Linux 机制。明确的代价是：batch 作业完成时间最多可能变成 SLIM 的 3 倍，因为它们承担了机会性执行与抢占带来的缓冲作用。敏感性分析和 160-worker 仿真也保持了相同结论，而且在“CPU 平均利用率明显低于 reservation、且 batch 工作更多”的场景下收益最大。

## 创新性与影响

这项工作的创新点在于把 billing 当成第一类系统接口，而不是定价层的事后处理。Leopard 表明，serverless 的大量低效并不是单纯来自调度不好，而是来自计费合同本身。这对 serverless 平台设计者，以及研究 mixed-criticality scheduling 和 resource harvesting 的系统研究者都很重要。

## 局限性

Leopard 需要比今天 serverless 服务更强的用户与提供商协作。用户必须把工作区分为 interactive 或 batch，并比较合理地设置四个旋钮；提供商则必须修改 cgroups、CFS 与 OOM 处理逻辑，这会提高部署复杂度。

它的收益也依赖工作负载是否存在足够 slack。如果函数本来就几乎吃满 reserved CPU，可转卖的剩余容量就会变少。Batch 工作之所以更便宜，是因为它接受更弱的保证，也因此承担了重排队和更长完成时间的代价。最后，BilliBench 仍是 Azure trace 与 22 个函数套件的合成评测，而不是生产部署研究。

## 相关工作

- _Hendrickson et al. (HotCloud '16)_ - OpenLambda 是 Leopard 的实现基础，但它假定的是传统 serverless 资源控制，而不是区分 reserved 与机会性资源的计费合同。
- _Kaffes et al. (SoCC '22)_ - Hermod 通过运行时预测改进 serverless 调度，而 Leopard 的论点是：如果计费合同本身仍然强迫系统采用 SLIM 式 reservation，仅靠调度优化是不够的。
- _Fuerst and Sharma (ASPLOS '21)_ - FaasCache 研究的是为 warm reuse 服务的 sandbox eviction，而 Leopard 则把 eviction 扩展成 OOM 下针对 active preemptible sandbox 的计费感知抢占机制。
- _Ambati et al. (OSDI '20)_ - Harvest VMs 也会转卖闲置容量，但发生在 VM 时间尺度；Leopard 处理的是更难的毫秒级 serverless invocation 场景，还要区分每次调用的 QoS。

## 我的笔记

<!-- empty; left for the human reader -->
