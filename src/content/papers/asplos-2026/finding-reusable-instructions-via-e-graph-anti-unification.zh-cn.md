---
title: "Finding Reusable Instructions via E-Graph Anti-Unification"
oneline: "用 e-graph anti-unification 从领域程序中找出可复用、可向量化的 custom instructions，并用硬件感知成本模型挑选最优集合。"
authors:
  - "Youwei Xiao"
  - "Chenyun Yin"
  - "Yitian Sun"
  - "Yuyang Zou"
  - "Yun Liang"
affiliations:
  - "School of Integrated Circuits, Peking University, Beijing, China"
  - "Peking University, Beijing, China"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790162"
code_url: "https://github.com/pku-liang/ISAMORE"
tags:
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ISAMORE 把 custom instruction 发现问题改写成“在语义等价的 e-graph 中寻找可复用模式”的问题，而不是继续围着语法上相似的热点代码打转。它先把 LLVM IR 编码成结构化 DSL，再用分阶段 equality saturation 加 anti-unification 找共同模式，最后用基于 profiling 的硬件成本模型挑选指令集合。论文在基准上给出最高 `2.69x` 的整体加速，库级与硬件案例也说明这条路线不只适用于小玩具程序。

## 问题背景

这篇论文要解决的是 ASIP 和 RISC-V specialization 里一个很实际的瓶颈：大家都知道 custom instructions 很有价值，但“到底该加什么指令”长期仍靠人工经验，而自动化方法大多只是在求一个更容易的问题。细粒度方法在 basic block 里枚举 convex subgraph；粗粒度方法把热点 basic block 或更大代码片段直接合并。它们确实能自动生成加速单元，但优化目标通常是局部热点频率或语法相似性，而不是跨程序、跨工作负载的复用价值。

这件事之所以关键，是因为 custom instruction 不是免费的。它会消耗面积、验证成本和集成精力。一个在单点热点上跑得很快、但全域只出现几次的大指令，未必是好设计。作者用 CImg 做了很直接的例子：语法合并会产生一个很大的专用指令，只能在 8 个位置复用；他们的语义方法平均每条指令可覆盖 93 个位置，同时速度更高、面积更小。已有方法还大多停留在标量层面，因此也看不到那些分散在重复标量表达式里的 data-level parallelism。

那能不能直接把已有的 e-graph anti-unification 套过来？论文认为也不行。真实程序有控制流，不能自然地塞进普通表达式树；equality saturation 会让 e-graph 指数膨胀；对所有 e-class 对做穷举 anti-unification 很快就会失控。所以真正的问题其实有两层：一是如何把一般程序编码成适合 e-graph 推理的形式，二是如何让“语义模式挖掘”在真实代码规模上还能跑得完。

## 核心洞察

论文最重要的主张是，只要程序表示能同时保留数据流和足够多的控制流语义，可复用的 custom instructions 就可以被看成“语义等价 e-class 之间 anti-unification 得到的模式”。在 equality saturation 暴露出等价改写之后，anti-unification 会把这些等价项概括成更一般的模板，而“模式至少出现两次”这件事又天然把复用性写进了搜索目标里，而不是在事后再去检查。

这个洞察成立的原因是，anti-unification 能穿透表面的语法差异。像 `a*2 + b*2` 和 `(1+i)<<1` 这样的表达式，对语法合并来说完全不同，但在改写之后可能收敛到同一个结构模式。论文进一步把这个想法推广到并行性上：如果相似的标量实例在同一个 basic block 中重复出现，就可以先打包进向量 lane，再继续挖掘向量化模式。换句话说，语义等价负责带来复用性，重复的标量结构负责暴露向量化机会。

## 设计

ISAMORE 的第一步是把 LLVM IR 降到一个结构化 DSL，其中既有算术和访存操作，也显式引入 `If`、`Loop`、`List`、`Get`、`Vec` 和 `App`。这是整篇论文最关键的工程动作，因为它让系统能够把“一般程序”而不只是直线表达式放进 e-graph。这个 DSL 还是强类型的，后面做 anti-unification 时，类型信息会直接参与剪枝。

RII 的主循环是分阶段的。系统不会一次性把所有 rewrite rules 都灌进 equality saturation，而是分多个 phase 小步推进。前面先对整数和浮点规则做完整饱和，后面再对 non-saturating rules 做有限次数的受控应用。前几个 phase 识别出的模式还会被重新作为 rewrite 加回去，因此后续 phase 可以在已有模式之上继续归纳出更大、复用性更强的模式。

可扩展性主要来自 smart AU。第一层剪枝是只配对结果类型一致、且 64 位结构哈希相似的 e-class。第二层剪枝是当某一对 e-node 的 anti-unification 会产生太多候选时，不做穷举保留，而是用 boundary sampling 或 kd-tree sampling，按延迟和面积特征挑代表性模式。也正是这一步，把原本理论上非常容易爆炸的搜索，变成可运行的工程流程。

向量化则作为一个独立但嵌入式的阶段处理。ISAMORE 先找标量 seed，把同一 basic block 中匹配的实例打包成 `Vec` 节点，再通过 lift 和 couple rewrites 扩展出向量结构，最后做 acyclic pruning，避免 `Get -> Vec -> Get` 这类环把混合标量/向量 e-graph 撑爆。之后的硬件感知选择器会结合 profiling 得到的 cycles-per-operation 和 HLS 估计出的硬件延迟与面积，维护 Pareto-optimal 的指令集合，并在最终 extraction 时再做一次更精细的代价回算。

## 实验评估

这篇论文的实验比较扎实，因为它同时检验了“能不能跑完”和“结果值不值得”。在 9 个 kernel 加一个 All 组合基准上，原始 LLMT 在论文设定的 `30GB` 限制下全部爆内存，而带 RII 的 ISAMORE 最多只用了 `145s` 和 `799MB`。这一点很重要，因为论文的贡献不只是“找到了更好的指令”，而是“把 e-graph anti-unification 变成了一个在真实程序上能跑通的方法”。

与基线的比较也比较公平。作者对比了 `ENUM`、`NOVIA` 和一个去掉 EqSat 的 `NoEqSat` 消融版，还专门把 NOVIA 接上了同样的 profiling-driven cost model，并统一了 I/O 约束。结果上，ISAMORE 的最大加速解相对 NOVIA 平均高 `1.52x`，不同基准的提升区间是 `1.12x` 到 `1.94x`。相对 `NoEqSat`，它的最大加速平均还能再高 `1.12x`，同时面积只用到后者的 `84.9%`。这基本支撑了论文的中心论点：语义等价不仅能提升复用率，也确实能换来更好的性能面积权衡。

案例研究是全文最有说服力的部分，说明它并不只适合小 kernel。在 `liquid-dsp` 上，ISAMORE 相对 NOVIA 平均有 `1.39x` 的加速，同时节省 `84.0%` 面积。在单体 CImg 库上，它找出了 8 条很小的指令，平均每条复用 93 次，以仅 `975 um^2` 的面积做到 `1.18x` 加速；相比之下，NOVIA 生成的是一个很大的单元，只有 `1.01x`。在 PCL 模块上，ISAMORE 相对 NOVIA 平均达到 `1.64x`，最高 `2.73x`，面积节省 `93.2%`。硬件案例也不是纸面估算：针对 BitNet 的 `BitLinear`，生成的 RoCC 单元在 RTL 仿真中达到 `2.15x` 加速，面积开销 `4.81%`，频率无下降；针对 CRYSTALS-KYBER，则得到 `5.15x` 加速，但代价是 `17.67%` 面积开销和 `2.58%` 的频率下降。整体看，这组实验对论文主张的支持度是高的。

## 创新性与影响

相对 _Trilla et al. (MICRO '21)_，ISAMORE 的真正新意在于它优化的是“语义复用”而不是“语法合并后的大 basic block”。相对 _VanHattum et al. (ASPLOS '21)_，它不是用 e-graph 把程序映射到既有向量 ISA 上，而是反过来用 e-graph 发明新的可复用指令。相对 _Melchert et al. (ASPLOS '23)_，它的关注点更明确地停留在 ISA extension 层面的指令发现，而不是处理单元级别的设计空间探索。

因此，这篇论文最可能影响的是 RISC-V 扩展、编译器辅助硬件专用化、以及领域专用处理器方向的研究者。它最值得记住的贡献不是某一条具体指令，而是一条把程序等价推理、复用性感知模式挖掘、以及硬件成本估计连成闭环的工作流。

## 局限性

这套系统本质上是高度启发式的，论文也没有回避这一点。phase scheduling、相似度阈值、AU sampling、以及 acyclic pruning 都是在拿完备性换 tractability，因此全局最优模式完全可能被漏掉。向量化路径还依赖 LLVM 先把合适的标量结构暴露出来，论文就明确提到 `2DConv` 因为 bounds check 阻碍了 if-conversion，导致一部分 DLP 没被吃到。

硬件成本模型虽然务实，但毕竟还是近似。选择阶段主要依赖 profiling 加上 `1GHz` 目标下的 HLS 估计，只有最后被选中的解才会做更精细的回算，所以前面若排序出错，后面未必能补回来。部署门槛也不低：论文里最漂亮的结果依赖 RoCC 集成、RTL 仿真和 OpenROAD 物理实现，这意味着它更像一种面向离线处理器专用化的专家工具，而不是可以轻量级即时部署的自动调优器。

## 相关工作

- _Trilla et al. (MICRO '21)_ — NOVIA 通过对热点区域做语法合并来生成 inline accelerator，而 ISAMORE 关注的是跨领域程序的语义等价可复用模式。
- _VanHattum et al. (ASPLOS '21)_ — Diospyros 用 equality saturation 把 DSP kernel 映射到现有向量指令；ISAMORE 则用相近工具链去发现新的 custom instructions。
- _Melchert et al. (ASPLOS '23)_ — APEX 研究的是面向 processing element 的 frequent subgraph 探索，和本文相邻，但不以 semantic anti-unification 驱动 ISA 扩展。
- _Coward et al. (ASPLOS '24)_ — SEER 把 e-graph rewriting 用在 high-level synthesis 内部，而 ISAMORE 更早一步，先决定哪些硬件指令值得被造出来。

## 我的笔记

<!-- 留空；由人工补充 -->
