---
title: "DFVG: A Heterogeneous Architecture for Speculative Decoding with Draft-on-FPGA and Verify-on-GPU"
oneline: "DFVG 把 speculative decoding 拆成 FPGA drafting 与 GPU verification，并用自适应分支和跨设备重叠执行同时提升吞吐与能效。"
authors:
  - "Shaoqiang Lu"
  - "Yangbo Wei"
  - "Junhong Qian"
  - "Dongge Qin"
  - "Shiji Gao"
  - "Yizhi Ding"
  - "Qifan Wang"
  - "Chen Wu"
  - "Xiao Shi"
  - "Lei He"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Eastern Institute of Technology, Ningbo, China"
  - "Southest University, Nanjin, China"
  - "Ningbo Institute of Digital Twin, Ningbo, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790153"
code_url: "https://github.com/ShaoqiangLu/DFVG"
tags:
  - llm-inference
  - hardware
  - gpu
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

DFVG 的核心主张是，speculative decoding 不该把 draft 和 verify 都塞进同一种处理器里。它把小 draft model 放到 FPGA，把大 verifier 留在 GPU，再用置信度与硬件预算共同驱动的动态分支、加上跨设备流水重叠，把吞吐和能效一起推高。论文报告的最好结果是 `3.26x` 加速和 `5.79x` 能效提升。

## 问题背景

这篇论文抓住的是 speculative decoding 里一个常被忽略的结构性失配。draft model 很小，偏带宽敏感、偏低延迟；verify model 很大，更像一个计算密集、接近 prefill 的工作负载。如果两者都放在 GPU 上，它们会争夺显存容量与带宽，却又无法共享同样的并行模式；如果都放在 CPU 上，verification 的吞吐又明显不够。于是系统不是在加载权重、等待阶段切换，就是让某类资源处于闲置状态。

现有系统的另外两个选择又把这个问题进一步放大。第一，很多 speculative decoder 使用固定形状的 draft tree，高置信度位置不能趁着硬件还有余量多分几条分支，低置信度位置却仍然会生成大量大概率被拒绝的候选。第二，draft 与 verify 常常只是“松耦合”地串接起来。一旦 acceptance 下降，系统会同时付出两种代价：被拒绝 token 触发 rollback，而另一侧设备还要为同步等待。论文的判断是，这些问题不能拆开看。硬件放置、分支生成和流水调度必须一起设计，否则 speculative decoding 理论上的收益会被利用率损失吃掉。

## 核心洞察

DFVG 最重要的洞察是，speculative decoding 天然就是异构的。draft generation 顺序性强但单步计算轻，很适合 FPGA 的流式流水线、细粒度并行和更低单位能耗；verification 则是密集、可批处理的大模型前向，更适合 GPU。只要把两个阶段放到更匹配其瓶颈的硬件上，剩下要解决的事情就是怎样让两个设备都忙起来，别让 PCIe 传输和 rollback 成为主导成本。

第二个洞察是，speculative tree 也应该同时适配模型置信度和硬件预算。DFVG 不再使用固定 branching pattern，而是在总分支数、每层并行度、以及隐藏 verifier 延迟所需最小深度的约束下，尽量最大化“预计能被接受的 token 数”。随后，它再把这棵树重排成更适合 GPU 的 block 化 verification 工作。换句话说，论文的关键不只是“把 draft 放到 FPGA”，而是“把 speculation 的形状也改造成 FPGA 和 GPU 都擅长处理的工作形态”。

## 设计

算法核心是 ADAPT，也就是一个带预算约束的 speculative tree 构造过程。论文为“某个节点是否选择某个 token”定义了二值变量，并把优化目标写成“最大化预期通过 verification 的 token 数”。约束有三类：总分支预算不能超过可用资源；每层分支数不能超过硬件并行度上限；tree depth 还必须足够深，才能让 FPGA drafting 覆盖掉 GPU verification 的延迟。由于在线求解整数规划太贵，DFVG 采用贪心近似：先用路径累计概率给候选分支打分，再做带温度的 softmax 归一化，最后用 Gumbel sampling 选择不重复的分支。这样一来，高置信度且硬件有余量时树会变“胖”，低置信度时则自动变“瘦”。

第二个关键机制是 TreeSort-Verify。原始的 tree verification 会在 GPU 上产生很不规则的 causal mask，导致访存局部性和向量化都不好。DFVG 通过重排节点顺序，把祖先关系变成 block-diagonal lower-triangular 的结构，再把 verification 分解成多个独立 block，交给标准高吞吐 GEMM kernel 来执行。这一点很重要，因为论文并不是仅靠“把 draft 从 GPU 挪走”获胜，它还显著降低了 tree-based speculation 在 verifier 这一侧的执行税。

硬件部分围绕一个 FPGA multi-core overlay processor 展开。它包含 HBM 驱动的 systolic PE array、并行 adder tree、special function unit，以及专门面向 speculative drafting 的 branch-management 逻辑。这里有两个设计细节尤其关键。第一，多条 speculative branch 会共享 prefix，所以处理器会按能够提升权重与激活复用的方式把分支映射到多个 core 上。第二，PE microarchitecture 提供 branch-specific weight buffer，并在 DSP 上做 two-BF16 packing，以提高有效吞吐。draft 侧还维护自己的 KV-cache 管理策略，包括 candidate branch 的临时缓冲、被拒绝路径的剪枝，以及已接受 token 的连续分配。

最后一块是流水控制。DFVG 通过 shared host memory、ping-pong buffer 与 interrupt-driven 的异步 PCIe 协调，把 FPGA 和 GPU 接成一个紧耦合流水线。GPU 在验证一批候选时，FPGA 已经继续生成下一批；如果 verification 提前结束，GPU 可以直接从已接受前缀继续 forward；如果发生 rejection，FPGA 则根据返回的 prefix length 做 rollback 并继续生成。论文特别强调，跨设备传输的是紧凑的 token 元数据，而不是重量级模型状态，这也是为什么它测到的通信开销没有进入关键路径。

## 实验评估

实现上，论文把 draft model 放在 V80 FPGA 上，把 verifier 放在 RTX 4090 或 A100 GPU 上，并在 Vicuna-7B、LLaMA-7B、OPT-13B、Qwen3-8B 及其同家族小模型 draft 上做实验。数据集覆盖 MT-Bench、translation、summarization、QA、math reasoning 与 RAG。基线也算比较完整：autoregressive decoding、经典 speculative sampling、DuoDecoding、SpecInfer，以及 vLLM、LLaMA.cpp、GPT-Fast 这类优化过的推理框架。

headline result 是，相比 autoregressive baseline，DFVG 端到端加速达到 `2.44x-3.26x`，能效提升达到 `4.33x-5.79x`，其中最好的速度结果出现在 Qwen3-8B。论文还报告，在已接受 draft 长度跨迭代波动很大的情况下，token acceptance rate 仍能稳定在 `75%-85%`，这为 dynamic drafting 相比 fixed-length 策略的优势提供了支撑。作者进一步指出，纯软件的 kernel 与 memory 优化大约在 `1.5x` 左右开始见顶，而 DFVG 之所以还能继续提升，是因为它改变了硬件映射与阶段重叠方式，而不只是减少单个 kernel 的开销。

我觉得最有说服力的是 ablation，因为它把收益拆得很清楚。仅靠 hardware-aware branching 就有 `2.21x`；再加上 TreeSort-Verify 提升到 `2.46x`；引入 FPGA multi-core accelerator 后到 `3.08x`；最后通过 pipeline overlap 到达 `3.26x`。通信开销只占 `1.08%-3.2%`，而 verifier 在 PCIe Gen4 x16 下依然是 compute-bound。资源利用率部分也支撑了实现故事：在 V80 上，设计吃掉了大部分 LUT/FF 预算，矩阵乘相关算子的执行效率达到 `86.2%-97.5%`。整体来看，这组实验最有力地证明了“异构 draft/verify 划分能够击败 GPU-only speculative decoding 的单模型推理场景”；至于多租户 serving、超大 batch 或按部署成本归一化的比较，论文覆盖得就少一些。

## 创新性与影响

相较 _Miao et al. (ASPLOS '24)_，DFVG 保留了 tree-based speculation 的大方向，但加入了 hardware-aware 的分支预算和明确的 FPGA/GPU 阶段划分，而不是继续依赖 multi-GPU 执行。相较 _Li et al. (ASPLOS '24)_，它的贡献不是把整个 speculative pipeline 搬到 PIM 一类新硬件上，而是把小模型和大模型分别映射到更匹配各自瓶颈的处理器类别上。相较纯软件 speculative 方法，论文把瓶颈重新定义成 branching policy、verifier layout 和 device overlap 的协同设计问题。

因此，这篇论文最可能影响两类读者：一类是做 LLM inference acceleration 的系统研究者，另一类是关心 FPGA 在现代 AI serving 栈里还扮演什么角色的架构研究者。即便 DFVG 本身未必就是最终生产方案，它也清楚说明了一点：speculative decoding 的性能上限，不只取决于更聪明的草稿策略，还取决于系统是否把每个阶段放到了合适的硬件上。

## 局限性

DFVG 依赖定制 FPGA 硬件、Verilog overlay 设计，以及一套明显比 GPU-only serving 更重的运行时与编译链路，部署门槛并不低。它的 dynamic tree builder 把 draft model 的 confidence 当作 verification probability 的近似，而当 draft 与 target 的差异比实验中的同家族模型更大时，这个近似可能失真。实验也不是完整的成本等价比较：论文把异构 FPGA+GPU 系统和多种软件基线作对比，但没有按采购成本、开发复杂度或集群级调度影响来归一化。最后，论文没有真正处理 multi-model serving、跨请求长生命周期 cache sharing，或分布式扩展，只是在 future work 里点到了这些方向。

## 相关工作

- _Miao et al. (ASPLOS '24)_ — SpecInfer 在 GPU 上做 tree-based speculative inference and verification，而 DFVG 进一步加入自适应分支预算、verification 重排，以及 FPGA/GPU 阶段划分。
- _Li et al. (ASPLOS '24)_ — SpecPIM 用 PIM 架构-数据流协同设计来加速 speculative inference，而 DFVG 则保留 GPU verification，只把 drafting 专门放到 FPGA 上。
- _Fu et al. (ICML '24)_ — Lookahead decoding 通过 masked decoding 去掉独立 draft model，而 DFVG 保留单独 draft model，并围绕它优化整条系统流水线。
- _Li et al. (ICML '24)_ — EAGLE 在 feature level 重新设计 speculative decoding 以降低不确定性，而 DFVG 的重点是硬件放置、动态 branching 与 verifier 执行效率。

## 我的笔记

<!-- 留空；由人工补充 -->
