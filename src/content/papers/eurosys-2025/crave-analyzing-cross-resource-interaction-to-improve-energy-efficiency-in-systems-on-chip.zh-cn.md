---
title: "CRAVE: Analyzing Cross-Resource Interaction to Improve Energy Efficiency in Systems-on-Chip"
oneline: "CRAVE 先离线学习 CPU、GPU 与内存之间的 DVFS 耦合，再用运行时主导资源效用查表联动调频，让移动 SoC 同时拿到更好的性能和能耗。"
authors:
  - "Dipayan Mukherjee"
  - "Sam Hachem"
  - "Jeremy Bao"
  - "Curtis Madsen"
  - "Tian Ma"
  - "Saugata Ghose"
  - "Gul Agha"
affiliations:
  - "Univ. of Illinois Urbana-Champaign"
  - "Sandia National Labs"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717498"
code_url: "https://github.com/dipayan2/CRAVE_Artifact_EuroSys"
tags:
  - energy
  - hardware
  - memory
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CRAVE 的出发点是：移动 SoC 的 DVFS 不能只盯着眼前最忙的那个资源。CPU、GPU 和内存通过统一内存架构彼此牵连，所以某个资源该设多高频率，往往取决于另外两个资源。CRAVE 先把这种平台级耦合离线学出来，再在运行时用主导资源效用挑选联动的 CPU/GPU/内存频率组合，因此能同时改善延迟和能耗。

## 问题背景

今天的移动 SoC 早已给 CPU、GPU 甚至内存暴露了 DVFS 控制接口，但主流 governor 仍然大多按局部信号做决定。Linux 自带 governor 主要看各资源自己的利用率；更进一步的 cooperative governor 往往依赖特定应用的训练数据，或者依赖帧率这类 QoS 反馈。论文认为，这两条路都漏掉了 SoC 设计里最关键的一层：CPU、GPU 与 DRAM 共享同一套内存系统，一个资源调频，可能直接改变另一个资源的性能和功耗。

作者证明，这不是边角效应。仅仅调整 memory frequency，就会显著改变 CPU 与 GPU benchmark 的表现，也会改变它们的功耗。于是如果 governor 只因为 GPU 利用率高就给 GPU 加频，却没看见真正卡住它的是内存带宽，就会把功耗抬上去，却拿不到对应的性能收益。对异构 workload 来说问题更严重，因为执行过程中主导资源会不停切换。

## 核心洞察

这篇论文最重要的判断是，跨资源耦合首先是平台属性，而不只是某个应用的偶然行为。既然如此，governor 就没必要为每个 workload 单独重学一遍，而应该先把平台里 CPU、GPU、内存之间的影响关系离线刻画清楚，再在运行时低成本复用。CRAVE 正是把这两步拆开：离线阶段学习耦合，运行时阶段只做查表与轻量决策。

更关键的是，它把 memory 提升成了一等公民。过去 cooperative policy 通常只在 CPU-dominant 和 GPU-dominant 之间切换，但 CRAVE 证明，在统一内存架构里，memory 往往才是系统级影响最大的那个环节。只要 governor 真正看见这种耦合，就不会去给正在等待的资源盲目加频，而会优先提升那个决定端到端推进速度的限制资源。

## 设计

CRAVE 分成一次性的训练阶段和轻量的运行时阶段。训练时，它穷举形如 `⟨fCPU, fMem, fGPU⟩` 的频率组合，并运行 AnTuTu、PassMark、Mixbench 中的资源专用 microbenchmark，收集每种组合下的性能与功耗。随后它构造 resource-interaction matrix `RI`：矩阵里的每个元素，都是某个资源频率与另一个资源性能之间的 Spearman 相关系数。

在这个基础上，CRAVE 又构造了两个关键对象。第一是 power-performance ratio `PPR`。对每个频率三元组，它用参数 `ν` 控制性能与功耗的权重，然后选出在给定某个资源频率时全系统最优的频率组合，并把结果存进查找表 `πν`。第二是运行时的 utility metric `U_r(t)`。它不再只看原始利用率，也不只看之前工作里的 `cost`，而是把所有资源当前的 `cost` 按照 `RI` 加权求和。效用值最大的资源，就被当成当前时刻的 dominant resource。

运行时流程因此很直接。系统每个 polling interval 读取一次利用率与当前频率，先找出 dominant resource，再用 `ondemand` 或 cost-based policy 给这个主导资源选频率，随后根据它的新频率到 `πν` 里查出其余资源该配什么频率。若某个非主导资源利用率低于 20%，CRAVE 会主动把它降频省电。对 big.LITTLE CPU，论文为了控制状态空间，只在一个时刻管理一个 CPU 域：通常管理 big cores；只有当 big cores 已经处在最低频率且利用率低于 5% 时，才转而管理 little cores。

## 实验评估

实验平台是两块真实开发板：ODROID-XU4 与 NVIDIA Jetson TX2。训练阶段使用 microbenchmark；端到端评估使用 Chai、Rodinia 和 glmark2。对比对象包括默认 Linux governor 组合、Co-Cap，以及 GearDVFS。论文把运行时 polling interval 设为 250 ms。

先看机制是否成立。论文学出的 `RI` 矩阵显示，在两个平台上 memory frequency 都对其他资源表现出最强的跨资源影响。`PPR` 分布也说明，高效频率区间里经常需要较积极的 memory setting；不过最优点会随平台变化，因为 XU4 的 LPDDR3 和 TX2 的 LPDDR4 在功耗占比上差别很大，后者在高频时甚至可占到总系统功耗的约 30%。

端到端结果也确实支撑论文论点。在 Jetson TX2 的单个 workload 上，CRAVE 相比默认 governor 平均带来 20% 的性能提升，同时降低 16% 的能耗；相对 Co-Cap 和 GearDVFS，它分别带来 16% 和 17% 的性能提升，同时再节省 10% 和 6% 的能耗。对 ODROID-XU4 的 heterogeneous workloads，CRAVE 相比默认 governor 平均提升 19% 性能、降低 24% 能耗。并发 workload 下结果仍然成立：在 TX2 上，它相对默认 governor 基本维持性能不变，但可节省 17% 能耗；在 XU4 上，则平均提升 21% 性能并降低 10% 能耗。

这些实验对中心论点的支撑是够扎实的。负载真正覆盖了 CPU、GPU 与 memory 协作的场景，对比对象也既有默认 governor，也有之前的 cooperative governor。不过它的外推范围仍有限：两块开发板和几组 benchmark 足以证明机制成立，却还不足以说明在所有商用手机 SoC 上都能稳定复现同样幅度的收益。

## 创新性与影响

如果拿 Co-Cap 对比，CRAVE 的创新不只是多加了一个 heuristic，而是把 memory 正式纳入 dominant-resource 识别和联动调频的核心路径。若和 GearDVFS 这类 workload-trained policy 相比，它把学习对象从应用轨迹换成了平台级的 cross-resource behavior，这更适合开放环境里的新应用与并发混部。所以这篇工作的贡献兼具新的问题 framing 和新的机制设计，也因此会吸引做移动平台电源管理、固件策略和 OS governor 的研究者与工程师。

## 局限性

CRAVE 的代价首先在训练阶段。论文报告说，ODROID-XU4 上穷举 980 个配置花了 12 小时，Jetson TX2 上 1716 个配置花了 15 小时。随着 DVFS 域继续增加，这个成本会按组合数上升，所以若想覆盖更多加速器或更细粒度的 CPU 域，后续大概率得靠采样与插值，而不是继续全量扫描。运行时策略本身也是 reactive 的，而不是 predictive 的；实现上它也做了不少简化，例如同一时刻只管理一个 CPU 域。最后，论文主要用 benchmark 评估，并没有在真实移动应用的交互式 QoS 目标下验证。

## 相关工作

- _Deng et al. (MICRO '12)_ - CoScale 协调的是服务器里的 CPU 与 memory DVFS，而 CRAVE 面向移动 SoC，并把 GPU 及平台级跨资源建模一并纳入。
- _Hsieh et al. (ESTIMedia '15)_ - MemCop 也联动 CPU、GPU 与 memory，但目标是 mobile gaming；CRAVE 强调的是 application-agnostic 的 governor 设计。
- _Park et al. (SAC '16)_ - Co-Cap 用 dominant-resource 分类来做 CPU-GPU 频率协同；CRAVE 进一步证明 memory 也可能是主导资源，并把它放进决策核心。
- _Lin et al. (MobiCom '23)_ - GearDVFS 依赖 workload trace 训练多资源 DVFS 模型，而 CRAVE 把学习重点转向硬件耦合本身，因而更适合新的 workload 组合。

## 我的笔记

<!-- 留空；由人工补充 -->
