---
title: "LAER-MoE: Load-Adaptive Expert Re-layout for Efficient Mixture-of-Experts Training"
oneline: "LAER-MoE 把每个 expert 全量切分到所有 GPU，并把重布局藏进 FSDP 通信里，使 MoE 训练能按迭代重排热点 expert 而不显式迁移参数。"
authors:
  - "Xinyi Liu"
  - "Yujie Wang"
  - "Fangcheng Fu"
  - "Xuefeng Xiao"
  - "Huixia Li"
  - "Jiashi Li"
  - "Bin Cui"
affiliations:
  - "School of Computer Science & Beijing Key Laboratory of Software and Hardware Cooperative Artificial Intelligence Systems, Peking University, Beijing, China"
  - "School of Artificial Intelligence, Shanghai Jiao Tong University, Shanghai, China"
  - "Bytedance Seed, Beijing, China"
  - "Bytedance Seed, Shenzhen, China"
  - "Institute of Computational Social Science, Peking University (Qingdao)"
conference: asplos-2026
category: llm-training
doi_url: "https://doi.org/10.1145/3779212.3790180"
code_url: "https://github.com/PKUDAIR/Hetu-Galvatron/tree/laer-moe"
tags:
  - llm-training
  - gpu
  - scheduling
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

LAER-MoE 的核心判断是，之前很多系统级 MoE 负载均衡方案之所以反应不够快，症结不在于看不到 routing skew，而在于重布局 expert 的代价太高。它提出 `FSEP`，把每个 expert 预先切分到所有设备上，只在需要时重构本设备要算的那些 experts，并把 expert re-layout 融合进 FSDP 风格的参数预取与梯度 reshard。再配合一个把“快速 token 路由”和“较慢 replica 摆放”分开的 planner，系统在不改变训练语义的前提下，相比 Megatron 报告了最高 `1.69x` 的加速。

## 问题背景

这篇论文关注的是 MoE 训练里一个非常具体、也非常顽固的瓶颈：routing 分布会在训练过程中持续变化，而且往往极不均衡，导致少数热点 experts 拖慢整个 iteration。作者在 Mixtral `8x7B` 的训练轨迹里观察到，几乎每一轮都会出现过载 expert；当这种 skew 出现时，All-to-All 在总时间中的占比会从不到 `10%` 上升到超过 `40%`。也就是说，系统并不是被平均算力限制住，而是被最慢那几个 device 的尾延迟限制住。

只靠算法层面补救并不理想。给 router 加 auxiliary loss 确实能让负载更平均，但论文也展示了这会拖慢收敛，要用更多 step 才能达到同样的模型质量。转向系统层面后，现有方案也有硬约束。像 FasterMoE、Prophet 这样的复制式方案，会为复制出来的 experts 引入额外梯度同步；像 SmartMoE 这样的迁移式方案，则需要显式搬运 expert 参数和 optimizer state。论文指出，单次 relocation 的通信量通常可达到 expert 参数规模的约 `6x`，还会因为 send/receive buffer 同时存在而抬高峰值内存。于是，现有系统不得不降低重布局频率，或者在 planner 里惩罚过于激进的调整，这恰好和“routing skew 每轮都在变”的需求相冲突。

## 核心洞察

论文最关键的洞察是：如果系统不再把 expert 看成“完整地住在某一张卡上的对象”，而是把每个 expert 一开始就切分到所有设备上，那么 expert re-layout 的成本结构会根本改变。每张 GPU 都持有每个 expert 的一个 shard 之后，所谓“移动 expert”就不再是搬一整份参数和优化器状态，而只是决定下一轮每台机器要重构哪些完整 experts。

这个重述之所以重要，是因为它把原本不规则、代价高、容易失衡的重布局流量，变成了规则且均衡的 All-to-All 参数重构。这样一来，planner 就可以按 iteration 粒度积极调整 expert placement，而不必先担心 relocation 自己是否比收益更贵。LAER-MoE 进一步把控制逻辑拆成两个时间尺度：一条是快速的 token routing 规则，立刻把 token 发往就近 replica；另一条是较慢的 layout tuner，利用近期 routing 历史来决定每个 expert 该有多少 replicas、这些 replicas 下一轮放在哪里。

## 设计

`FSEP` 是整篇论文最核心的机制。对于 `N` 个 devices、`E` 个 experts，每个 device 存每个 expert 的 `1/N`，并且一次最多重构 `C` 个完整 experts。围绕这一点，系统在 FSDP 式训练流程上增加了三个操作。`shard` 在初始化时把所有 expert 参数展平并切分；`unshard` 在 forward 或 backward 前通过 All-to-All 只恢复当前 device 需要的 experts；`reshard` 则在 backward 之后把 expert 梯度重新切分。因为每个 device 始终只物化 `C` 个 experts，`FSEP` 的内存行为仍然接近 fully sharded training，但运行时已经能在每一轮自由选择不同的 expert layout。

论文的工程重点在于让这种自由不会变成新瓶颈。作者把展平后的 expert 存储与用于恢复参数形状的 metadata 分离开来，从而兼容 PyTorch autograd 对参数视图的要求。随后又重新安排通信时序：下一层 MoE 的 expert prefetch 不再只和前一层 attention overlap，而是尽量和当前层的 expert compute 重叠；prefetch 会排在 token All-to-All 之后发起，以减少链路争用；梯度同步则被延后到下一层 backward 期间。按论文的分析，`FSEP` 的通信量只比 `FSDP+EP` 略高，并且随着规模增大越来越接近，文中给出的代表性比例约为 `1.1x`。额外内存成本也主要来自这些重叠优化所需的参数与梯度缓冲，而不是 `FSEP` 本身不可避免的结构性负担。

在 `FSEP` 之上，LAER-MoE 叠加了一个 planner。完整目标是同时最小化通信时间和最大单设备计算时间，并满足 expert capacity 与 token-to-expert routing 约束。由于直接求解太慢，作者把它拆开处理。同步执行的 token dispatcher 使用 lite routing：若某个 expert 在本节点内有 replica，就把 token 在节点内 replicas 之间平均分；否则再在全局 replicas 之间平均分。异步执行的 expert layout tuner 则负责决定 replica 数量和摆放位置。它会同时尝试按负载比例分配 replicas 与平均分配 replicas 两种方案，再做随机扰动，并用 cost model 选最优。placement 本身是 topology-aware 的贪心算法：先尽量把同一 expert 的 replicas 分散到不同 nodes，再把它们放到当前总负载最小的可用 devices 上。

## 实验评估

实验规模足以支撑论文的主张。作者在 `4` 个节点、共 `32` 张 `A100-80GB` GPU 上评估，节点内是 `300 GB/s` 的 NVLink，节点间是 `800 Gbps` 的 InfiniBand。模型包括 Mixtral-`8x7B`、Mixtral-`8x22B` 和 Qwen-`8x7B`，每个模型都测试了 `e8k2` 与 `e16k4` 两种配置，数据集使用 WikiText 与 C4，训练采用 dropless routing。基线包括 Megatron、做过并行策略调优的 `FSDP+EP`，以及作者复现的 FlexMoE 风格 planner。

在这些设置下，LAER-MoE 相比 Megatron 的最高加速为 `1.69x`，相对 `FSDP+EP` 的最高加速为 `1.50x`，相对 FlexMoE 的最高加速为 `1.39x`，后者平均也有 `1.20x` 提升。case study 解释了收益来自哪里：在负载失衡的运行里，`FSDP+EP` 的 All-to-All 占总时间可高达 `40%`，FlexMoE 能降一点，而 LAER-MoE 能把这部分压到 `20%` 以下，相对基线带来最高 `2.68x` 的 All-to-All 加速。最大 token count 的可视化也和这个故事一致，尤其在更难的 `e16k4` 配置上，LAER-MoE 基本能把每层的每设备负载拉回到接近理想均衡线。

收敛实验同样关键。使用 `1e-4` auxiliary loss 时，LAER-MoE 与 Megatron 的相对误差保持在 `< 1e-3`，这支持了论文的论点：`FSEP` 改变的是通信与布局方式，而不是训练语义本身。因为它可以在较小 auxiliary loss 下仍保持高吞吐，所以 wall-clock 收敛速度反而优于需要更大 balancing loss 的 Megatron。planner 的额外开销在目标场景里几乎可以忽略：lite routing 约 `25-31 ms`，不到总时间的 `0.1%`；CPU 端 layout solver 在论文的扩展分析里也始终低于每层基线时间。我对实验的主要保留意见是范围：真正的端到端实验只做到 `32` 张 A100，更大规模的结论主要来自理论分析和模拟，而不是完整实测。

## 创新性与影响

相对 _He et al. (PPoPP '22)_ 和 _Wang et al. (CLUSTER '23)_，这篇论文的新意不只是“再发明一个复制热点 expert 的策略”，而是提出了一个新的底座，让 replication 与 relocation 的成本足够低，低到可以持续进行。相对 _Zhai et al. (USENIX ATC '23)_ 和 _Nie et al. (Proc. ACM Manag. Data '23)_，它最有辨识度的一点是拒绝把 re-layout 当成一个单独且昂贵的 phase。也正因为如此，它才能做到按 iteration 调整，而不是每几百步才改一次，或者只在 planner 估计“这次迁移值得”时才动。

因此，这篇论文更像是在为分布式 MoE training stack 提供一个新的系统构件，而不只是提出另一条负载均衡启发式规则。作者还明确指出 `FSEP` 与 Comet、Lancet、Lina、DeepEP 等通信/计算重叠优化是正交的。如果这种可组合性在更多真实系统里成立，LAER-MoE 的影响面会超过论文当前展示的这套实现。

## 局限性

论文也很坦率：LAER-MoE 最擅长的是负载不均衡场景。若 routing 本来就很平衡，它的表现应当和 `FSDP+EP` 接近，因为两者通信量本来就相差不大。换句话说，它的收益高度依赖 expert skew 是否足够频繁、足够严重，能够真正主导 step time。

另外还有部署层面的限制。它关于 overlap 的论证依赖 micro-batch 里有足够多的 tokens，才能把 prefetch 藏在 expert compute 后面；论文给出了阈值分析，并说明自己的实验满足这一条件，但更小 batch 下效果可能变弱。`32` GPU 以上的大规模可扩展性主要还是理论分析与模拟。再加上 FlexMoE 没有公开实现，相关对比基于作者自己的复现，而不是直接对着官方代码跑。这些问题不会推翻结果，但会限制我们把结论外推到所有集群与所有工作负载。

## 相关工作

- _He et al. (PPoPP '22)_ — FasterMoE 通过复制热点 expert 来分流，而 LAER-MoE 选择把所有 expert 统一切分，再把布局变化转化为均衡的参数重构通信。
- _Zhai et al. (USENIX ATC '23)_ — SmartMoE 能在线迁移 expert，但 relocation 仍是一个显式且昂贵的阶段；LAER-MoE 的关键改进是把这部分代价藏进常规 sharding 通信里。
- _Wang et al. (CLUSTER '23)_ — Prophet 选择性复制热点 expert，但必须顾虑复制后带来的偏斜同步开销；LAER-MoE 的目标是把 planner 从“先算迁移值不值”转向“主要为了均衡而优化”。
- _Nie et al. (Proc. ACM Manag. Data '23)_ — FlexMoE 同时考虑 replication 与 relocation，但搜索空间仍受 re-layout 成本约束；LAER-MoE 通过改变底层并行范式，扩大了可行布局空间。

## 我的笔记

<!-- 留空；由人工补充 -->
