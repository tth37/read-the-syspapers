---
title: "Accelerating Design Space Exploration for LLM Training Systems with Multi-experiment Parallel Simulation"
oneline: "Multiverse 把大量 LLM 训练模拟批量装进一个驻留 GPU 的 ECS 流水线里，在保持与真实训练误差低于 3% 的同时，把探索速度提高到 73.2x。"
authors:
  - "Fei Gui"
  - "Kaihui Gao"
  - "Li Chen"
  - "Dan Li"
  - "Vincent Liu"
  - "Ran Zhang"
  - "Hongbing Yang"
  - "Dian Xiong"
affiliations:
  - "Tsinghua University"
  - "Zhongguancun Laboratory"
  - "University of Pennsylvania"
  - "BNRist"
  - "Tsinghua Shenzhen International Graduate School"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/NASP-THU/multiverse"
tags:
  - llm-training
  - gpu
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Multiverse 的出发点是：LLM 训练系统的设计空间探索通常需要几百到上万次彼此独立的模拟实验，而把这些实验当成互不相关的 CPU 作业，会浪费掉它们共享的结构。它把许多实验放进同一个 single-process multi-experiment 模拟器里，用 ECS/DOD 方式组织状态，再直接放到 GPU 上执行。这样既能在需要的地方保留 packet-level 网络保真度，又能用校准过的解析模型替代缓慢的机内通信模拟，最终相对已有 CPU 模拟器获得 43.1-73.2x 的加速，同时把端到端 iteration time 控制在与真实 128/1,024-GPU H100 训练集群低于 3% 的误差内。

## 问题背景

这篇论文解决的是 LLM 训练系统上线之前就会遇到的一个前置瓶颈：如何在一个极大的设计空间里找到合适配置。现代训练栈要同时决定 tensor/pipeline/data parallel 的组规模、collective communication 算法、拥塞控制参数，甚至网络拓扑本身。作者给出了非常具体的量级：仅仅优化并行组配置就可能需要约 100 次实验，而拓扑搜索则可能超过 10,000 次。如果没有把搜索做充分，代价会很高；论文援引的先前工作表明，一个不合适的拓扑会把 iteration time 拉长 3.4x。

最直接的办法，是把这些实验拆成许多 CPU 进程并行跑。论文认为问题恰恰出在这里。独立进程会重复持有模拟器状态，争抢 cache 和内存；如果再用 multi-process 技术加速单次实验，还要额外支付同步和调度开销。因此，即便是 ASTRA-sim 搭配 UNISON 或 DONS 这样的强 CPU 基线，在真正的任务是“跑很多独立实验”时，扩展性依然是次线性的。论文的关键动机是：设计空间探索的速度本身已经是一个系统问题，而不只是某一次模拟运行快不快。

## 核心洞察

Multiverse 的核心洞察是，应当把多实验探索视为一种 SIMD 风格的工作负载。不同实验执行的是同一套模拟逻辑，只是输入状态不同，因此最合适的执行模型不是“很多个模拟器”，而是“一个模拟器同时对许多实验状态执行同样的系统逻辑”。论文把这种方式称为 single-process multi-experiment，也就是 SPME。

但光有 SPME 还不够，真正让它变强的是 data-oriented 表示。Multiverse 用 ECS 抽象来建模 AI 训练系统，把任务调度、packet forwarding、ACK 处理等逻辑组织成可以跨实验批处理的 system，使同类组件在内存中按列紧密排布。一旦模拟器被写成这种形状，GPU 就自然成为合适的执行后端，因为整个工作流已经非常接近“对大数组上的相同逻辑做重复计算”。换句话说，论文的贡献并不只是把一个 CPU 模拟器移植到 CUDA，而是先重构模拟器，让跨实验的一致性本身变成可利用的并行性。

## 设计

Multiverse 主要由四部分组成。System simulator 接受类似 ASTRA-sim 的 workload 图输入，其中每个 GPU 上的节点要么是计算，要么是 collective communication。它支持 TP、DP 等训练并行策略；对于跨服务器的 collective operation，它会先把 collective 展开成 point-to-point flow，再交给网络部分决定这些 flow 的完成时间。另一个 GPU memory simulator 会在探索某个配置之前先检查是否会超过显存上限，如果会就直接返回 OOM。

体系结构上最关键的切分，是把机内通信和机间通信分开处理。对 inter-server 流量，Multiverse 保留 packet-level 的 discrete-event network simulator，这样拓扑与拥塞控制的影响仍然是显式可见的。对 intra-server 通信，作者认为 packet-level 模拟既慢也不准，因为 NVIDIA 的本地通信协议并不开源，而且 NCCL 运行时会引入明显的软件栈开销。于是 Multiverse 通过 profile NCCL 行为，构造了一个按 collective 类型、GPU 类型和服务器配置校准参数的线性模型 `y = alpha + comm_size / beta`。对于 compute 与 communication 的重叠，它也用经验模型去修正计算时间。

模拟器内部状态则由一组 ECS entity 表达，例如 `Task`、`Flow`、`Sender`、`IngressPort`、`EgressPort` 和 `Receiver`。组件被存成跨所有实验共享的列式表格，每一行额外带一个隐式的实验编号。各个 system 通过 query 选中匹配的 archetype，然后对这些列执行逻辑。论文强调，这种跨实验共享存储能提升访问相干性：相邻的 GPU 线程即使处理的是不同实验，也可以连续读取相邻组件值，而不是在许多独立进程或堆对象之间来回跳。

每个 simulation step 都执行一张固定的 system graph：先调度任务依赖，再用解析模型模拟机内 collective，然后把 point-to-point flow 注入网络，再让 packet 穿过 NIC 和交换机实体，最后产生 ACK。为了让这套流程适合 GPU，运行时不会给每个 ECS stage 单独发一个 CUDA kernel，而是把所有 system 函数连同它们的 wrapper 一起编译成一个 megakernel。这样 GPU 可以在一次启动之后完成整批模拟任务，避免 CPU-GPU 之间反复的 kernel launch 开销。

论文提出的三个优化实际上都很关键。第一，pull-based synchronization 把 many-to-one 写冲突改写成无锁的两阶段协议：源端先登记意图，目的端稍后主动把待处理数据 pull 过来。第二，校准过的 intra-server 模型避免了在 NVLink/PCIe 流量上浪费 GPU 计算资源做“伪 packet 模拟”。第三，megakernel 让大批量多实验在每个阶段都有足够的工作量，从而真正吃满 GPU，而不是被频繁启动 kernel 的开销拖住。

## 实验评估

评估把 Multiverse 与 ASTRA-sim+UNISON、ASTRA-sim+DONS，以及一个 single-experiment 版本的 Multiverse 做比较。实验机器是一台带单张 H100 GPU、80 核 CPU 和 256 GB 内存的服务器。测试场景也不是玩具例子，而是比较接近真实设计空间搜索：128-GPU GPT-3 13B 集群上的 10,000 次拓扑搜索，1,024-GPU LLaMA 65B 集群上的 500 次 collective-communication 参数调优，8,192-GPU GPT-3 175B 集群上的 100 次 TP/DP/PP 组规模搜索，以及一个模拟 54,000-GPU GPT-dense 集群上的拥塞控制比较。

最核心的结果是探索吞吐量。在前三类用例里，Multiverse 比其他模拟器快 57.4-73.2x，相比只跑单实验的 Multiverse 版本也仍然快 1.7-7.3x。论文给出的解释是可信的：SPME 消除了重复的内存与调度成本，ECS/DOD 降低了 cache miss，而 GPU 后端又把 CPU 批处理无法挖出的并行性利用了起来。最大规模结果也很有意思：单张 H100 可以模拟一个 54k-GPU 的训练集群，并且相对先前方法仍有 28.6-43.1x 的速度优势。

第二根支柱是准确性。对于一台含 8 张 A100 的服务器上的机内 collective，ASTRA-sim 默认解析模型在小消息时会出现 20%-72% 的误差，而 Multiverse 的校准模型把误差压到约 0.7%-1.2%。在端到端层面，LLaMA 65B 与 GPT-3 175B 在真实 H100 集群上的 iteration time，与 Multiverse 的模拟结果在 128 和 1,024 GPUs 两种规模下都相差不到 3%。因此，这篇论文的主要论点是成立的：它不是靠把模拟器变成一个粗糙估算器来换速度，而是在保真度基本守住的前提下加速了探索过程。

当然，评估最强的是吞吐量与 iteration-time fidelity，较弱的是部署广度。硬件目标明显偏向 NVIDIA，比较也主要围绕单机模拟主机展开，而不是分布式模拟后端。但如果把目标限定为“更快地做探索”，这些结果已经相当有说服力。

## 创新性与影响

这篇论文的创新不在于单独某一个部件，而在于把三件事组合起来：把很多实验放进一个模拟器进程里执行，用 ECS/DOD 方式重写模拟器让逻辑可以跨实验批处理，再把这种结构直接映射到 GPU 上。ASTRA-sim 关注分布式训练系统建模，DONS 展示了 DOD 对网络模拟的价值，UNISON 则强化了 CPU 侧的并行网络模拟；而 Multiverse 把“设计空间探索本身”当作优化对象，这是它真正新的地方。

这对构建和调优大规模 AI 集群的人都很有意义。训练系统研究者可以把它看作一个证据：模拟器吞吐量已经成为一阶瓶颈。网络设计者可以更激进地搜索拓扑和拥塞控制方案。更一般地说，这篇论文展示了一个很典型的 systems move：不再只问“怎么把单次运行做快”，而是改问“整个搜索过程里有哪些共享结构值得利用”。

## 局限性

Multiverse 的保真度依赖多处经验校准，而不是完全公开、从原理出发的模型。机内通信模型来自对 NCCL 行为的测量，并且按 GPU/算子组合做专门拟合，因此每当硬件代际或运行时版本变化时，都可能需要重新 profile。同样地，计算与通信重叠的影响也是通过拟合模型得到的，而不是通过第一性原理模拟出来的。

实现覆盖面也比它的动机陈述更窄。Implementation 一节写到，当前代码基线支持 TP、DP，以及有限的 collective 和拥塞控制算法；这使得 pipeline parallelism 与更完整训练特性的支持范围在论文中显得有些不够清楚。最后，虽然论文用真实的 128/1,024-GPU H100 集群验证了 iteration time，但最大 54k-GPU 结果只能依赖模拟本身。因此，它非常有力地证明了“探索可以快很多”，但在极端规模上的现实可信度仍有一部分建立在外推之上。

## 相关工作

- _Rashidi et al. (ISPASS '20)_ - ASTRA-sim 建模的是分布式训练系统的软硬件栈，而 Multiverse 进一步解决“怎样把大量此类模拟快速跑完”这个被忽略的问题。
- _Won et al. (ISPASS '23)_ - ASTRA-sim 2.0 扩展了对分层网络与解耦系统的建模，而 Multiverse 的主要贡献是围绕探索吞吐量重新设计执行架构。
- _Gao et al. (SIGCOMM '23)_ - DONS 证明了 DOD/ECS 可以在 CPU 上加速网络模拟；Multiverse 则把这类结构推广到 AI 训练实体，并扩展成跨实验的 GPU 批处理执行。
- _Bai et al. (EuroSys '24)_ - UNISON 通过高效 CPU 多线程来加速 ns-3，但 Multiverse 认为对 LLM 训练探索来说，single-process multi-experiment 比大量 CPU 侧并行运行更合适。

## 我的笔记

<!-- empty; left for the human reader -->
