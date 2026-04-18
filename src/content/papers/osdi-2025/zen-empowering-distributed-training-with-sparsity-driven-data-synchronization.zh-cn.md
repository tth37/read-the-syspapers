---
title: "ZEN: Empowering Distributed Training with Sparsity-driven Data Synchronization"
oneline: "ZEN 用分层哈希把稀疏梯度均衡分到点对点同步路径上，再用 hash bitmap 压缩回拉阶段的索引开销，从而显著降低分布式训练通信时间。"
authors:
  - "Zhuang Wang"
  - "Zhaozhuo Xu"
  - "Jingyi Xi"
  - "Yuke Wang"
  - "Anshumali Shrivastava"
  - "T. S. Eugene Ng"
affiliations:
  - "Rice University"
  - "Stevens Institute of Technology"
  - "Unaffiliated"
conference: osdi-2025
code_url: "https://github.com/zhuangwang93/ZEN"
tags:
  - ml-systems
  - gpu
  - networking
category: llm-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ZEN 的出发点是一个算法层面的判断：稀疏梯度同步通常不应该继续沿用 ring collective，或者把 sparse tensor 粗暴地塞进参数服务器式流程里，而应该采用负载均衡的 point-to-point 分区同步。论文用驻留在 GPU 上的分层哈希来近似实现这个最优方案，不需要每轮先做一次昂贵的数据依赖分析；同时再用 hash bitmap 压缩 pull 阶段的索引表示。作者在天然稀疏和 top-k 压缩两类训练任务上报告，相比已有稀疏同步方法，ZEN 最多可把通信时间降低 5.09 倍，并把端到端训练吞吐提升到 2.48 倍。

## 问题背景

这篇论文关注的是分布式训练里越来越突出的老问题：GPU 计算性能涨得比网络带宽更快，结果梯度同步逐渐成为主要瓶颈。对 dense tensor 来说，Ring-AllReduce、BytePS 这类系统已经有相对清晰的最优性故事；但稀疏梯度不是简单把 dense 流程“减点数据量”就行。现代训练中的 sparsity 既可能来自模型本身，例如 embedding-heavy 的推荐和 NLP 模型，也可能来自梯度压缩算法，例如 top-k sparsification。理论上，稀疏性应该显著减少通信量；现实里，已有系统却没有把这个潜力吃干榨净。

作者认为问题在于，社区之前没有先把“跨 worker 的稀疏梯度究竟长什么样”刻画清楚。论文总结出三个关键性质。第一，overlap 会变化：不同 GPU 上的 nonzero index 往往部分重合，但重合程度既不固定，也不小。第二，聚合会让张量变稠密：多个 worker 的 sparse update 合并后，结果通常比任一单机上的张量更不稀疏。第三，nonzero 的分布高度 skewed：如果按索引范围把张量均匀切块，某些块里会聚集远多于平均值的非零元素，造成严重的通信热点。AGsparse、SparCML、OmniReduce 等现有方案各自抓住了一部分问题，却没有同时优化 overlap、densification 和负载均衡。

## 核心洞察

论文最重要的洞察是：稀疏同步首先是一个 design-space optimization 问题，其次才是编码和实现问题。作者把方案空间拆成四个维度：通信模式、聚合时机、分区方式和负载均衡方式。这样建模之后，可以证明真正可能达到通信最优的只剩两类方案：Balanced Parallelism 和 Hierarchical Centralization。

这个结论的价值在于，它把工程目标重写了。实践里通常更好的选项是 Balanced Parallelism，也就是 point-to-point、增量聚合、分区化并且通信负载均衡的同步方案。难点不在于“知道它更好”，而在于怎样以足够低的开销实现它。因为每个 worker 的 nonzero index 都在变，如果每轮都先收集全局索引分布，再算一个数据依赖的分区映射，成本会高得不可接受，而且还会让迭代时间变得不稳定。ZEN 的核心贡献正是在这里：它不是泛泛地“更好地利用 sparse gradients”，而是用一个数据无关、GPU 友好的构造，把理论上的最优方案近似落到了系统里。

## 设计

ZEN 会先根据论文推导出的代价模型，在运行时于两类理论最优方案之间做选择。它采样前几轮的 sparsity profiling，估计 densification 相关项，再比较 Balanced Parallelism 和 Hierarchical Centralization 的通信成本。作者在论文评测的工作负载里，最终选择的大多是 Balanced Parallelism。

系统的核心机制是一个两级的 hierarchical hashing algorithm，用它把 nonzero gradient index 映射到均衡的分区中，同时保证不丢信息。第一级 universal hash 决定一个 index 属于哪个目标分区，并且这一级 hash 在所有 worker 上保持一致，这样相同的 index 在 push 阶段一定会被送到同一个 server，后续才能正确聚合。第二级 hash 只负责决定该 index 在目标分区本地内存中的落点。为了让这个过程适合 GPU 并行执行，ZEN 组合了四个技巧：按目的地划分的 hash memory、减少碰撞的多重 hash 函数、保证跨 worker 一致性的第一级 hashing，以及无需全局锁的 read-after-write 检查，用来捕捉并发写入下的碰撞。若多次 rehash 仍失败，元素就退化到带 atomic append 的 serial 区域，因此整个过程是 lossless 的。

这样，push 路径就实现了 Balanced Parallelism：每个 worker 向每个 server 发送的稀疏流量大致相同，每个 server 聚合后的工作量也大致相同。论文还给出了 push 和 pull 两个方向的高概率 imbalance bound；在实现里，为此额外使用的 GPU 内存通常低于 150 MB。

pull 路径则针对另一个瓶颈：如果继续使用 COO 表示，聚合后更稠密的 sparse tensor 会携带大量 index 元数据，通信成本很高。ZEN 因此提出 hash bitmap。由于第一级分区映射已经固定，每个 server 只需要针对“理论上可能属于自己分区的索引集合”广播一个 bitmap；worker 再结合预先计算好的本地索引集合完成解码。这样一来，pull 阶段的索引通信总量固定为 `|G| / 32`，不再随聚合后 nonzero 的具体分布波动，也避免了 COO 或全量 bitmap 在高密度区间里的膨胀。

## 实验评估

评测部署在最多 16 台 AWS 节点上，每台有 8 张 V100、节点内 NVLink，节点间分别使用 25 Gbps 以太网或 100 Gbps EFA RDMA。工作负载覆盖两类场景：LSTM、DeepFM、NMT 的 embedding 梯度天然稀疏；以及 Llama3.2-3B、OPT-2.7B、Gemma2-2B 在 tensor parallelism 下使用 DGC top-5% 压缩后的梯度。对比基线包括 dense AllReduce，以及 AGsparse、SparCML 和 OmniReduce。

核心结果是，ZEN 基本在所有任务上都优于已有稀疏同步方法，而且随着集群规模增大，优势往往还会扩大。在 25 Gbps 网络下，针对天然稀疏任务，LSTM 在 16 台机器上相较 SparCML、OmniReduce、AllReduce 的训练吞吐分别最多提升 1.67 倍、2.48 倍和 3.1 倍；DeepFM 和 NMT 相对 OmniReduce 分别最多提升 1.44 倍和 1.51 倍。对压缩后的 LLM 任务，ZEN 最多可比 OmniReduce 快 1.68 倍、比 SparCML 快 2.19 倍、比 AllReduce 快 2.02 倍。即使换到 100 Gbps RDMA，这些收益依然存在：相对 OmniReduce，ZEN 最高还能达到 1.32 倍；相对 AllReduce，在 Llama3.2-3B、OPT-2.7B、Gemma2-2B 上分别快 64%、45% 和 44%。

只看通信阶段，结果与论文论证完全一致。ZEN 在 LSTM 上相对 AllReduce 达到最高 6.77 倍的通信加速，在 Gemma2-2B 上达到 3.51 倍；而 AGsparse 和 SparCML 在一些场景下甚至会落后于 AllReduce，因为 COO 元数据开销已经大到抵消稀疏性收益。额外的计算并没有把这些收益吃掉。以 DeepFM 大小的张量为例，hashing 额外开销约 6 ms，而在 25 Gbps 网络下，相对 AllReduce 节省的通信时间大约是 270 ms。准确率验证也比较干净：DeepFM 的每轮 test accuracy 与 AllReduce 完全一致；OPT-2.7B 在 DGC 下的 loss 曲线与 AGsparse 重合，说明 ZEN 改变的是通信成本，而不是优化语义。

## 创新性与影响

相对于 _Renggli et al. (SC '19)_，ZEN 的观点是 SparCML 代表的 hierarchical-centralization 并不是普适解；它只是两个理论最优族中的一个，而且在考虑 overlap 和 skew 之后，往往并不是实践里的赢家。相对于 _Fei et al. (SIGCOMM '21)_，OmniReduce 同样试图做稀疏 collective communication，但它的静态 block partitioning 在 nonzero 分布不均时会留下明显性能损失。相对于 _Jiang et al. (OSDI '20)_，BytePS 优化的是 dense distributed training 在 heterogeneous cluster 上的通信，而 ZEN 的贡献是让“利用 sparsity 本身”变成一个可分析、可负载均衡、可实现的系统问题。

更广义地说，这篇论文把 sparse synchronization 从“若干经验性格式和工程技巧的组合”，推进成了“有定理支撑的系统设计问题”。它同时给出了设计空间分析、一个可落地的 GPU 哈希构造，以及一个专门针对聚合后高密度区间的索引编码方案，因此影响力不太像一次性原型，更像一个可被后续训练系统复用的机制。做稀疏 embedding 训练或大模型压缩训练运行时的人，都会很自然地把它当成一个系统部件来引用。

## 局限性

论文明确承认 Balanced Parallelism 并不是在所有场景下都最好。如果张量极度稀疏、不同 worker 之间几乎没有 overlap，那么 Hierarchical Centralization 仍然可能更优；作者用 batch size 为 1、8 张 GPU 的 NMT 例子展示了这个极端情况。这意味着 ZEN 的理论结论是带条件的，运行时的方案选择逻辑本身就是系统的一部分，而不是可有可无的包装。

实现范围也比论文的总论述更窄。对天然稀疏场景，系统只在 embedding layer 的跨机梯度上启用稀疏同步；对压缩场景，评测集中在 DGC 的 top-5% 设定，而不是更广泛的压缩器和 sparsity level。原型还依赖自定义 CUDA hashing、额外的 GPU 内存，以及对 ColossalAI 和 PyTorch 通信 hook 的修改。最后，实验虽然已经足够有说服力，但规模仍然有限：最多 16 台 AWS V100 节点、两种网络配置，能证明思路成立，却还不足以完全覆盖更新的加速器、互连和超大规模 fabric。

## 相关工作

- _Renggli et al. (SC '19)_ — SparCML 对应的是 hierarchical centralization，而 ZEN 的主要论点是：只有在异常低 overlap 的稀疏区间里，这才会是更好的选择。
- _Fei et al. (SIGCOMM '21)_ — OmniReduce 已经使用了稀疏的 point-to-point 聚合，但它的 block-based partitioning 在 nonzero 分布 skewed 时容易失衡，ZEN 的 hierarchical hashing 正是为了解决这一点。
- _Jiang et al. (OSDI '20)_ — BytePS 优化的是 heterogeneous GPU/CPU 集群上的 dense 通信，而 ZEN 聚焦的是如何利用并均衡 sparse gradient 本身。
- _Li and Hoefler (PPoPP '22)_ — Ok-Topk 研究的是压缩场景下的 sparse allreduce，而 ZEN 试图分析更广义的 sparse synchronization 设计空间，并给出一个数据无关的近似最优构造。

## 我的笔记

<!-- 留空；由人工补充 -->
