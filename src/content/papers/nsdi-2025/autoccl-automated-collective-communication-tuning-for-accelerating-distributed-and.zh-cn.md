---
title: "AutoCCL: Automated Collective Communication Tuning for Accelerating Distributed and Parallel DNN Training"
oneline: "AutoCCL 针对每类 collective 在线调优 NCCL，把实现选择与资源旋钮分开搜索，并在真实训练的计算-通信干扰下收敛到更快配置。"
authors:
  - "Guanbin Xu"
  - "Zhihao Le"
  - "Yinhe Chen"
  - "Zhiqi Lin"
  - "Zewen Jin"
  - "Youshan Miao"
  - "Cheng Li"
affiliations:
  - "University of Science and Technology of China"
  - "Microsoft Research"
  - "Anhui Province Key Laboratory of Biomedical Imaging and Intelligent Processing, Institute of Artificial Intelligence, Hefei Comprehensive National Science Center"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/gbxu/autoccl"
tags:
  - llm-training
  - gpu
  - networking
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AutoCCL 把 NCCL 调优从“离线跑一堆 benchmark”变成“训练过程中的在线系统问题”。它先把实现层面的选择和资源分配层面的旋钮拆开，再在真实训练前几轮里边跑边测，直接在存在计算-通信干扰的环境中找到更快的 collective 配置。

## 问题背景

这篇论文抓住了一个分布式训练论文里常被默认忽略的前提: 很多做 overlap、scheduling 或新 collective algorithm 的工作，都默认底层通信库已经调得差不多了。但实际情况是，NCCL 内部仍然要为每个 collective 决定大量低层参数，而默认选择对某个具体的 primitive、消息大小、通信组规模和硬件拓扑来说，经常并不是最优。论文里的例子表明，只改这些配置就可能带来 20% 以上、甚至更高的带宽差异。

这个问题之所以重要，是因为现代训练任务会反复执行海量 collective。单个 iteration 内，AllGather、ReduceScatter、AllReduce 往往会在不同并行维度和不同消息大小上重复成千上万次。用一个全局固定配置显然太粗，而对每种任务暴力穷举又太贵: 候选空间可达数百万组合，光给一个通信任务做完整搜索就可能花掉数小时。

更麻烦的是，真实训练并不等于“纯通信 benchmark”。训练过程中，通信通常和计算并发执行，双方会争夺 GPU 的 SM、cache 和 memory bandwidth。某个配置在孤立环境下表现最好，并不代表在 GEMM 和训练框架调度一起出现时仍然最好。换句话说，系统必须在真实运行环境里调优，而不是在与部署脱节的离线实验里调优。

## 核心洞察

论文的第一层洞察是把 NCCL 的选择拆成两类。Algorithm、protocol 和 transport 决定 collective “怎么实现”；`nchannel`、`nthread` 和 chunk size 决定在这个实现里“怎么分配资源”。一旦这样拆开，搜索问题就容易多了: 先枚举数量不大的 `<A, P, T>` 实现子空间，再在每个子空间里优化资源旋钮，而不是一次性在整个笛卡尔积空间里搜索。

在固定 `<A, P, T>` 的前提下，作者进一步观察到 `NC`、`NT` 和 `C` 对带宽的联合影响呈现一种带有 sweet point 的单峰形态。起初增大这些参数会提升并行度，但当拥塞和资源竞争继续上升后，收益会趋平甚至下降。只要这个形态大体成立，coordinate descent 就足够有效。AutoCCL 因而不试图精确重建整个 GPU 和网络系统的解析模型，而是利用这个“局部上山即可”的结构快速逼近最优点。

第二层洞察更偏系统实现: 训练前几轮中反复出现的相同 collective，本身就是在线 profiling 的机会。只要在这些真实执行中轮流试探候选配置，并记录对应时间，调优器就能自动吸收计算干扰、硬件细节和运行时调度带来的影响，而不必显式建模这些高度动态的因素。

## 设计

AutoCCL 先把 NCCL 的低层调优空间收敛为六个关键旋钮: algorithm、protocol、transport、channel 数、thread 数和 chunk size。随后，它按 `<A, P, T>` 把整个空间切成多个实现子空间。对于每个子空间，系统在 `NC`、`NT`、`C` 三个维度上执行 coordinate descent: 每次只改一个维度，测量带宽是否提升，若提升则保留该方向并继续前进，否则切换到下一个维度。每个子空间找到局部最优后，再在所有子空间之间选出全局最优配置。

论文给出的带宽模型并不追求精确数值，而是提供足够合理的结构解释。它把一次 collective 的执行分成两个串行阶段: transport 阶段负责在 GPU 之间搬运 chunk，protocol 阶段负责把 buffer 数据搬到 SM 上做 reduction，再写回 buffer。总体带宽取决于这两个阶段中的较慢者。这个视角很好地解释了为什么 `NC`、`NT`、`C` 会彼此耦合，以及为什么把这些资源盲目开大最终会因为拥塞而适得其反。

系统结构上，AutoCCL 与原始 NCCL 的最大区别在于引入了 Leader/Worker 分工。普通 NCCL 里，每个 peer 都根据确定性的 cost model 独立推导默认配置；AutoCCL 则让每个通信组中的一个 GPU 担任 Leader。Leader 内部有 `Optimizer` 和 `Coordinator` 两个组件: 前者收集历史执行时间并决定下一次要试的配置，后者把新配置以原子方式广播给整个通信组。其他 GPU 作为 Worker，只需在本地 config table 中选择“默认配置”或“最新调优配置”并执行。

在线调优之所以可行，关键在于它把开销摊进了训练前期。相同 collective 每出现一次，就推进一小步搜索，而不是预先停机做完整 benchmark。Leader 一旦收敛，后续所有相同任务都会统一切换到调优后的配置。论文实现基于 NCCL 2.18.3，总计 9,176 行 C++，保持 NCCL 原始接口不变，因此 PyTorch 和 MegatronLM 这类框架可以通过替换动态库来接入 AutoCCL，而不需要改模型代码。

## 实验评估

评估覆盖两套 A40 集群: 一套是 2 节点、节点内 NVLink、节点间双 400 Gbps InfiniBand；另一套是 4 节点、节点内 PCIe、节点间 100 Gbps InfiniBand。工作负载既包括通信 microbenchmark，也包括 Phi-2-2B、Llama-3.1-8B、Yi-1.5-34B 和 VGG-19 的端到端训练，对比对象是原生 NCCL 和离线调优器 AFNFA。

在无计算干扰的 microbenchmark 中，AutoCCL 相比 NCCL 和 AFNFA 的平均带宽提升分别达到 1.24-1.29x 和 1.15-1.22x，某些具体点位更高。这里最重要的结论不是某一个单点数字，而是“最优配置随 primitive、消息大小和拓扑变化而显著变化”，说明 NCCL 的内置 cost model 只在少数场景下能猜对。论文还展示了一个值得注意的现象: 即使是已经被高度优化的 NVLink 环境，低层参数调优仍然有明显空间。

带计算干扰的实验更能体现在线设计的价值。对一个代表性的 128 MB 配置，AutoCCL 在并发 GEMM 压力下把 AllGather、ReduceScatter 和 AllReduce 的带宽分别提升到 NCCL 的 1.29x、1.50x 和 1.38x，而 AFNFA 往往只是和 NCCL 持平，甚至更差。更广泛地看，论文报告在“通信与计算并发”的 microbenchmark 里，AutoCCL 相比 NCCL 和 AFNFA 的收益最高可达 1.80x 和 1.49x。这个结果基本证明了论文的核心主张: 离线调优抓不住真实训练最关键的性能环境。

端到端训练收益比 microbenchmark 温和一些，这是合理的，因为它毕竟只是底层通信库优化。论文报告四个模型的 iteration time 降低幅度为 1.07-1.32x。作者还专门测了收敛速度: 大型 Transformer 因为同类 collective 重复次数极多，只需少量 iteration 就能收敛到较优配置；更小的 VGG-19 虽然重复度低一些，但也能在大约 10 分钟内完成调优。

## 创新性与影响

这篇论文的创新点不在于发明新的 collective algorithm，而在于把 NCCL 从“不可见的黑盒库”变成“可在线优化的运行时系统”。与 AFNFA 相比，差异主要有三点: 它是按通信任务逐类调优而不是使用全局固定配置；它依赖在线 profiling 而不是离线采样建模；它把计算-通信干扰视为一等公民，而不是假定通信总是在隔离环境中运行。

因此，这项工作即使不被原样采用，也会对训练系统设计者有参考价值。它传达出的更深层结论是: collective communication 的性能高度依赖工作负载相关的低层选择，而这些选择应该在训练循环内部被动态优化。AutoCCL 很可能影响未来的 NCCL 类库、训练运行时，以及希望在不改变模型语义前提下透明提速的 GPU 集群系统。

## 局限性

AutoCCL 的收益建立在“重复”之上。它之所以有效，是因为训练作业会在 layer 和 microbatch 维度上反复执行同一类 collective。对重复度很低、寿命很短，或者根本来不及摊销探索成本的任务，这套方法的收益会明显下降。论文自己的结果也体现了这一点: 小模型 VGG-19 需要更长的墙钟时间才能完成调优。

此外，论文的适用范围其实比标题暗示的更窄。实现严格绑定在 NCCL 2.18.3 和 NVIDIA GPU 集群上，最强的实验也都基于 A40 机器。作者认为其参数划分思路可以扩展到更多 transport-specific setting，但并没有在 RCCL 或显著不同的加速器/网络组合上做验证。

最后，这套搜索方法本质上仍是启发式的。Coordinate descent 的合理性来自作者观察到的单峰趋势，而不是证明所有工作负载在每个子空间里都一定满足这一性质。论文也承认激进调优可能触发失败，例如某些 transport-specific setting 会导致 deadlock，或者资源参数过大导致程序崩溃，因此 AutoCCL 主动回避了一些高风险旋钮，并对另外一些参数设置上界。这样的工程取舍很现实，但也意味着它用更保守的搜索范围换取了运行安全性。

## 相关工作

- _Wang et al. (APNet '23)_ - `AFNFA` 依赖离线 profiling 预测 NCCL 配置，而 `AutoCCL` 在真实训练过程中按通信任务在线调优，并显式面向计算干扰场景。
- _Shah et al. (NSDI '23)_ - `TACCL` 用 communication sketch 合成新的 topology-specific collective algorithm，`AutoCCL` 则保留 NCCL 现有实现，只调已有低层旋钮。
- _Cowan et al. (ASPLOS '23)_ - `MCCLang` 提供自定义 collective 的语言与编译器，而 `AutoCCL` 的目标是优化 commodity communication library 执行现成 collective 的方式。
- _De Sensi et al. (NSDI '24)_ - `Swing` 针对 torus network 重新设计 AllReduce，而 `AutoCCL` 更广但更浅，覆盖多个 primitive，并在既有硬件 fabric 上做参数级调优。

## 我的笔记

<!-- 留空；由人工补充 -->
