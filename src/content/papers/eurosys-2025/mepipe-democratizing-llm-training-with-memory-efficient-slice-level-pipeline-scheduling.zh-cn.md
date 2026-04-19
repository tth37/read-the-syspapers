---
title: "MEPipe: Democratizing LLM Training with Memory-Efficient Slice-Level Pipeline Scheduling on Cost-Effective Accelerators"
oneline: "MEPipe 把样本切成序列切片并重排流水线，让 24 GB RTX 4090 也能训练更大的 LLM：显存峰值更低，空泡更少，而且不额外增加跨卡通信。"
authors:
  - "Zhenbo Sun"
  - "Shengqi Chen"
  - "Yuanwei Wang"
  - "Jian Sha"
  - "Guanyu Feng"
  - "Wenguang Chen"
affiliations:
  - "Tsinghua University"
  - "Zhipu AI"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717469"
project_url: "https://zenodo.org/records/14942680"
tags:
  - llm-training
  - gpu
  - memory
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

MEPipe 针对的是一个很现实的训练平台空档：像 RTX 4090 这样的廉价 GPU 算力不差，但显存只有 24 GB，互连也远弱于 A100 这一档。它提出的核心机制是 Sequence Virtual Pipeline Parallelism，也就是把流水线调度粒度从 micro-batch 下探到 sequence slice，让系统只需保留少量切片的激活，而不是整串 micro-batch 的激活，再用细粒度 weight-gradient GEMM 去填平剩下的空泡。论文在 64 张 RTX 4090 上报告，相比已有方案最高可快 1.68x，训练 Llama 13B 时达到 35% MFU，而且迭代时间已经接近 32 张 A100 的集群，同时资本成本效率高 2.5x。

## 问题背景

这篇论文的出发点不是「怎么把训练再做快一点」，而是「怎么把训练从昂贵硬件上解放下来」。作者给出的市场对比很直白：按照他们在 2024 年 10 月观察到的价格，一台 8 卡 A100 + NVLink 服务器，大约是一台 8 卡 RTX 4090 服务器的 5 倍价钱。问题在于，LLM 训练最依赖的两样资源，恰好是 4090 最缺的：显存容量和卡间带宽。

传统并行策略在这个硬件档位上都不够理想。Tensor parallelism 和 context parallelism 虽然能把模型状态或序列状态切开，降低单卡显存压力，但它们要求在每层前向和反向中频繁通信；对 PCIe 互连的 4090 集群来说，这个代价太高。Pipeline parallelism 的跨卡通信最少，看起来更适合廉价 GPU，可经典调度为了减少空泡，往往要求早期 stage 在第一次 backward 之前先攒下很多 forward pass 的激活，这又撞上了 24 GB 显存的硬约束。

更接近的方案是 TeraPipe 一类的 sequence pipeline parallelism。它把单个样本切成更小的序列片段，确实能降低 bubble ratio，也让单次 forward 的激活更小，但它的调度方式依旧是把所有 forward 都跑完才启动第一轮 backward。这样一来，worker 仍然要同时保留太多激活。MEPipe 要解决的因此不是某一个局部瓶颈，而是一个组合难题：能不能在不引入额外通信的前提下，把激活驻留时间压到足够低，让便宜 GPU 真能放下 LLM 训练？

## 核心洞察

作者最关键的判断是，流水线调度真正该优化的对象，不是 micro-batch 数量，而是第一次 backward 之前同时活着的 sequence slice 数量。只要能在依赖允许的最早时刻，把 forward 和 backward 交错到 slice 粒度，峰值激活占用就会从「若干完整样本」变成「少量切片」。

但 slice 级调度本身会引入两个新问题。第一，decoder-only 模型里后面的 slice 比前面的 slice 更重，因为 attention 需要依赖更多先前 token 的 key/value。第二，当模型再被切成多个 virtual pipeline chunk 以后，slice 与 chunk 之间的依赖关系会变复杂。MEPipe 的做法是把这两个问题拆开处理：先用 SVPP 构造一个合法、低显存的 slice 调度，再用细粒度 weight-gradient 计算去吸收 slice 之间的不平衡和迭代尾部的空泡。

## 设计

MEPipe 基于 Megatron-LM 和 PyTorch 实现，包含 profiler、SVPP scheduler、execution engine 三部分。profiler 负责测目标模型和目标硬件上各类 forward、backward 的耗时与显存占用；scheduler 根据这些测量结果以及 `p`、`v`、`s`、`n` 等参数，决定第一次 backward 前允许多少个 forward pass，并从多个候选调度里选出满足显存约束的版本。

SVPP 同时融合了两种切分思路。它像 sequence pipeline parallelism 一样，把单个样本切成多个 sequence slice；又像 virtual pipeline parallelism 一样，把模型切成更细的 chunk，并允许一个 worker 持有多个 chunk。之后，系统在 slice 粒度上交错安排 forward 和 backward，同时严格遵守因果注意力的依赖关系：某个 stage 上的后续 slice，不只依赖本 stage 的前一 slice，还依赖前一 stage 上对应 slice 的输出。

论文真正实用的地方，在于它没有把 SVPP 写成单一调度，而是系统性地产生多种合法变体，再根据显存预算选其中 bubble ratio 最低的一种。作者构造的 memory model 把显存拆成三部分：参数、梯度、优化器状态等 static memory；算子临时 workspace；以及在某一时刻必须保留的 activation。这样一来，调度就能和设备能力绑定起来。显存更宽裕的卡，可以在第一次 backward 前多放一些 forward 来缩短空泡；24 GB 级别的设备，则需要把部分 forward 延后到 backward 启动之后。

第二个关键机制是细粒度 weight-gradient computation。作者借鉴 Zero Bubble pipeline parallelism 把 activation-gradient 和 weight-gradient 分开计算的思路，但进一步把 weight-gradient 拆成单个 GEMM 任务。反向传播时，这些 GEMM 会先进入队列；一旦某个 stage 因等待前后相邻 stage 的张量而出现空档，就把这些 GEMM 拿出来执行。这样做一方面能把通信等待变成有效计算，另一方面也能缓解不同 slice 之间由于 attention 开销递增带来的负载不均衡。

## 实验评估

实验平台是 8 台服务器组成的集群，每台有 8 张 RTX 4090 24 GB GPU，节点内通过 PCIe 4.0 连接，节点间是 100 Gbps InfiniBand。工作负载覆盖 Llama 2 的 7B、13B、34B 模型。基线并不弱，作者比较了 DAPPLE、VPP、Zero Bubble、ZBV，并且对 PP、CP、VP、recomputation 做了穷举搜索，尽量找出每种方案在对应场景下的最好组合。

结果说明 MEPipe 的收益确实来自它瞄准的那个硬件区间。论文报告，在 64 张 RTX 4090 上，相比已有方案最高可提升 1.68x，平均提升 1.35x。训练 Llama 13B 时，MEPipe 达到 35% MFU 和 116 TFLOPS 峰值性能。更重要的是，作者在动机分析里展示了机制层面的因果链：当 sequence-pipeline size 取 4 和 8 时，SVPP 对峰值 activation memory 的削减分别超过 70% 和 80%，这正是便宜 GPU 能否放下训练的关键。

这些对比也基本支撑论文的中心论点。DAPPLE 往往需要借助 context parallelism 或 recomputation 才能塞进显存，于是要么多付通信代价，要么多付重算代价。VPP 和 ZBV 确实能减少 warmup/drain 阶段的 bubble，但 chunk 更多以后，参数和梯度的静态显存也会上升，能用的 pipeline depth 反而被限制住。MEPipe 的好处在于，它靠调度本身压低 activation，而不是把压力转移到通信或额外计算上。除此之外，细粒度 weight-gradient 机制还在同一套调度上再带来 9.4% 的性能提升。

论文最后给了一个很有说服力的经济学对照。作者把 64 张 RTX 4090 的集群和 32 张 A100 80GB 的集群放在一起测，发现三种 Llama 模型的最优迭代时间已经相当接近。由于他们当前实现里用 FP32 做 GEMM accumulation，单张 4090 的实际吞吐大约只有单张 A100 的一半，但整机价格仍然差了约 5 倍，所以整体算下来，RTX 4090 集群依旧有 2.5x 的成本效率优势。

## 创新性与影响

MEPipe 的新意不在于单独发明了某一种并行手段。低 bubble 的 pipeline schedule、virtual chunk、recomputation、sequence slicing，这些前人都做过。它真正新的地方，是把目标重新定义成「在低带宽、低显存设备上，靠调度而不是靠额外通信，把 activation 驻留压下来」。SVPP 是这篇论文的核心，因为它不再把更低的 bubble ratio 当成唯一目标，而是把显存峰值一起纳入调度设计。

这让它的影响范围不止于 RTX 4090。凡是想在受限加速器、PCIe-only 服务器，或者未来更便宜的训练硬件上跑 LLM 训练的人，都可以借用这套思路：先建立足够精确的 memory model，找出合法且低显存的 slice 调度；再用延迟执行的梯度工作去吃掉剩余空泡。就系统论文而言，这比单纯说一句「廉价 GPU 也能训练」要扎实得多。

## 局限性

MEPipe 的适用范围并不宽。它的调度逻辑明显建立在 decoder-style causal attention 的依赖结构之上，论文没有讨论 encoder-decoder 或更不规则模型会发生什么。实验也主要是吞吐导向的：作者跑的是 100 次 iteration 的性能评测，重点看 iteration time、MFU 和显存是否装得下，并没有给出完整预训练过程中的最终收敛质量。

这套系统还依赖相当多的离线选择。最优的 PP、CP/SPP、VP 以及具体调度变体，都是靠 profiling 和 grid search 找出来的，作者也明确承认搜索空间过大会带来额外开销。与此同时，SPP 不能无上限地继续增大，因为一旦切得太细，GEMM 和 FlashAttention 这类算子的效率会明显下降，bubble ratio 的收益会被算子级退化抵消掉。

最后，硬件层面的现实问题并没有被这篇论文消除。作者自己就提到，成百上千张 RTX 4090 组成的大集群会遇到可靠性挑战，FP16 训练容易出现 overflow 和 underflow，而在等效算力下，4090 集群的功耗也高于 A100 集群。MEPipe 解决的是「能不能更便宜地训」，不是「便宜硬件天然没有运维成本」。

## 相关工作

- _Fan et al. (PPoPP '21)_ - DAPPLE 把 1F1B pipeline scheduling 做成了经典基线，而 MEPipe 进一步把调度粒度从 micro-batch 下探到 sequence slice，从根上减少需要同时保留的激活。
- _Li et al. (arXiv '21)_ - TeraPipe 提出了 sequence pipeline parallelism，但 MEPipe 认为它先跑完所有 forward 再启动 backward 的方式，仍然会在小显存 GPU 上留下过高的 activation 驻留。
- _Qi et al. (ICLR '24)_ - Zero Bubble pipeline parallelism 通过延迟 weight-gradient 来填补尾部空泡，MEPipe 则把这个思路继续细化到单个 GEMM，用来同时处理 slice 级不均衡。
- _Sun et al. (ASPLOS '24)_ - AdaPipe 借助自适应 recomputation 和 repartitioning 来应对 stage 间显存不均衡；MEPipe 的路线则是先选出更省显存的 schedule，尽量避免把额外代价落到重算上。

## 我的笔记

<!-- 留空；由人工补充 -->
