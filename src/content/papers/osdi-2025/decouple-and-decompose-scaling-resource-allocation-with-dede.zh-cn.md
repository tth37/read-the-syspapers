---
title: "Decouple and Decompose: Scaling Resource Allocation with D E D E"
oneline: "D E D E 复制分配矩阵，用 ADMM 在按资源与按需求的子问题间交替求解，在不依赖 POP 粒度假设的前提下扩展大规模云资源分配。"
authors:
  - "Zhiying Xu"
  - "Minlan Yu"
  - "Francis Y. Yan"
affiliations:
  - "Harvard University"
  - "University of Illinois Urbana-Champaign"
conference: osdi-2025
tags:
  - scheduling
  - networking
  - datacenter
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

D E D E 面向一类常见但难扩展的云资源分配问题：变量同时出现在按资源和按需求定义的约束中。它的关键做法是复制分配矩阵，并用 ADMM 约束两份矩阵保持一致，从而把一次大规模求解拆成许多可以并行执行的 per-resource 与 per-demand 子问题。这样做在 cluster scheduling、traffic engineering 和 load balancing 上都比 POP 给出更好的时间/质量折中，并能更快逼近 exact solver 的分配质量。

## 问题背景

论文针对的是生产系统里一个非常现实的痛点。很多云控制器仍把资源分配建模成 LP 或 MILP，然后交给商业求解器处理；但今天的云环境里，资源种类、需求数量和变量规模已经增长到几千乘几千、甚至数百万变量。对于必须按秒级节奏重算的控制环路来说，几十分钟乃至数小时的求解时间根本不可接受。

此前的加速方案大多牺牲了通用性。一类工作是特定领域定制，例如专门为 WAN traffic engineering 设计的系统。POP 更通用一些，但它要求每个 demand 只需要一小部分、且彼此可互换的资源，才能把问题随机切成几个子问题分别求解。作者认为这个“granular”假设在真实工作负载中并不稳固：GPU 任务可能只能跑在指定硬件上，网络流量也可能被限制在预配置路径内。一旦这个假设不成立，粗暴切分不是分配质量下降，就是根本无法切得足够细，因而并行化收益有限。

论文想抓住的不是某一种 allocator，而是许多 allocator 共享的一种结构：目标函数通常是若干 per-demand 或 per-resource utility 的和，约束也通常分别写在每个 resource 和每个 demand 上。难点在于，每个分配变量同时出现在两类约束里，所以问题虽然“看起来可分”，但在求解器内部仍然高度纠缠。

## 核心洞察

论文最重要的判断是，这种纠缠主要是代数形式上的，而不是问题本身不可分。只要把原始分配矩阵 `x` 复制成一个辅助矩阵 `z`，就可以把 resource 侧的目标与约束全部写在 `x` 上，把 demand 侧的目标与约束全部写在 `z` 上，然后只额外保留一个等式约束 `x = z`。这个重写不会改变最优解，却把问题精确地变成了适合 two-block ADMM 的形式。

一旦进入 ADMM 框架，D E D E 就能交替优化：固定 demand 侧变量时求 resource 侧，固定 resource 侧变量时求 demand 侧。更关键的是，由于论文关注的问题本身具备 separable structure，这两步还能继续拆开：`x` 步拆成若干 per-resource 子问题，`z` 步拆成若干 per-demand 子问题。换句话说，D E D E 的扩展性并不是靠牺牲全局视野来换局部贪心，而是用乘子更新保留全局耦合，同时把真正的数值求解变成大量更小的独立任务。

## 设计

形式上，D E D E 处理的是这样一类问题：目标函数由 `f_i(x_i*)` 这样的 per-resource utility 和 `g_j(x_*j)` 这样的 per-demand utility 组成；每个 resource 都有线性约束 `R_i x_i* = r_i`，每个 demand 都有线性约束 `D_j x_*j = d_j`。框架先把原问题改写成：最小化 `sum_i f_i(x_i*) + sum_j g_j(z_*j)`，其中 resource 约束仍作用在 `x` 上，demand 约束改写到 `z` 上，并新增 `x - z = 0`。

真正关键的是后续求解方式。D E D E 没有像 penalty method 或普通 augmented Lagrangian 那样去联合优化 `x` 和 `z`，而是使用 scaled ADMM。增广拉格朗日里除了目标函数外，还包含三组辅助变量：一组对应 resource constraints，一组对应 demand constraints，另一组对应 `x` 与 `z` 的一致性约束。每轮迭代中，系统先做一次 `x` 最小化，再做一次 `z` 最小化，最后更新乘子。

由于目标和约束本身是 separable 的，`x` 最小化会自然变成 `n` 个彼此独立的 per-resource 子问题，每个子问题只涉及一个资源相关的变量切片；`z` 最小化则变成 `m` 个 per-demand 子问题。这样一来，D E D E 一方面通过 ADMM 的乘子更新维持全局一致性，另一方面又能把真正昂贵的数值优化交给许多更小的 off-the-shelf solver 调用。论文还给出一个粗略复杂度解释：对于线性规划，原始问题近似是 `O((n*m)^2.373)`，分解后变成 `n` 个大约 `O(m^2.373)` 的子问题，前提是 ADMM 在相对稳定的迭代次数内收敛。

实现层面，D E D E 被做成了一个接近 cvxpy 体验的 Python package。用户定义变量矩阵、分别声明 resource constraints 与 demand constraints，然后调用 `solve(num_cpus=...)` 即可。内部实现会先把不等式通过 slack variable 改写成等式，再分别构造 per-resource 和 per-demand 的 cvxpy 子问题，后续迭代只更新参数而不重建问题。并行执行由 Ray 提供，而不是 Python 线程，从而绕开 GIL。在 traffic engineering 里，作者还把 per-demand 子问题按 source 分组，避免真的维护 `|V|^2` 个 demand 级子问题。

## 实验评估

实验覆盖面很广，这也是论文最有说服力的部分。作者在 64 个 CPU core 上，将 D E D E 与 exact solving、POP 以及理想化的顺序仿真版本 `D E D E*` 对比；在不同领域里还额外比较了 Gandiva、Pinning、Teal 和一个 greedy load-balancing heuristic。

在 heterogeneous cluster scheduling 上，D E D E 只需 3 秒就达到 0.94 的 normalized max-min allocation，10 秒达到 0.99；作为对比，exact solver 需要 156 秒，而 POP-16 在 3.1 秒附近只能达到大约 0.90。对于 proportional fairness 这个更难的目标，基于 cvxpy 的 exact baseline 即使运行 5 小时也无法达到最优；D E D E 和 `D E D E*` 都能在 100 秒内超过该 baseline 的 normalized score，而 POP-4 与 POP-16 分别需要 3,053 秒和 682 秒才能接近相似质量。

在 1,739 个节点的 WAN traffic engineering 评测中，D E D E 30 秒即可满足 90.8% 的 demand，60 秒达到 92%。POP-4 最终也能接近这个水平，但平均需要 1,658 秒；POP-64 虽然更快，却明显牺牲了更多质量。在最小化最大链路利用率的变体里，D E D E 10 秒达到 1.67，exact solver 能做到稍好一些的 1.63，但需要 35 秒；Teal 在 GPU 上只要 0.3 秒就能做到 1.74，不过它是为这一领域专门训练的系统，而不是通用优化框架。

Load balancing 是最难的一组实验，因为它既非凸又带整数变量。即便如此，D E D E 在 15 秒内平均只产生 20.1 次 shard movement，优于 POP-4 在 133 秒内的 21.5 次，也和 exact solver 的 20.9 次很接近，而后者平均需要 4,820 秒。微基准进一步解释了这些收益来源：理想化的 `D E D E*` 在 64 核下有 61.7x speedup，真实实现的 D E D E 仍有 18.2x；warm start 很重要；如果改用 naive 的联合优化，penalty method 达到同等 traffic-engineering 质量会比 D E D E 慢 30 倍以上，augmented Lagrangian 也仍慢 3 倍以上。

## 创新性与影响

相对于 _Narayanan et al. (SOSP '21)_ 的 POP，D E D E 不是随机把 allocation graph 切成几块然后假设 workload 足够 granular，而是先做一个数学上等价的重写，让每个子问题仍能接触完整的资源或需求空间。相对于 _Xu et al. (SIGCOMM '23)_ 的 Teal，它放弃了领域特定的学习模型和 GPU 路线，换来一个可以跨 cluster scheduling、traffic engineering 和 load balancing 复用的通用分解框架。相对于生产环境中直接调用商业求解器的传统做法，它的创新不在于新目标函数，而在于把许多 allocator 早已隐含的并行性系统化地暴露出来。

这件事的价值在于，很多系统最终都会为某一个控制环路重新发明一套专用加速技巧。D E D E 证明了：对相当大一类云资源分配问题，可以共享同一种理论基础、同一种建模接口以及同一种 CPU 并行执行方式，而不必每个领域各写一套。

## 局限性

论文也很明确地说明了适用边界。D E D E 最适合的是二维分配矩阵、separable objective，以及写成 per-resource / per-demand 形式的线性约束。如果目标函数依赖多个 allocation 之间的相互作用，或者约束同时跨越多种资源和多类需求，分解粒度就会变差；若模型再引入时间等额外维度，ADMM 也不再是干净的 two-block 形式。

分配质量同样是有条件的。对于凸问题，ADMM 有较强保证；但论文里的 load balancing 是非凸且带整数变量，因此 D E D E 在这部分更多依赖经验有效性，而不是最优性证明。实现上也存在真实系统开销：`D E D E*` 所呈现的理想速度提升，在真实实现里会被 cache contention、进程管理成本和 straggler 拉低。最后，像 Teal 这样的领域专用系统，在自己手工定制的场景里仍然可能拥有更低的绝对延迟。

## 相关工作

- _Narayanan et al. (SOSP '21)_ — POP 同样追求大规模 allocation 的并行化，但它依赖 granular workload 假设，而 D E D E 的设计目标正是摆脱这一路径。
- _Xu et al. (SIGCOMM '23)_ — Teal 用 learned initialization 和 GPU 执行加速 WAN traffic engineering；D E D E 则提供一种也能迁移到 cluster scheduling 和 load balancing 的通用求解器分解方法。
- _Abuzaid et al. (NSDI '21)_ — NCFlow 通过网络拓扑结构来分解 traffic engineering，而 D E D E 针对的是跨领域可复用的 separable optimization pattern。
- _Namyar et al. (NSDI '24)_ — Soroush 为 max-min fair allocation 提供专门的并行算法，而 D E D E 试图覆盖多种目标函数和多个资源分配领域。

## 我的笔记

<!-- 留空；由人工补充 -->
