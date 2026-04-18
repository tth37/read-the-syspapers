---
title: "Minder: Faulty Machine Detection for Large-scale Distributed Model Training"
oneline: "Minder 通过找出在去噪后仍持续偏离同任务其他机器的那台主机，把分布式训练中的多团队人工排障变成平均 3.6 秒的运行时告警。"
authors:
  - "Yangtao Deng"
  - "Xiang Shi"
  - "Zhuo Jiang"
  - "Xingjian Zhang"
  - "Lei Zhang"
  - "Zhang Zhang"
  - "Bo Li"
  - "Zuquan Song"
  - "Hang Zhu"
  - "Gaohong Liu"
  - "Fuliang Li"
  - "Shuguang Wang"
  - "Haibin Lin"
  - "Jianxi Ye"
  - "Minlan Yu"
affiliations:
  - "Tsinghua University"
  - "ByteDance"
  - "Northeastern University"
  - "Harvard University"
conference: nsdi-2025
tags:
  - llm-training
  - observability
  - gpu
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Minder 面向大规模分布式训练中的故障机器检测，核心做法是把同一任务中的健康机器视为近似同步的参照组，再找出去噪后监控轨迹持续偏离同伴的那台机器。它为每个指标单独训练 LSTM-VAE，按故障敏感度优先使用最有信息量的指标，并且只有当同一台机器在连续时间窗口里持续异常时才告警。在 ByteDance 的生产部署中，Minder 平均 3.6 秒即可作出反应，在真实故障数据上达到 0.904 precision 和 0.893 F1。

## 问题背景

这篇论文解决的是大规模模型训练里一个非常实际、但长期依赖人工处理的问题：故障通常先出现在单台机器上，但运维侧往往只有在整个任务明显变慢甚至停掉之后，才真正知道出了问题。作者所在环境中的训练任务规模可达上千台机器，平均每天约有两次意外故障。由于现代训练同时依赖 data parallelism、pipeline parallelism 和 tensor parallelism，一台坏机器就可能通过 NCCL timeout、通信断连或大面积空转，把影响迅速扩散到整组任务。

传统做法是人工排障。训练、网络、存储、硬件等多个团队一起查日志、看计数器、跑离线测试，最后定位是哪台机器出了问题。论文认为这套流程慢不是偶然，而是结构性地慢。首先，告警时机太晚，通常要等任务停掉，而不是在性能刚开始劣化时介入。其次，日志内容不完整，像 GPU 功耗、PFC 报文速率这类很有价值的监控数据往往不在日志里。最后，故障来源极其分散，既可能来自 GPU memory、PCIe、NVLink、NIC，也可能来自 CUDA、NCCL、HDFS、SSH 等软件与服务层。

更难的是，这不是一个可以靠单一指标或统一标签解决的问题。CPU、GPU、Memory、Throughput、PFC 等指标都和某些故障相关，但没有哪个指标能覆盖所有故障；同一个指标在不同训练任务里，正常范围也可能完全不同。因此，论文真正面对的不是通用异常检测，而是在任务依赖很强、基线又随工作负载变化的场景下做运行时“责任机器”定位。

## 核心洞察

Minder 的核心命题是：大规模分布式训练本身已经天然提供了参照组，也就是同一任务里的其他机器。在 3D parallel training 下，健康机器在秒级粒度上的计算、通信与存储行为应该大体相似。因此，系统不需要预先学出一个跨任务通用的“正常”模板，只需要找出那台相对于同伴持续偏离的机器即可。

基于这个观察，论文又做了两个关键收敛。第一，不把所有指标揉进一个统一检测器里，而是按指标分别去噪和检测，因为不同故障会通过不同计数器表现出来，把它们混在一起反而会模糊信号。第二，引入 continuity 约束：真正的故障往往会导致几分钟级别的持续性能劣化，而传感器噪声或短暂抖动通常只持续很短时间。这样一来，问题就从“当前状态是否异常”转化成“哪台机器在足够长时间里最像离群点”。

## 设计

Minder 作为后端 watcher 运行。对于每个训练任务，它周期性拉取所有机器最近一段时间的秒级监控数据，先对不同主机的时间戳做对齐，再用最近采样值补齐缺失点，并对各指标做 min-max normalization。之后，系统把每个指标切成滑动时间窗口，送入按指标单独训练的去噪模型。

这里的去噪模型是 LSTM-VAE。论文的理由很务实：如果训练数据大部分来自正常运行区间，VAE 就能学到主要的时间序列结构，把带噪输入重构成更干净的 embedding，而真正的异常样本在重构后仍然会显得突出。Minder 为每个指标单独训练一个模型，例如 CPU usage、PFC packet rate 或 GPU duty cycle。这样做很重要，因为论文对真实故障的统计表明，故障类型和指标之间更像是“或关系”：ECC error 可能体现在 CPU 或 GPU 指标上，PCIe 故障更容易出现在网络计数器里，没有任何单个特征是权威信号。

系统还会学习一个指标优先级顺序。具体做法是：先在每个时间窗口上计算各指标在机器之间的最大 Z-score，再把这些窗口级特征送入 decision tree，学习哪些指标对故障最敏感。树根附近的指标优先级更高。最终得到的顺序把 PFC、CPU、GPU 与 NVLink 相关信号排在前面，这也和作者的案例分析一致，即真实故障最常先扰动进程状态或通信行为。

运行时检测按这个优先级依次尝试。对于某一个指标，Minder 用对应的 LSTM-VAE 重构每台机器的窗口数据，计算机器之间 embedding 的 pairwise Euclidean distance，再把某台机器到其他所有机器的距离求和，并做与机器规模相关的归一化。若某台机器的归一化离群分数最高且超过 similarity threshold，它就成为当前窗口的候选故障机。随后系统以步长 1 滑动窗口继续检测。只有当同一台机器持续超过 continuity threshold，论文设为 4 分钟，Minder 才真正发出告警。在生产环境里，这个告警会交给驱动程序封禁该机器，并由 Kubernetes 换上一台新机器，让任务从 checkpoint 快速恢复。

## 实验评估

评估同时包含一年的生产部署经验和一个覆盖九个月、共 150 个运行时故障实例的数据集。任务规模从 4 台到 1500 多台机器不等，最高覆盖超过 10,000 张 NVIDIA Ampere GPUs，包含 ECC error、CUDA failure、GPU execution error、PCIe downgrading、machine unreachable 等主要故障类型。

第一组核心结果是检测时延。一次 Minder 调用平均只需 3.6 秒，其中既包括从 Data APIs 拉取监控数据，也包括后续预处理与推理计算。相比论文中统计到的人工排障平均超过半小时、最坏可达数天的流程，这个数字足以支撑作者“常规路径上减少 99% 以上响应时间”的结论。

第二组结果是检测质量。Minder 达到 0.904 precision、0.883 recall、0.893 F1；对比基线 Mahalanobis Distance 的 0.788 precision、0.767 recall、0.777 F1，有明显优势。这支持了论文的中心论点：仅靠统计离群值不够，抖动和噪声会显著干扰判断，而按指标去噪后再做比较更稳健。

消融实验也很说明问题。只用更少指标会损失 recall，因为关键信号被删掉了；加入更多指标则会降低 precision，因为异质信号彼此干扰。把模型替换成 raw distance，或者把所有指标做拼接/一体化建模，都会让 recall 和 F1 下降；移除 continuity 后，precision 会明显降到 0.757，因为短暂抖动会被直接放大成误报。评估较弱的地方在于罕见并发故障：PCIe downgrading 和 GPU execution error 在故障快速沿 3D parallel group 扩散时更难识别，而交换机侧 AOC error 也因为缺乏相关光模块计数器而容易漏检。论文对此较为坦诚，认为真正的瓶颈是当前只有秒级监控。

## 创新性与影响

这篇论文的创新不在于单独提出了某个新的深度学习模型，而在于提出了一套适合训练集群运维的系统性配方：利用同任务机器之间的 peer similarity，按指标分别去噪和检测，依据 fault sensitivity 给指标排序，再用 temporal continuity 过滤抖动误报。它比通用 KPI anomaly detection 更贴近训练系统，也比依赖服务依赖图的根因分析框架更容易直接落地。

对大规模训练集群的运营者和 AI infrastructure 研究者来说，这篇论文都很有价值。它说明机器级故障检测已经可以快到直接进入恢复闭环，也说明在这类任务里，最有效的抽象不是跨任务统一异常标签，而是对同构 worker 做 comparative observability。因此，我更愿意把它看成一种新的训练运维机制，而不是一篇纯测量论文。

## 局限性

Minder 能检测“哪台机器有问题”，但不能直接回答“根因到底是什么”。系统发出告警后，工程师仍然可能需要额外工具去区分这是 ECC、PCIe、NVLink、软件栈故障，还是短暂网络事件。论文明确把更细粒度的 root cause analysis 留给未来工作。

这套方法也依赖工作负载结构。它默认同一任务中的机器应该表现得大体相似，这对作者的 3D parallel training 成立，但对更异构的 inference 或混合服务场景未必同样稳固。作者认为只要 inter-machine similarity 仍成立，Minder 就能迁移过去，但论文并没有真正验证这一点。

最后，当前部署依赖秒级计数器，且大多数评估案例仍是单点故障。这使它难以捕捉极快的传播模式，也难以在没有更细粒度遥测时定位并发故障。论文里用于展示多故障能力的注入实验，实际上依赖的是毫秒级监控。

## 相关工作

- _Xiong et al. (USENIX ATC '24)_ - SuperBench 通过主动跑 benchmark 来提前发现不可靠的 AI 硬件，而 Minder 监控的是正在运行的训练任务，并且覆盖软件侧运行时故障。
- _Liu et al. (NSDI '23)_ - HostPing 依赖离线测试来诊断 RDMA 服务器中的机内瓶颈，Minder 则试图在分布式训练还在运行时直接找出故障机器。
- _Liu et al. (ISSRE '19)_ - FluxRank 面向服务故障中的根因机器定位，依赖服务级上下文信号；Minder 则利用分布式训练 worker 之间高度同构的同行行为。
- _Xu et al. (WWW '18)_ - 这类基于 VAE 的 KPI 异常检测为 Minder 的去噪选择提供了方法学基础，但 Minder 进一步加入了按指标建模、跨机器距离比较和 continuity 检查。

## 我的笔记

<!-- empty; left for the human reader -->
