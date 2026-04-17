---
title: "Fine-grained and Non-intrusive LLM Training Monitoring via Microsecond-level Traffic Measurement"
oneline: "Pulse 在 SmartNIC 上做微秒级 RDMA 流量测量，并把流量还原成 NCCL 算子，从而在不改用户代码的前提下定位 LLM 训练故障。"
authors:
  - "Yibo Xiao"
  - "Hao Zheng"
  - "Haifeng Sun"
  - "Qingkai Meng"
  - "Jiong Duan"
  - "Xiaohe Hu"
  - "Rong Gu"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "State Key Laboratory of Novel Software Technology, Nanjing University, Nanjing, China"
  - "National University of Singapore, Singapore, Singapore"
  - "Infrawaves, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790163"
tags:
  - llm-training
  - observability
  - rdma
  - smartnic
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Pulse 认为，云上 LLM 训练监控应该直接在 SmartNIC 上测 RDMA 流量，而不是依赖用户代码插桩。它把 per-flow 轨迹还原成 NCCL 算子，并用“实际通信时间”这类显式排除空洞的指标来区分计算故障与通信拖尾。在一个 64 张 H200 的平台上，它能把 12 类代表性故障中的 10 类定位到机器级，而算子级基线只能做到 4 类。

## 问题背景

这篇论文针对的是云上托管训练的运维问题。大模型训练持续时间长、规模大、同步频繁，一台机器一旦变慢，影响就会沿着 collective 迅速扩散。服务商需要尽快定位故障节点，但往往既拿不到用户代码控制权，也不适合要求用户修改训练框架或通信库，因此 intrusive 的监控方式天然不理想。

现有方法主要在两个方向上不够用。离线 benchmark 事后可能复现不出瞬时故障。在线方法如 Aegis、Holmes、GreyHound 虽然更适合实时诊断，但它们大多只观察算子级 timing 和平均吞吐，这对 LLM 训练仍然太粗。collective 在 slice 粒度同步时，真正的 straggler 会让其他 rank 出现传输空洞，于是整组节点可能表现出几乎一样长的 duration，真正慢的机器反而藏起来了。与此同时，算子级 timing 又把 GPU 计算、CPU proxy thread 延迟和 NIC 传输混在一起，CPU 瓶颈很容易被误诊成网络异常。

## 核心洞察

论文的核心判断是：只要能把底层 RDMA 流重新映射回高层通信算子，RDMA 流量本身就是细粒度训练诊断最可靠的信号。直接在 RNIC 上按 QP 测量流量，看到的是通信真实推进过程，而不是软件层记录的粗糙起止区间，因此那些算子级方法看不到的 gap 会自然暴露出来。

同时，Pulse 并不把所有微秒级曲线都送去分析器。它把细粒度流量先压缩成少量“对空洞敏感”的指标：对内建 collective，用实际通信时间和通信体积；对 custom collective，用 rank 级实际传输速率和完成状态。这样既保留了定位所需的信息，又不会把整个系统做得太重。

## 设计

Pulse 由 NIC Agent、Host Agent、Analyzer 三部分组成。NIC Agent 是技术核心。它没有把测量直接压到 packet-processing critical path 上，而是拆成三层：NIC pipeline 里的 aggregation、NIC 内嵌微处理器上的 measurement，以及主机上的 collection。原型里一条流每发送 4 KB 就触发一次事件，measurement 层按 32 us 的 epoch 记录 per-QP 流量。实现上，它用 24-bit QPN 做 direct-address table，再配合只给活跃流分配空间的 epoch pool 和 host 轮询下的 flow aging。论文估算，在 400 Gbps NIC 上，监控 2000 条活跃流只需要 16 个 DPA 线程和约 184 MB 内存。

Host Agent 负责把 flow-level 测量还原成 operator-level 测量。初始化阶段，它通过 hook `ibv_modify_qp`、NCCL 初始化和 GPU 使用信息来恢复 QP 到 GPU 的映射以及通信组成员。运行阶段，它拦截 NCCL 算子并推断预期通信 peer 和数据量。P2P 算子比较直接；内建 collective 则需要先根据 active peer 模式推断 NCCL 选的是 ring 还是 tree。

但预期流量只是下界，因为真实传输还包含报文头、同步消息和可能的重传。Pulse 因此用“体积条件 + 时间间隔条件”做 segmentation。对 custom collective，它再把 `ncclGroupStart` 和 `ncclGroupEnd` 之间的一组 P2P 调用归并起来。

Analyzer 再基于压缩后的指标做定位。对内建 collective，communication fail-slow 看实际通信时间，fail-stop 看哪个节点发出的数据最少。对 custom collective，Pulse 用 rank 级实际速率平滑单个 P2P 上的抖动，并用未完成的 P2P 算子识别 fail-stop。计算异常则通过后继算子的延迟开始、缺失开始时间，以及“总 duration 变长但实际通信时间正常”这一模式来判断。

## 实验评估

实验和目标场景是匹配的。作者在 8 台租用服务器上部署 Pulse，每台机器有两颗 AMD EPYC 9575F、8 张 H200、8 张 BlueField-3 SuperNIC，通过 400 Gbps RoCEv2 互连，总计 64 张 GPU。评测覆盖 57 次故障注入，分别落在 GPT-2 70B、Mixtral 8x7B 和一个小型 neighbor-exchange 工作负载上。

Pulse 总体达到超过 90% precision 和 100% recall，在 12 个代表性场景里有 10 个能定位到机器级，另外 2 个也能缩到 group 级；算子级基线只有 4 个场景做到机器级，且还有 2 个场景会误诊。案例分析也能解释这些收益：32 us 粒度足以显露 network congestion 下的真正 straggler，而 64 us 已经开始把部分 gap 折回“实际通信时间”；CPU contention 时，Pulse 看到 duration 变长但实际通信时间正常，因此不会错怪网络；MoE expert-parallel 时，rank 级实际速率抑制了单个 P2P 抖动导致的假阳性。

开销也很低。单个 RNIC 上同时测量 2000 条流时，吞吐没有下降，平均 RDMA 延迟只从 1.52 us 变到 1.53 us。GPT-2 32B、GPT-2 70B、Llama-70B 的训练 iteration 时间几乎不变，Host 与 NIC 之间的 PCIe 开销峰值约 0.3 MB/s。主要代价是诊断延迟：由于 RNIC 数据按 1 秒周期上传，而且还要做 flow-operator association，Pulse 比算子级方法平均慢约 0.7 秒。

## 创新性与影响

相较于 Aegis 和 Holmes，Pulse 的新意不在于做一个更复杂的算子级监控器，而在于整体下移观测底座：先看 RNIC 可见流量，再从底层重建高层算子行为。相较于 GreyHound，它保留了 non-intrusive 部署方式，但进一步拿到了子算子级可见性。相较于 host 或 switch 侧测量工作，它的关键贡献是三层 RNIC 设计，让部署在现有 SmartNIC 上的、无损的微秒级 RDMA 测量真正可行。

这让它对云上训练服务商很直接有用，也说明细粒度流量测量可以成为通信密集型 ML 系统的应用级可观测性基础设施。

## 局限性

Pulse 只能看到跨节点的 RDMA 流量，看不到 NVLink，也不支持 CollNet 或 NVLS，因此无法覆盖完整的 scale-up 通信视图。这个限制还会影响部分计算故障的定位粒度：如果歧义留在单机内的 TP group 里，Pulse 往往只能缩到机器级，而不是精确到单块 GPU。

此外，Pulse 依赖一组比较具体的环境假设。它需要 BlueField-3 或 ConnectX-6 Dx 这类可编程 RNIC，需要周期性的 host 轮询，也需要一个贴近 Megatron、DeepSpeed 这类主流框架的 parallelism identification 规则。这些前提在目标环境里也许合理，但会限制可移植性。1 秒轮询周期同样是明确的权衡：它让系统保持轻量，却也限制了诊断反应速度。

## 相关工作

- _Dong et al. (NSDI '25)_ — Aegis 从训练日志和 CCL 中收集算子级信息，而 Pulse 下探到 per-flow RDMA 流量，因此能在不改用户代码的前提下暴露子算子级 gap。
- _Yao et al. (NSDI '25)_ — Holmes 面向在线的 LLM 训练异常定位，但它依赖的是算子时间线，而不是从 NIC 可见流量重建通信推进过程。
- _Wu et al. (USENIX ATC '25)_ — GREYHOUND 通过函数 hook 和 CUDA event 实现 non-intrusive 监控；Pulse 保留了这种部署便利性，同时用微秒级流量测量把定位粒度进一步推进到机器级。

## 我的笔记

<!-- empty; left for the human reader -->
