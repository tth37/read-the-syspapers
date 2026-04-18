---
title: "SimAI: Unifying Architecture Design and Performance Tuning for Large-Scale Large Language Model Training with Scalability and Precision"
oneline: "SimAI 复用真实训练框架与 NCCL，把 LLM 训练的容量规划和 packet-level 调优统一进一套模拟器，平均与真实运行对齐 98.1%。"
authors:
  - "Xizheng Wang"
  - "Qingxu Li"
  - "Yichi Xu"
  - "Gang Lu"
  - "Dan Li"
  - "Li Chen"
  - "Heyang Zhou"
  - "Linkang Zheng"
  - "Sen Zhang"
  - "Yikai Zhu"
  - "Yang Liu"
  - "Pengcheng Zhang"
  - "Kun Qian"
  - "Kunling He"
  - "Jiaqi Gao"
  - "Ennan Zhai"
  - "Dennis Cai"
  - "Binzhang Fu"
affiliations:
  - "Alibaba Cloud"
  - "Tsinghua University"
  - "Zhongguancun Laboratory"
  - "South China University of Technology"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/aliyun/SimAI"
tags:
  - llm-training
  - gpu
  - networking
  - datacenter
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SimAI 的主张是，LLM 训练需要一套既能做 packet-level 调优、又能做容量规划的统一模拟器。它通过 mock 真实训练框架和 NCCL 生成工作负载，再配合更细粒度的计算模型、NCCL 派生的通信模型，以及多线程加无锁共享状态的执行引擎，把这件事真正做成。按论文在各类测试场景中的汇总结果，SimAI 与真实运行的平均偏差为 1.9%，并被用来直接指导主机带宽和 TP 调参。

## 问题背景

论文指出了一个现实割裂：采购前大家用粗粒度模拟估算需要多少 GPU、NIC 和交换机，部署后又用 packet-level 模拟去调 NCCL、拥塞控制和并行参数。现有工具往往只擅长其中一端，所以同一个训练集群在规划和优化阶段常常对应两套不同抽象，结论容易彼此脱节。

在 LLM 时代，这种割裂代价很高。团队想比较 GPU 代际、主机布局、网络带宽和 TP/DP/PP 设置，但现有方法不是忽略真实框架和 collective 的行为，就是慢到无法反复探索。论文因此把目标收敛成一句话：需要一套在没有目标集群时也能生成真实工作负载、同时准确覆盖计算与通信、并且能扩展到上千 GPU 的统一模拟器。

## 核心洞察

SimAI 的关键判断是，统一模拟器只有在“借用真实软件栈的关键语义”时才可信。它不是从 FLOP 数反推工作负载，也不是把 collective 近似成理想流，而是让 Megatron 和 DeepSpeed 误以为自己运行在目标规模集群上，跳过真实通信后直接记录 submodule、collective 和 overlap 依赖；通信侧再拦截 NCCL 的初始化与 collective 选择逻辑，重建真实训练会产生的点对点流量。

更一般的洞察是 selective fidelity。计算部分需要比传统训练模拟器更细，但没必要走到完整 GPU 微架构模拟；通信部分要继续保持 packet-level 且忠实于 NCCL；模拟器本身的加速则靠系统实现，而不是靠继续牺牲模型细节。

## 设计

SimAI 由三个建模模块和一个执行引擎组成。`SimAI-WG` 在单机上运行被 mock 过的框架，假装目标 world size 已经存在，屏蔽真实通信后输出 workload description file，其中包含计算 submodule、collective 和 peer-to-peer 通信操作，以及它们之间的依赖图。之所以要保留依赖，是因为真实训练里计算与通信会重叠。

`SimAI-CP` 负责计算模拟。对已有 GPU，它使用一个基于实测的 operation database，覆盖常见 LLM submodule，必要时还能进一步细化到 attention 和 MLP 等 kernel。对未发布 GPU，它退化为一个双公式 Roofline 风格模型：compute-bound kernel 按有效 FLOPS 缩放，memory-bound kernel 按显存带宽缩放，这比拿整机参数做统一比例缩放要准确得多。

`SimAI-CM` 负责通信模拟，其核心是轻量改造过的 NCCL 版本 `SimCCL`。它创建虚拟 communicator，从用户提供的 topology 文件读取 GPU、NIC 和 PCIe 结构，再在 collective 调用处拦截 NCCL，把底层点对点 flow 列表导出来。由于这条路径保留了 NCCL 的真实决策，SimAI 才能模拟算法选择、PXN 路由以及许多 NCCL 环境变量对通信模式的影响。

这些事件最终进入一个基于 NS-3 的执行引擎。为了让规模跑起来，作者采用多线程，并把大量共享元数据重构成按节点编号切分的表格，避免全局锁。论文报告说，这种无锁设计让 SimAI 比最初单线程版本快 23x，比早期多线程实现也再快 15%。

## 实验评估

评估使用了两套 128 台主机的 RoCEv2 集群，一套是 A100，一套是 H100，都是 fat-tree、多 rail 拓扑。工作负载来自 GPT-3 和 LLaMA 的 benchmark suite，覆盖 Megatron 和 DeepSpeed。主要对比对象是 ASTRA-sim。

通信精度是最干净的结果。对机内 collective，SimAI 在 A100 和 H100 上的平均偏差分别只有 3.9% 和 2.3%，而 ASTRA-sim 分别高达 74.8% 和 51.7%。跨主机通信也呈现同样趋势，尤其在小消息和大规模场景下更明显。论文特别举出一个 8 MB 的 `AllGather`：到 512 张 A100 时，ASTRA-sim 的误差已经膨胀到 530.2%。

计算侧对实测路径也很强。`SimAI-CP` 在 A100、H100 和 H20 上都能把 kernel 时间控制在 0.5%-3.1% 的误差内，而后备路径 `SimAI-CP-Model` 约为 13%-15%。端到端地看，SimAI 在 1,024 GPUs 以内都能把 iteration time 压在与真实集群 4% 以内的误差，作者把总体平均对齐度总结为 98.1%。生产案例也说明它不是纯离线玩具：在 H100 案例里，把单卡带宽从 200 Gbps 提升到 400 Gbps 仍能带来 19% 的性能收益；而 TP 研究则表明，layer 放得下之后，再增大 TP 反而可能伤害吞吐，额外的 DP 往往更划算。

## 创新性与影响

SimAI 的新意不在单个模块，而在于整体组合：从真实框架生成工作负载、按 NCCL 重建通信、用更细粒度的计算模型覆盖 GPU 行为，再把执行路径做快到足以支持反复探索。和 ASTRA-sim 这类工作相比，它更像一套面向生产问题的全栈方法，而不只是某个模拟器组件。这也解释了论文的影响主张为什么成立：作者声称 Alibaba 的团队已经用它来决定主机带宽和训练参数，而不只是做离线分析。

## 局限性

它的覆盖范围仍然偏窄。框架支持集中在 Megatron 和 DeepSpeed，通信支持集中在 NCCL，评估环境也主要是 NVIDIA 加 RoCE；如果工作负载超出论文给出的 benchmark suite，还需要补做 GPU 侧测量来扩充 operation database。小消息通信仍可能偏差较大，因为 SimAI 没有模拟 `libibverbs` 或 NIC pipeline 等运行时细节；对未发布 GPU，后备计算模型也明显不如基于实测 kernel 库的方法准确，而换用其他 NCCL 版本或新的 CCL 也需要重新适配 `SimCCL` 这一层。它还跳过了真实 payload 语义，因此 expert parallelism 被简化成 token 均衡分布假设，而 adaptive routing 和 InfiniBand SHARP 相关特性仍属于未来工作。

## 相关工作

- _Rashidi et al. (ISPASS '20)_ - `ASTRA-sim` 建模的是分布式 DNN 训练栈，而 `SimAI` 试图把同一套模拟器同时用于 LLM 的容量规划和 packet-level 调优。
- _Won et al. (ISPASS '23)_ - `ASTRA-sim 2.0` 扩展了对分层网络和解耦系统的训练模拟，而 `SimAI` 更强调高保真工作负载、计算和 NCCL 感知通信的统一建模。
- _Gao et al. (SIGCOMM '23)_ - `DONS` 展示了 data-oriented 网络模拟如何改善 cache 行为和并行性，`SimAI` 则把类似的可扩展性思路用到了自己的多线程执行引擎上。
- _Khairy et al. (ISCA '20)_ - `Accel-Sim` 提供了更细粒度的 GPU 建模，而 `SimAI` 选择牺牲指令级细节，换取足以支撑大规模端到端 LLM 集群研究的速度。

## 我的笔记

<!-- 留空；由人工补充 -->
