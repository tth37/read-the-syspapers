---
title: "Evolution of Aegis: Fault Diagnosis for AI Model Training Service in Production"
oneline: "Aegis 把 AI 训练诊断推进到可插拔的 CCL 运行时观测与交付前检查，在不改客户代码的前提下做在线故障定位。"
authors:
  - "Jianbo Dong"
  - "Kun Qian"
  - "Pengcheng Zhang"
  - "Zhilong Zheng"
  - "Liang Chen"
  - "Fei Feng"
  - "Yichi Xu"
  - "Yikai Zhu"
  - "Gang Lu"
  - "Xue Li"
  - "Zhihui Ren"
  - "Zhicheng Wang"
  - "Bin Luo"
  - "Peng Zhang"
  - "Yang Liu"
  - "Yanqing Chen"
  - "Yu Guan"
  - "Weicheng Wang"
  - "Chaojie Yang"
  - "Yang Zhang"
  - "Man Yuan"
  - "Hanyu Zhao"
  - "Yong Li"
  - "Zihan Zhao"
  - "Shan Li"
  - "Xianlong Zeng"
  - "Zhiping Yao"
  - "Binzhang Fu"
  - "Ennan Zhai"
  - "Wei Lin"
  - "Chao Wang"
  - "Dennis Cai"
affiliations:
  - "Alibaba Cloud"
conference: nsdi-2025
tags:
  - llm-training
  - observability
  - fault-tolerance
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Aegis 是一套面向公有 AI 训练云的生产级诊断体系：它先从日志和拓扑相关的排障流程起步，再演进到 CCL 层的运行时观测，因此能在不修改客户代码的前提下，把计算侧故障和通信侧故障区分开来。随着这套体系上线，论文报告其在线诊断覆盖率从 77% 提升到接近 100%，同时显著降低了诊断空转时间、任务重启次数和性能退化程度。

## 问题背景

论文指出，传统云诊断系统默认故障会沿着某条清晰的源-宿路径暴露出来，但同步式模型训练恰好相反：一个坏掉的 GPU、NIC、PCIe 路径、NVLink 或光链路，最先暴露出来的往往不是“罪魁祸首”，而是整批机器同时报出的 CCL timeout。也就是说，训练作业把单点故障扩散成了全局症状，根因很容易被淹没。

硬件环境又把这个问题放大了。作者的训练集群采用八卡主机、复杂的 PCIe 与 NVLink 互连，以及 rail-optimized 网络。论文给出的生产统计显示，A100 的平均失效时间大约是 400 天，H100 约为 200 天，而 45.6% 的故障都与 GPU 相关。与此同时，光模块与光纤的故障率又比 DAC 高 1.2x-10x。即便 dual-ToR 避免了训练任务直接崩掉，链路坏掉之后的带宽折半仍然可能把作业拖入明显的性能退化。

现有方案只能解决局部问题。作者已有的网络监控、RDMA Pingmesh 和带内诊断在普通数据中心场景下很好用，但它们过于关注网络本身和单条请求-响应路径。SuperBench 适合上线前筛查，却不适合训练运行时；MegaScale 更接近运行时方案，但它要求观测客户模型里的“critical code segments”，这对服务多租户、代码高度保密的公有云并不现实。

## 核心洞察

这篇论文最重要的判断是：对于公有模型训练云，最合适的诊断边界既不是应用层，也不是裸网络层，而是 collective communication library。CCL 正好位于计算与通信的边界，又能在主流训练框架里以可替换插件的形式部署，因此可以在不侵入客户模型和训练框架的情况下，暴露出足够有用的同步运行时信号。

但作者并没有把它包装成“单一银弹”。Aegis 的关键其实是分层：先用高置信度的日志与拓扑流程清理掉容易定位的故障，再用 CCL 层的轻量观测补上那些只能在线区分的复杂情况。于是，论文真正贡献的是一条生产工作流：先做 critical error 快速隔离，再做拓扑感知的离线 backstop，随后用 CCL 做运行时定位，最后再用交付前检查把“作业一启动就失败”的问题尽量挡在外面。

## 设计

Aegis 主要由三部分组成。Phase-1 在现有基础设施日志之外，引入训练日志和新的诊断流程。`CriticalError()` 处理那些能直接指向坏主机的故障，例如 double-bit ECC、GPU/NIC/NVLink 缺失、供电问题和过热。`DistError()` 则记录“connection reset by peer”这类分布式症状。如果只有一两台主机被牵连，系统会直接隔离它们；如果波及多台机器，`RootDiag()` 会检查首次失败连接是否能围绕某个源或宿形成聚类；再不行，就交给 `ConfigCheck()` 和 `NetDiag()` 去排查配置与网络问题。

当这些在线信息仍然不够时，Aegis 会进入离线诊断，但它不是把整簇机器锁住跑几小时测试，而是做并行且拓扑感知的 backstop。主机先各自执行自检，然后再在精心切分的子集上运行代表性训练模型；切分时尽量避免不同诊断任务共享同一组 Pod 或 ToR group，以免相互争用链路、污染结论。论文里一个 1.5K-GPU 故障案例很典型：正是这种切分“复现不出来”的异常，反过来暴露出 Tier-2 aggregation switch 在丢弃大于 1 KB 的报文，从而推动他们把 RDMA Pingmesh 扩展到不同 probe 长度。

Phase-2 把关键观测推进到定制 CCL 中。对于每个 collective `Ci` 和 GPU `Gj`，Aegis 记录 collective launch、work request 和 work completion 的计数。如果某个 GPU 没能像别人一样继续发起下一次 collective，而其他 GPU 都还在推进，那说明故障在该主机的计算侧；如果所有 GPU 都卡在同一个 collective 里超时，但某个参与者的 work request 和 work completion 行为异常，那更可能是通信侧故障，系统再把相关端点交回 `NetDiag()`。针对性能退化，Aegis 先对 20 多个主机与网络指标做跨主机的 Z-score 异常检测，再补充 CCL 侧的 collective 时长和吞吐观测，用于区分计算变慢还是通信变慢。最后，Check Before Delivery (CBD) 会在资源正式交给客户前执行一组紧凑的配置检查、单机检查和多机检查；完整版不到 10 分钟，轻量版不到 1 分钟。

## 实验评估

论文的评估本质上是一项约 16 个月的生产运维研究，对象是作者内部一个顶级 LLM 训练项目，其训练规模在这段时间里增长了 40 多倍。这个背景很重要，因为论文不是在实验室里做静态基准对比，而是在真实业务压力下观察诊断体系逐步演进后的结果。

最核心的结果是空转时间下降。Aegis Phase-1 上线后，尽管训练规模在次月翻倍，因等待故障诊断造成的 idle time 仍下降了 71%。到 2024 年 6 月 Phase-2 上线后，剩余 idle time 又进一步下降了 91%，因为绝大多数故障不再需要进入离线定位。论文最关键的主张是“运行时诊断覆盖率从 77% 提升到接近 100%”，从给出的生产结果看，这个结论是被支撑住的。

另外两个结果也和系统设计高度一致。CBD 针对的是初始化阶段故障，而论文显示 73% 的失败任务都发生在前 10 分钟。CBD 上线后，次月任务重启次数下降了 44.8%，随着检查项不断完善，累计降幅达到 84.6%，并且持续在正式交付前拦截出 1%-2% 的问题主机。性能退化方面，相关性诊断与 procedure-aware 机制落地后，总体退化程度下降了 71%。论文还给了一个具体案例：某块 NIC 的 ECN 指标突然升到每秒 10K-30K，同时训练 iteration time 增加了 26%，Aegis 由此追到了一条存在 silent packet loss 的链路。

## 创新性与影响

和最接近的两套系统相比，Aegis 的差异很清楚。`SuperBench` 是离线验证套件；Aegis 吸收了它的交付前检查思路，但把它延伸成运行时定位体系，并把离线路径改造成可增量、拓扑感知的 backstop。`MegaScale` 同样面向大规模训练故障，但它建立在对模型代码深度可见的前提上。Aegis 的新意在于，它把“公有云可部署性”和“足够具体的运行时故障区分能力”结合起来，仅凭 CCL 层就能把计算侧与通信侧的大类故障分开。

这更像一篇生产系统论文而不是纯算法论文，但价值并不低。它展示了云服务商如何把原本依赖人工经验的排障流程，整理成一套分层的服务能力；同时也明确提出，collective communication 才是多租户训练云里最现实的观测边界。

## 局限性

论文明确承认，这套方案是“为易部署性做妥协”。CCL 观测只是一个 bridge：它能把罪魁祸首定位到某台主机或某条路径，足以完成隔离，但更深入的根因分析仍然在线下完成，而且作者明确说这不属于 Aegis 的范围。系统还有真实的维护成本，因为云平台必须针对不同 CCL 版本和异构客户镜像持续维护自己的定制版本。

评估本身也更多是结果导向。论文没有给出按故障类型划分的 precision/recall 表格，部分监控指标也因为保密原因没有公开。多数量化结果来自一个内部 LLM 项目，而不是覆盖大量外部工作负载。某些问题最终仍需依赖厂商配合，例如经验部分提到的 NIC 拥塞控制固件缺陷。最后，CBD 会引入启动时延，所以论文不得不再提供一个轻量版，以适应对启动时延更敏感的 PaaS 场景。

## 相关工作

- _Xiong et al. (USENIX ATC '24)_ - `SuperBench` 重点是在部署前验证 AI 基础设施，而 `Aegis` 把这一思路扩展到了运行时定位，并补上了更轻量的交付前检查路径。
- _Jiang et al. (NSDI '24)_ - `MegaScale` 通过观测模型中定义好的 CUDA critical sections 来定位训练故障，而 `Aegis` 则避免依赖任何客户代码级的插桩。
- _Liu et al. (SIGCOMM '24)_ - `R-Pingmesh` 是面向网络的 RoCE 监控系统，但 `Aegis` 认为一旦 collective training 的故障扩散到整个作业，单靠网络视角并不够。
- _Harsh et al. (SIGCOMM '23)_ - `Murphy` 用相关性观测来诊断分布式云应用，而 `Aegis` 把这种思路专门改造成适配同步式 collective training 与多租户云约束的版本。

## 我的笔记

<!-- 留空；由人工补充 -->
