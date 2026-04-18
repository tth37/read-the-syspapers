---
title: "Ouroboros: Wafer-Scale SRAM CIM with Token-Grained Pipelining for Large Language Model Inference"
oneline: "Ouroboros 把 LLM 的权重、激活和 KV 缓存都留在晶圆级 SRAM CIM 中，再用 token 级流水、通信感知映射和分布式 KV 放置把利用率补回来。"
authors:
  - "Yiqi Liu"
  - "Yudong Pan"
  - "Mengdi Wang"
  - "Shixin Zhao"
  - "Haonan Zhu"
  - "Yinhe Han"
  - "Lei Zhang"
  - "Ying Wang"
affiliations:
  - "SKLP, Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
  - "University of Chinese Academy of Sciences, Beijing, China"
  - "Hangzhou Institute for Advanced Study, University of Chinese Academy of Sciences, Hangzhou, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790197"
tags:
  - hardware
  - llm-inference
  - memory
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Ouroboros 认为 LLM 推理里最贵的部分已经不是算术本身，而是权重、激活和 KV cache 在深层存储层次之间来回搬运。它因此把整个推理状态都放进晶圆级 SRAM-based computing-in-memory 硬件里，再用 token-grained pipelining、communication-aware mapping 和 distributed KV management 去解决这种全 SRAM 设计最容易出现的利用率瓶颈。

## 问题背景

这篇论文的起点首先是一个硬件判断，而不是调度判断：随着 LLM 规模增长，计算能耗已经不再是主导项，真正主导延迟和能耗的是片上到片外的数据移动，以及设备之间的通信。GPU、TPU，甚至已有的 wafer-scale engine，本质上都还依赖“SRAM 只是缓冲层，权重和 KV cache 还是要落到 HBM/DRAM”的层次化内存体系。这样的架构会产生作者所谓的 hardware scaling tax：模型越大、上下文越长，系统就越需要穿越高代价链路搬运数据。

把所有状态都塞进 SRAM 听起来很理想，但 wafer-scale SRAM CIM 会立刻带来另一组问题。SRAM 的密度远低于 DRAM，所以系统必须极其高效地利用有限的一层存储。在 Ouroboros 里，SRAM 阵列同时承担存储和计算职能，因此存储利用率低，往往也意味着计算利用率低。作者把问题归纳成三个具体失效模式。第一，sequence-level pipeline parallelism 会因为 prompt 长度不同、prefill 和 decode 混合执行而产生 bubble。第二，KV cache 随上下文增长，会把 SRAM 切成很多碎片，并连带浪费本可用来计算的资源。第三，当数千个 core 铺满整片晶圆后，如果按 stage 紧密聚拢会加重 stage 之间的数据传输；如果把不同 stage 交错摆放，又会加重单层内部 reduction 的通信。

## 核心洞察

论文最核心的主张是：要让全 SRAM 的晶圆级 LLM 加速器真正成立，必须把“利用率”当作一等公民来做软硬件协同设计。Wafer-scale CIM 只是消除了 deep-memory tax，但如果不进一步处理 bubble、碎片化和远距离通信，这种容量紧张的架构会在另一个维度上把收益重新丢掉。

因此，论文真正重要的不是某一个单点加速器技巧，而是三件事的组合。Token-grained pipelining 让流水线以 token 而不是整条 sequence 为最小单位，从而不再因为请求长度差异出现严重 stage 失衡。Communication-aware mapping 在 core 级放置 transformer layer 和 tile 时，同时优化 stage 间传输和 stage 内 reduction。Distributed KV cache management 则把已分配 core 中剩余的碎片 SRAM 重新组织成可用缓存，而且不依赖集中式控制。正是这三部分共同处理了“全 SRAM 前提”引入的主要利用率杀手。

## 设计

Ouroboros 是一块 215mm x 215mm 的 wafer-scale chip，由 9 x 7 个 die 组成，片上总共集成 54GB SRAM，推理路径中没有更深一级的二级内存。每个 die 内部是一个 13 x 17 的 CIM core 网格。单个 core 包含 128KB 输入缓冲、32KB 输出缓冲、4MB SRAM crossbar array、H-tree 互连、负责 softmax 等操作的 SFU，以及本地同步控制逻辑。

执行层面上，系统把每个 transformer block 完全展开成 6 个流水阶段：LayerNorm、QKV generation、score、softmax、projection 和 FFN。对于 decoder-only 模型，Ouroboros 引入 token-grained pipelining。也就是说，不再让一个 stage 处理一整条 sequence、另一个 stage 处理另一条 sequence，而是让不同 stage 分别处理不同 token。由于 causal mask 只要求当前 token 关注自己及之前的 token，因此在 prefill 阶段，token 的 QKV 一旦生成，就可以立刻和已有 token 做 attention 计算，而不必等待整条序列全部生成完成。这既避免了大部分由序列长度差异带来的 bubble，也把中间激活的存储需求从“整条序列”压缩到“单个 token”。对于 encoder 风格 attention，论文承认无法完全保留这一性质，所以 attention 阶段会退回带 blocking 的 sequence-level 执行，而其他阶段仍保持 token 粒度。

映射部分分成两层。Inter-core mapping 被建模为一个 MIQP 问题，通过对 Manhattan distance 和跨 die 传输加惩罚，把 layer tile 分配到各个 core。Intra-core mapping 则在 H-tree 拓扑上做动态规划，把 concatenation 尽量推向靠近根部的位置，把 reduction 尽量留在靠近叶子的地方，从而降低关键带宽段上的压力。这套映射同时也被做成 fault tolerant：如果某个存储权重的 core 失效，邻近 core 会组成 replacement chain，在亚毫秒级别完成局部 remapping，而不是重新运行全局放置。

KV 管理同样是分布式的。处于 attention 模式的 crossbar 会被切分成多个 logical block，并分别维护行列有效位。每个 transformer block 的 attention core 都维护自己的多级地址转换：先由类似页表的结构把 sequence 映射到若干 core，再由 core 内部 bitmap 和 crossbar controller 里的 block 元数据定位具体块。为了把“当前 token 的 attention 读取”和“下一个 token 的 KV 写入”分离开来，系统会把连续调度的 sequence 摆到不同 core 上；同时还把不同 head 分布到不同 core，以减轻 H-tree 上的 concat 压力。再配合基于阈值的准入规则，为后续 decode 扩张预留空间，降低 cache thrashing 与被迫驱逐。

## 实验评估

实验是基于模拟器完成的，但覆盖面算比较完整。作者用 CACTI、Synopsys DC、BookSim2、MNSIM 和 yield model 搭了一个 end-to-end simulator，测试对象包括 LLaMA-13B/32B/65B、Baichuan-13B、Qwen-32B，以及 BERT-large 和 T5-11B，数据集使用 WikiText-2。对比基线包括运行 vLLM 的 DGX A100、8x TPU v4、DGX+AttAcc，以及使用 WaferLLM 风格执行方式的 Cerebras WSE-2。

在 decoder-only 模型上，Ouroboros 的收益相当明显。对 13B 模型，平均吞吐提升是 5.4x；对 32B 模型，平均提升是 2.8x。论文也明确解释了为什么 32B 的提升较小：单晶圆上的 KV 容量不够大，导致流水线深度填不满，出现利用率下降。跨基线看，单位输出 token 的能耗相对 DGX A100 降低 84%，相对 TPUv4 降低 82%，相对 AttAcc 降低 78%，相对 WSE-2 降低 66%。摘要里给出的总结果是平均吞吐提升 4.1x、平均能效提升 4.2x，在 13B 模型上最高达到 9.1x 吞吐和 17x 能效。

消融实验能较好解释这些增益来自哪里。相对于一个由 64 个 die 通过 NVLink 互连、使用 static KV management 的基线，wafer-scale integration 本身带来约 1.15x 吞吐提升；再加入 CIM，提升扩大到 1.49x；加入 token-grained pipelining 后，达到 2.05x 吞吐和 0.51x 能耗。Spatial mapping 还能额外贡献约 1.17x 的吞吐提升，而 distributed KV management 最终把相对基线的总收益推到大约 1.99x 吞吐和 0.81x 能耗。两片晶圆运行 LLaMA-65B 的扩展实验也很关键：论文报告相对基线平均有 5.4x 吞吐提升和 79% 能耗下降，说明这种设计在模型继续变大时并没有失去优势，反而更受益。

## 创新性与影响

这篇论文的创新点并不只是“把 LLM inference 放到晶圆上”。真正的新意在于，它针对 memory-bound workload 做了 capacity-oriented 的软硬件协同设计。和 GPU/TPU 集群相比，Ouroboros 是从架构层面直接消掉 deep-memory traffic。和已有 CIM accelerator 论文相比，它的覆盖范围更广：TGP、distributed KV placement 以及 wafer-aware mapping 都是为端到端自回归 serving 服务的，而不是只优化某一个 operator。和已有 wafer-scale engine 相比，最大的区别是 SRAM 不再只是片上 cache，而是权重、激活、KV 数据和计算共同发生的地方。

因此，这篇论文最可能影响的是 accelerator architecture 和 LLM inference hardware 方向的研究者。它给出了一个相当明确的系统观点：对 memory-bound LLM 推理来说，牺牲一部分电路级峰值密度，去换取更大的 first-level SRAM 容量，可能才是更优的整体取舍。

## 局限性

最明显的局限是，整篇论文的结论都来自模拟器，而不是流片后的真实晶圆或实际部署。映射算法在 Xeon CPU 上需要数小时离线求解，这对静态放置可以接受，但意味着系统很难做更动态的重配置。结果里也已经暴露出单晶圆 KV 容量对 32B 模型的限制，所以即便有 54GB SRAM，这个设计也并非彻底摆脱了内存压力。对 encoder 的适配效果也明显更弱：T5-11B 相比基线平均只有 0.7x 吞吐提升，因为 blocked attention 又把 sequence-level stall 带了回来。最后，系统刻意采用 1/32 row activation ratio，把容量优先于峰值 TOPS，因此它优化的是 memory-bound 的 LLM inference，而不是一般性的高密度矩阵计算。

## 相关工作

- _Aminabadi et al. (SC '22)_ — DeepSpeed-Inference 研究的是跨加速器的 transformer 推理流水与并行，而 Ouroboros 试图从体系结构层面移除层次化内存和跨设备通信成本。
- _Hong et al. (MICRO '22)_ — DFX 在多 FPGA 平台上加速 transformer 文本生成，但仍依赖外部内存；Ouroboros 的目标是把整套推理状态都保留在晶圆片上的 SRAM 中执行。
- _Ham et al. (ISCA '21)_ — ELSA 主要优化 self-attention 这一类算子，而 Ouroboros 关注的是带有 KV 管理和映射策略的晶圆级端到端 LLM 执行。
- _Fujiwara et al. (ISSCC '22)_ — 这类 fully digital CIM macro 追求电路层面的 TOPS/W，Ouroboros 则明确牺牲部分电路密度，换取更大的 SRAM 容量和更好的端到端推理效率。

## 我的笔记

<!-- 留空；由人工补充 -->
