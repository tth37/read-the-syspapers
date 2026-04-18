---
title: "Performance Predictability in Heterogeneous Memory"
oneline: "Camp 用一次 DRAM profiling 预测 CXL 与 DRAM-CXL 加权交织下的 slowdown，把需求读、预取失时和 store-buffer 背压拆开建模。"
authors:
  - "Jinshu Liu"
  - "Hanchen Xu"
  - "Daniel S. Berger"
  - "Marcos K. Aguilera"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech, Blacksburg, USA"
  - "Microsoft and University of Washington, Redmond, USA"
  - "NVIDIA, Santa Clara, USA"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790201"
code_url: "https://github.com/MoatLab/CAMP"
tags:
  - memory
  - disaggregation
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Camp 的核心主张是：异构内存上的性能退化可以在部署前预测，而不必等到 workload 跑上 CXL 之后再做归因。它从一次 DRAM profiling 中提取会被 CXL 放大的微架构压力点，再把这些信号组合成纯 CXL slowdown 预测和 DRAM/CXL 加权交织曲线。

## 问题背景

这篇论文抓住的是 CXL / tiered memory 里一个非常实际的规划问题。运维者真正想知道的，不是某个 page 是否“热”，也不是程序在迁移后已经慢了多少，而是：如果把 workload 的部分甚至全部 footprint 放到更慢的内存层，它到底会慢多少，而且这个判断能不能在部署前做出来。这个问题之所以重要，是因为异构内存同时带来更便宜的容量和更高的访问延迟，一旦把延迟敏感的数据放错地方，后果可能是 pipeline stall、DRAM 带宽浪费，甚至 SLO 违约。

现有指标并不能直接回答这个问题。MPKI 只能说明程序经常碰内存，却不能说明它是否有能力隐藏 latency；平均延迟和带宽描述的是 memory system 的状态，却没有告诉我们 CPU pipeline 会怎样把这些变化变成真实执行时间损失；stall counter 更接近性能本体，但依旧大多是 reactive 的，而且把几种不同的 slowdown 机制混在一起。作者此前的 Melody 虽然能把 slowdown 拆成几个组成部分，但它仍然需要 DRAM 和 CXL 两次执行。Camp 想补上的，就是这一步部署前预测能力。

## 核心洞察

论文最重要的洞察是，CXL slowdown 并不是某种“设备很慢所以程序就慢”的黑箱属性，而是 CPU 侧几个明确的微架构压力点在更高 latency 下被放大的结果。Camp，也就是 Causal Analytical Memory Prediction，把这些压力点当成真正有因果意义的预测特征。

作者把 slowdown 拆成三个可加的来源：demand-read stall、cache/prefetch inefficiency，以及 store-induced backpressure。需求读 slowdown 取决于 baseline latency 与 memory-level parallelism 的关系，因为只有 MLP 无法掩盖掉的那部分 latency 才会转化为额外 stall。cache slowdown 体现在 workload 对 line fill buffer 和来自 memory 的 prefetch 的依赖上；当 latency 升高时，prefetch 会变得不及时。store slowdown 则来自 store buffer 的接近饱和状态，因为更慢的 read-for-ownership 会拖慢 draining。只要把这三部分分别建模，Camp 就能同时预测“全放到 CXL 会怎样”和“按某个 DRAM/CXL 比例交织会怎样”。

## 设计

Camp 的外形其实很克制，但推导相当细。它先在 DRAM 上做一次 profiling，最多读取 12 个 PMU counter。对非带宽瓶颈 workload，这一次 DRAM run 就够了；对带宽瓶颈 workload，Camp 再补一个 CXL endpoint run，用来合成完整的加权交织性能曲线。

需求读 slowdown 的模型从 memory-active cycles 和 Little's Law 出发。作者观察到，同一个 workload 在 DRAM 和 CXL 上的 request 数量大致稳定，所以关键不在请求总数，而在 latency 的增长与 MLP 的增长谁更快。最后得到的是一个关于 baseline `L/MLP` 的双曲函数：如果 workload 原本就很难隐藏暴露出来的 latency，那么到了 CXL 上就会被放大得更厉害。cache 模型则关注 prefetch 的时效性：更高 latency 会让填充进入 L1/L2 的过程变慢，使更多数据停留在 LFB 这样的 transient structure 中，所以 Camp 用 workload 对 LFB hit 的依赖程度，以及这些填充来自 memory prefetch 的比例，来估计 cache-induced slowdown。store 模型更直接：如果 workload 在 DRAM 上就已经有不少 cycle 被“满的 store buffer”卡住，那么 CXL 上更长的 RFO latency 就会近似线性地放大这种阻塞。

至于 interleaving，论文最关键的化简是假设 MLP 在不同 DRAM/CXL 比例下变化不大。这样一来，ratio knob 的本质就变成了 latency curve 问题。Camp 把每个 tier 的 latency 建模成“空载基线 + 二次型 contention 项”，再把两端点测得的 stall component 按比例缩放，拼成任意 weighted-interleaving ratio 下的 closed-form slowdown 曲线。这个模型既能支撑 "Best-shot" 预先选比例，也能支撑 Camp-guided colocation。

## 实验评估

对论文设定的目标范围来说，这组实验是很扎实的。作者一共评估了 265 个 workload，覆盖 SPEC CPU 2017、PARSEC、GAPBS、PBBS、Redis、Spark、VoltDB、MLPerf、GPT-2、DLRM 和 Llama 风格推理。硬件方面用了三代 Intel 处理器、一个 NUMA 慢层，以及三种 ASIC CXL 2.0 expander，延迟范围是 214-271 ns，带宽范围是 22-52 GB/s。

预测精度是最醒目的结果。Camp 在 NUMA 上达到 0.97 Pearson correlation，在三种 CXL 设备上达到 0.91-0.96。视设备不同，有 77.8-92.4% 的 workload 绝对误差在 5% 以内，90.7-97.3% 在 10% 以内。更关键的是，各组成部分也能分别预测得准：demand-read、cache、store 三项都能单独对上，而不是靠误差互相抵消。

真正体现系统价值的是 use-case 实验。对 interleaving，Best-shot 在八个 bandwidth-bound workload 上击败了 Caption、NBT、Colloid、Alto、Soar、first-touch 和 Linux 默认的 1:1 interleave，最高可提升 21%。对 colocated scheduling，Camp-guided placement 相对 MPKI-guided placement 最多提升 12%，相对常规 placement 选择最多提升 23%。我觉得这部分很有说服力，因为它比较的正是实践里最容易先想到的几类策略，而不是弱基线。当然边界也很清楚：interleaving 模型目前只覆盖 weighted interleaving，而且 bandwidth-bound 情况仍需要第二个 endpoint run。

## 创新性与影响

相对于 _Liu et al. (ASPLOS '25)_，Camp 的创新在于把 Melody 的事后分解推进成部署前预测：Melody 解释 slowdown 从哪里来，而 Camp 试图在真正迁移前就估计它会有多大。相对于 _Liu et al. (OSDI '25)_，Camp 比 SoarAlto 的 AOL 式 demand-read 视角更完整，因为它同时把 prefetch 失时导致的 cache stall 和 store-buffer backpressure 纳入模型。相对于 _Vuppalapati and Agarwal (SOSP '24)_，它也明确反对把 latency equalization 当作最终目标，而是直接去预测端到端 slowdown。

因此，这篇论文最可能影响两类读者：一类是做 CXL / tiered memory runtime 与资源管理的系统研究者，另一类是需要制定 placement policy 的工程团队。它贡献的不是一个新设备，也不是一个新内核子系统，而是一个可解释、硬件约束感很强的预测模型。

## 局限性

Camp 依赖平台相关的 calibration，其中一些常数要靠 microbenchmark 拟合出来，而不是完全无条件可移植。论文也承认，设备 tail latency 仍会制造 outlier，尤其是在噪声更大的 CXL expander 上；对极高并发的 workload，平均 MLP 的假设也可能失真，从而带来过估。

它的适用范围也没有标题看起来那么宽。纯 CXL predictor 主要针对“带宽尚未饱和”的区间，而 interleaving 模型只覆盖 weighted interleaving，不直接处理 first-touch 或 migration-driven policy。作者把动态 page placement 与更丰富的 cross-tier interference 留给了未来工作。

## 相关工作

- _Liu et al. (ASPLOS '25)_ — Melody 给出了 Camp 所继承的 slowdown 分解框架，但它需要同时运行 DRAM 与 CXL，因此本质上是 attribution 工具，而不是 predictor。
- _Liu et al. (OSDI '25)_ — SoarAlto 用 AOL 风格的 reactive 信号做 tiering；Camp 则给出因果化的 `L/MLP` 模型，并把范围扩展到 cache 与 store 效应。
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid 试图让不同 tier 的 latency 接近；Camp 认为如果最终没有减少 stall cycle，这样的 latency equalization 仍可能是错误目标。
- _Sun et al. (MICRO '23)_ — Caption 帮助社区理解真实 CXL 系统并探索较粗粒度的 interleaving 选择，而 Camp 补上了能解析地挑选 ratio 的预测模型。

## 我的笔记

<!-- 留空；由人工补充 -->
