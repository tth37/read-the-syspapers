---
title: "ICARUS: Criticality and Reuse based Instruction Caching for Datacenter Applications"
oneline: "ICARUS 用分支历史感知的关键性检测和复用感知分桶替换，让会再次用到的关键指令行在 L2 中留得更久。"
authors:
  - "Vedant Kalbande"
  - "Hrishikesh Jedhe Deshmukh"
  - "Alberto Ros"
  - "Biswabandan Panda"
affiliations:
  - "Indian Institute of Technology Bombay, Mumbai, India"
  - "University of Murcia, Murcia, Spain"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790175"
tags:
  - caching
  - hardware
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ICARUS 针对的是 datacenter CPU 前端里一个很具体的瓶颈：即使 decoupled front-end 已经掩盖了大多数 L1I miss，L2 指令 miss 仍然会让 decode 饿死，进而拖空 issue queue。论文认为，之前只看“关键性”的替换策略之所以不够，是因为大多数关键指令行并不会一直关键，而真正值得保的那部分关键行往往还伴随着更长的局部复用距离。ICARUS 因此把“分支历史感知的关键行检测”和“复用感知的淘汰策略”结合起来，相比 TPLRU 平均提速 `5.6%`，而 EMISSARY 为 `2.2%`。

## 问题背景

论文的出发点很现实：datacenter 应用的代码体积还在持续增长，因为一次请求会跨越应用逻辑、内核模块、语言运行时、RPC 栈和网络栈。现代处理器已经通过 decoupled front-end 和 FDIP 隐藏了相当多 L1I miss，因此 L1I 本身不再是唯一主瓶颈。真正麻烦的是下一层：一旦某次指令 fetch 在 L2 miss，而 decode queue 又已经见底，issue queue 会被逐步耗空，核心就会因为前端断粮而停住。

最接近的前作 EMISSARY 已经意识到“不是每条指令都同样重要”，所以它会标记那些曾经导致 decode starvation 的 cache line，并尽量把它们留在 L2 里。ICARUS 认为这一步还不够细。平均来看，只有 `3.49%` 的指令 fetch 真正属于 critical fetch，但它们却造成了 `23.18%` 的前端 stall，因此识别精度非常关键。与此同时，真正能在后续访问里持续保持关键性的 critical line 只有 `28.32%`；也就是说，如果采用类似“只要关键过一次，以后都算关键”的 PC 粒度策略，就会同时浪费容量、又保不住真正重要的行。

## 核心洞察

这篇论文最重要的观点是：指令 cache 的关键性不是某条指令行的静态属性，而是与执行路径强相关。相同的 instruction line，在一条控制流路径上可能完全无害，在另一条路径上却会因为更长的局部复用距离而在 L2 被淘汰，最终引发 decode starvation。因此，branch history 不是只能服务 branch predictor，它也可以成为预测“这次访问到底会不会出问题”的紧凑上下文。

接着论文提出第二个判断：仅仅识别关键性还不够，替换策略还必须知道这条行接下来是否会被复用、以及复用发生得早还是晚。最值得保护的不是所有 critical line，而是那些“已经被证明重要、但第一次有价值复用还没发生”的 critical line。因为一旦这类行被过早淘汰，系统失去的不是一个普通 miss，而是把未来一次 decode-starving miss 转成 L2 hit 的机会。换句话说，L2 空间应该优先花在“可能真的影响前端”且“后续确实会回来”的那一小部分行上。

## 设计

ICARUS 由两个部分组成。第一部分是 BHC，也就是 branch-history-based criticality detector。处理器维护一个 Critical Instruction Table（CIT），规模为 `512` 项，每项是 `2` 位饱和计数器，同时再维护一个 `9` 位的 branch history register。每当一次来自 L2、L3 或 DRAM 的 instruction fetch 导致 decode starvation 且 issue queue 为空时，系统就把该 cache line 地址与最近分支历史一起哈希，给对应计数器加一；当计数器超过阈值二时，就把这次 fetch 视为 critical，并向 L2 发送 criticality signal。为了避免过时模式永久残留，CIT 每一百万周期清空一次重新学习。

这样做的价值在于，branch history 让签名比“只看 PC”精细得多。论文分析显示，仅用 PC 时，大约 `24%` 的签名会表现出混杂的 decode-starvation 行为；把 branch history 加进来后，这个模糊区间下降到 `5.5%`。也因此，基于 PC 的 EMISSARY 风格策略相对 TPLRU 只能把 decode-starvation cycles 降低 `2.5%`，而带有 BHC 的版本可以做到 `6.5%`。

第二部分是 BRC，也就是基于分桶的替换策略。它为每条 L2 line 额外维护两位元数据：criticality bit 和 reuse bit。于是所有行被分为四类：非关键且尚未复用 `[0,0]`、非关键但已复用 `[0,1]`、关键且已复用 `[1,1]`、关键但尚未复用 `[1,0]`。淘汰顺序按“价值最低到最高”推进，也就是先从 `[0,0]` 开始，再到 `[0,1]`、`[1,1]`，最后才轮到 `[1,0]`，同时分别受 `2`、`4`、`6`、`4` 这组 watermark 约束。reuse bit 会在第一次 hit 后置位，因此 ICARUS 能区分“还在等待第一次有价值复用”的关键行和“已经证明自己会被反复使用”的行。数据行只会落在两个 non-critical bin 中，所以这并不是无条件牺牲数据来偏袒指令，而是在共享 L2 中做更细粒度的权衡。

## 实验评估

实验基于 gem5 full-system simulation 与 FDIP，在 `12` 个 datacenter workload 上进行，包括 `tpcc`、`wikipedia`、`finagle-http`、`kafka`、`tomcat`、`web-search` 和 `verilator`，默认硬件模型接近 Granite Rapids：`64KB` L1I、`2MB` 私有 L2。相对 TPLRU，EMISSARY 的平均运行时间提升为 `2.2%`，完整 ICARUS 为 `5.6%`，在 `verilator` 上最高达到 `51%`。论文还报告，ICARUS 将平均 L2 instruction MPKI 从 `4.72` 降到 `1.94`，并把归一化后的 decode-starvation cycles per instruction 从 `0.97` 压到 `0.86`。

最能支撑中心论点的，其实是按复用距离拆开的分析。BHC 负责把 critical line 识别得更准，但真正让论文成立的是 BRC：它明显降低了那些 mid-reuse 和 long-reuse 的 critical instruction line 的 miss，而这正是作者一开始指出 EMISSARY 处理不好的部分。像 `kafka` 这样的 workload，其 long-reuse instruction MPKI 可以从 `0.8` 降到 `0.02`。论文也做了比较完整的敏感性分析：无论是 L1I 大小、L2 大小、BTB 大小，还是 Granite Rapids、EPYC 9005、AmpereOne 风格的层次结构，ICARUS 都持续优于 EMISSARY。再加上与 PDIP 和 IP-stride prefetcher 的组合实验，双 prefetcher 都开启时 ICARUS 的平均提速达到 `7.7%`。

这些证据最有说服力的场景，是论文明确瞄准的那一类：代码 footprint 很大、front-end stall 仍主要由 L1I 之下的 instruction miss 驱动、且每核拥有共享私有 L2 的 datacenter 应用。对于代码早已装进 L2，或者主要瓶颈变成 instruction translation 的情形，论文给出的证据就没有这么直接了。

## 创新性与影响

和 _Nagendra et al. (ISCA '23)_ 相比，ICARUS 的创新点不是“更努力地保护 critical line”，而是提出 criticality 本身必须做路径敏感建模，同时替换策略还要区分“第一次复用尚未来临”的关键行和“已经复用过”的关键行。和 Ripple 这类 profile-guided 方案相比，它把整个方法保持在在线、硬件可管理的范围内，而不是依赖离线分析与二进制改写。因此这篇论文更像一篇真正的机制论文：它同时引入了新的元数据路径、新的检测器以及新的淘汰准则，并把它们都绑定到一个具体的前端瓶颈上。

这类工作最可能影响的是做 server CPU 前端优化和 datacenter workload 分析的架构师。即使未来实现细节不再沿用同样的 hash、计数器或 watermark，这篇论文传递出的更广义结论大概率会留下来：面向 datacenter 软件栈的 instruction-cache replacement，不能只靠“指令优先”或者“关键过一次就一直关键”，而需要把上下文和复用一起纳入决策。

## 局限性

ICARUS 依赖若干手工设计并调过参数的部件：CIT 大小、branch history 长度、reset interval、各个 bin 的 watermark，甚至在 `verilator` 配小 L2 时还额外引入了“costly fetch”阈值。论文虽然做了敏感性实验，但整体上它仍比 TPLRU 或简单 RRIP 风格策略更依赖参数设定。这会自然带来一个问题：换到论文未覆盖的微架构和软件混合负载上，是否还需要重新整定。

另一个限制来自评估方式。论文所有结果都来自 simulation，而且只覆盖 `12` 个应用在各自 region of interest 内的表现。主要收益集中在 instruction-side miss，而 instruction translation、多核干扰，以及与其他前端结构的联动，大多只被作者描述为“正交”而非系统性联合评估。最后，像 `verilator` 这种高 critical-fetch 比例 workload 还需要额外定义“高代价 critical fetch”，这也说明基础策略在极端负载下可能仍需要 workload-aware 的自适应。

## 相关工作

- _Nagendra et al. (ISCA '23)_ — EMISSARY 是最接近的 L2 instruction-cache policy，但它把关键性看得过于静态，也没有区分长复用关键行与短复用关键行。
- _Khan et al. (ISCA '21)_ — Ripple 通过离线 profile 和二进制改写管理 L1I，而 ICARUS 是在线硬件策略，目标是共享 L2 中的 instruction caching。
- _Ajorpaz et al. (ISCA '18)_ — GHRP 用 PC 和 history 预测 L1I 与 BTB 中的 dead block；ICARUS 则用 branch history 预测哪些 L2 指令行会引发 decode starvation。
- _Godala et al. (ASPLOS '24)_ — PDIP 是与 ICARUS 互补的 instruction prefetcher：ICARUS 负责让关键行在 L2 留得更久，PDIP 负责把紧急行更早拉进 L1I。

## 我的笔记

<!-- empty; left for the human reader -->
