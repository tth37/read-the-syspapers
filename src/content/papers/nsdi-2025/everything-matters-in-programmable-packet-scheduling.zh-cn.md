---
title: "Everything Matters in Programmable Packet Scheduling"
oneline: "PACKS 用基于 quantile 的 admission control 和感知 queue occupancy 的 queue mapping，让可编程交换机同时逼近 PIFO 的排序与丢包行为。"
authors:
  - "Albert Gran Alcoz"
  - "Balázs Vass"
  - "Pooria Namyar"
  - "Behnaz Arzani"
  - "Gábor Rétvári"
  - "Laurent Vanbever"
affiliations:
  - "ETH Zürich"
  - "BME-TMIT"
  - "USC"
  - "Microsoft Research"
conference: nsdi-2025
code_url: "https://github.com/nsg-ethz/packs"
tags:
  - networking
  - scheduling
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`PACKS` 是一个运行在可编程交换机上的 P4 调度器，目标是同时逼近 `PIFO` 的两部分行为：保留有限缓冲里最该保留的包，并让这些包尽量按 rank 顺序发出。它通过 sliding-window rank 估计、quantile-based admission control 和 occupancy-aware queue mapping 来做到这一点。

## 问题背景

`PIFO` 的吸引力在于，它把调度策略拆成两步：先给包打 rank，再让交换机按 rank 发包。但真正的 `PIFO` 需要在线速完成 push-in insertion，还要在更高优先级包后来到达时做 rank-aware eviction，而现有 programmable switch ASIC 并不提供这种能力。已有近似方案通常只解决一半问题。`SP-PIFO` 这类方法通过 strict-priority queues 改善输出顺序，但丢包只是副作用，所以低优先级包仍可能占据本该留给高优先级包的缓冲空间。`AIFO` 在单个 FIFO 上做 rank-aware admission，更接近正确的 keep/drop 决策，却没法继续按 rank 排序。对于同时关心时延和丢包的 datacenter workload，这两种折中都会扭曲原本想表达的调度策略。

## 核心洞察

这篇论文的核心判断是：交换机不一定非要有真正的 push-in 硬件，只要它能估计“接下来更可能到来的 rank”，就能在入队前近似做出有限容量 `PIFO` 的关键决策。`PACKS` 从最近到达包的 sliding window 中计算 rank quantile，再结合剩余缓冲推导出 `rdrop`，把高于容量预算的包直接丢掉；随后再设置 queue bounds，让映射到每个 priority queue 的 rank 质量与该队列容量匹配。

这里最重要的点是，queue bounds 不能只追求减少 rank inversion，还要避免 collateral drops，也就是“全局上本该被接纳的包，最后却因为某个具体队列溢出而被二次丢弃”。`PACKS` 正是通过同时优化 admission 和 per-queue fit，才比单纯优化排序更接近 `PIFO`。

## 设计

`PACKS` 运行在一组 strict-priority FIFO queues 之上。每个包到达时，它先更新最近 rank 的 sliding window `W`，再读取当前 buffer occupancy，最后按从高到低优先级扫描队列。admission 是 quantile-based 的：只有当 `W.quantile(r)` 低于当前空闲缓冲比例时，包才有资格被接纳，并可通过参数 `k` 给 burstiness 留余量。mapping 也是 quantile-based 的：当该包的 quantile 能落入队列 `1..i` 的累计空闲空间时，它就可以进入第 `i` 个队列。

如果更高优先级队列已经满了，包会继续尝试更低优先级队列，而不是立刻被丢弃。这一点避免了 `SP-PIFO` 在 burst 场景下常见的过度丢包。实现上，作者用 439 行 P4 在 Intel Tofino 2 上完成了 `PACKS`，总共使用 12 个 pipeline stages、一个 16-entry sliding window，以及一个把 egress occupancy 回传到 ingress 的 ghost thread。

## 实验评估

实验分成 simulator、端到端 workload 和真实硬件三部分。在 Netbench 中，作者比较 `PACKS`、理想 `PIFO`、`SP-PIFO`、`AIFO` 和 FIFO 在多种 rank 分布下的表现。uniform 场景里，`PACKS` 相比 `SP-PIFO`、`AIFO`、FIFO 分别减少超过 `3x`、`10x`、`12x` 的 inversion，同时把丢包更集中在高 rank 区间：`PACKS` 大约从 rank 79 才开始丢包，AIFO 是 77，而 `SP-PIFO` 低到 20 就开始丢。Poisson 和 inverse-exponential 分布下，`PACKS` 相比 `SP-PIFO` 仍能减少大约 `5x-7x` 的 inversion，相比 `AIFO` 和 FIFO 则能减少超过 `14x`。

论文还清楚展示了 window-based 设计的代价。`|W| = 1000` 明显好于 `100`，但即便 `|W| = 15`，`PACKS` 仍比 `SP-PIFO` 少 30% 的 inversion。突发的 distribution shift 会伤害它，尤其负向偏移会导致窗口适应前的过度丢包。在端到端 pFabric-style leaf-spine workload 上，`PACKS` 的 small-flow average FCT 只比理想 `PIFO` 高 `5%-9%`，但比 `SP-PIFO` 好 `11%-33%`，比 `AIFO` 好 `2.25x-2.6x`。fair-queuing 实验里，它也稳定优于 FIFO、AIFO 和 AFQ。最后，作者在真实 Tofino2 上验证了 `PACKS` 能按预期把带宽分配给最高优先级流，并保持 line rate。

## 创新性与影响

这篇论文的新意不在于新的 rank function，而在于给“如何在现有 programmable switch 上近似完整 `PIFO` 行为”提供了一个可部署方案。`SP-PIFO` 逼近了 ordering，`AIFO` 逼近了 admission；`PACKS` 则把两者统一到同一个由 rank quantile 和 queue occupancy 驱动的 enqueue algorithm 里。因此，它既可以被看作 pFabric、fair queuing 这类策略的更好底座，也可以被看作未来 programmable scheduler 的设计模板。

## 局限性

`PACKS` 最依赖的前提是：最近观测到的 rank 足够代表不久之后的未来。大的非平稳分布变化会污染窗口，使 admission 暂时变得过于宽松或过于保守；论文把这个问题讲得很清楚，但部署时仍然要面对。实现层面，它还依赖 ghost thread 这类 switch-specific 机制，默认只用了 16-packet window，规模扩大时可能需要用较粗粒度的 buffer occupancy 近似。此外，硬件实验也比 simulator 范围窄，只验证了 Tofino2 上的 bandwidth allocation，没有覆盖完整应用 trace。

## 相关工作

- _Sivaraman et al. (SIGCOMM '16)_ - `PIFO` 定义了理想的 programmable scheduling 抽象，而 `PACKS` 的目标是在商品 programmable switch 上逼近这种理想行为。
- _Gran Alcoz et al. (NSDI '20)_ - `SP-PIFO` 通过动态 strict-priority bounds 逼近 `PIFO` 的排序，而 `PACKS` 进一步加入显式 admission control 与感知 occupancy 的 fallback，确保留下来的包也更接近 `PIFO` 的选择。
- _Yu et al. (SIGCOMM '21)_ - `AIFO` 在单个 FIFO 上逼近 `PIFO` 的 admission 行为，但无法继续对已接纳包排序；`PACKS` 则把类似的 rank-aware admission 与 multi-queue ordering 结合起来。
- _Gao et al. (NSDI '24)_ - `Sifter` 通过新的硬件结构追求 inversion-free programmable scheduling，而 `PACKS` 的重点则是立刻部署到现有 data plane 上。

## 我的笔记

<!-- empty; left for the human reader -->
