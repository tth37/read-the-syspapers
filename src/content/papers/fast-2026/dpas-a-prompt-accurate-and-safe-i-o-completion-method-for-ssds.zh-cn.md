---
title: "DPAS: A Prompt, Accurate and Safe I/O Completion Method for SSDs"
oneline: "DPAS 用最近两次 I/O 的欠睡/过睡结果逐次校正休眠时长，并在 CPU 争用或 timer failure 出现时切换 classic polling、PAS 与 interrupts。"
authors:
  - "Dongjoo Seo"
  - "Jihyeon Jung"
  - "Yeohwan Yoon"
  - "Ping-Xiang Chen"
  - "Yongsoo Joo"
  - "Sung-Soo Lim"
  - "Nikil Dutt"
affiliations:
  - "University of California, Irvine"
  - "Kookmin University"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/DongDongJu/DPAS_FAST26"
tags:
  - storage
  - kernel
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`PAS` 不再依赖按 epoch 聚合的统计值来猜休眠时长，而是只根据最近两次休眠是欠睡还是过睡来逐个 I/O 调整睡眠。`DPAS` 再按核在 classic polling、PAS 和 interrupts 之间切换，因此既能在 CPU 空闲时获得快速完成路径，也能在争用下避免 hybrid polling 失控。

## 问题背景

NVMe SSD 已经快到让 interrupts 的固定开销重新显形。只要设备延迟降到几微秒量级，context switch、cache 污染以及 CPU power state 转换都会直接出现在应用可见延迟里。classic polling 能绕开这些成本，但代价是独占 CPU；一旦前台线程、后台工作或别的系统任务同时抢核，它就会迅速变得不可接受。

hybrid polling 本该是折中：先睡一段，再在接近完成点时醒来轮询。论文指出，现有方案失败的原因是它们用 epoch 级统计值估计 sleep。Linux Hybrid Polling 用上一 epoch 的平均延迟一半，`HyPI` 靠离线设定 attenuation，`EHP` 用更短 epoch 的最小延迟。它们都对延迟突变反应太慢，也都把 OS 导致的晚醒和设备真实变慢混在一起看。于是 CPU contention 一来，系统就会把 oversleep 错当成 SSD 变慢，继续把后续 sleep 拉长，也就是论文所说的 "latency shelving"。

## 核心洞察

这篇论文最关键的主张是，hybrid polling 不需要复杂的绝对延迟预测器，它需要更快的控制反馈。只要知道最近两次 sleep 的结果是 undersleep 还是 oversleep，就足以逐个 I/O 地追踪 SSD 延迟的下包络线。这个二元反馈会在每个 I/O 完成后立刻出现，因此控制器不必等下一个 epoch 才能收敛。

但更准的 hybrid polling 也不等于万能。timer 自身的开销仍可能让 `PAS` 在稳定低延迟场景下不如纯 polling；而一旦 CPU 争用过重，scheduler 晚唤醒线程，`PAS` 会把请求的 sleep duration 一路压到零，退化成 timer-failure 忙等循环。论文因此给出的第二个洞察是：polling、PAS 和 interrupts 应该被看成互补模式，并根据争用信号在运行时切换。

## 设计

`PAS` 继承了 Linux Hybrid Polling 的 bucket 划分方式，按读写方向和 I/O 大小维护状态。每个 bucket 保存最近两次休眠结果、当前 sleep duration，以及一个 adjustment factor。初始化时，状态是 `(OVER, UNDER)`，sleep duration 是 `0.1 us`。之后控制规则完全由最近两次结果驱动：`(UNDER, UNDER)` 就把 adjustment 增加 `UP`，`(OVER, OVER)` 就减去 `DN`，两次结果不同则说明控制器刚越过真实延迟边界，于是把 adjustment 拉回 `1` 附近，再做一步反向修正。睡眠通过 `hrtimer` 完成，醒来后由修改过的 poll 函数返回 `UNDER` 或 `OVER`。

为了避免灵敏度写死，作者又给 `PAS` 加了动态灵敏度控制。如果最近两次结果相同，说明追踪太迟钝，就把 `UP` 和 `DN` 同时乘以 `(1 + HEATUP)`；如果两次结果不同，说明可能调得太激进，就乘以 `(1 - COOLDN)`。设计里固定 `UP:DN = 1:10`，并把 `UP` 限制在 `[0.001, 0.01]`，实验统一使用 `(HEATUP, COOLDN) = (0.05, 0.1)`。

并发 I/O 又带来两类问题。首先，按设备共享一套 `PAS` 状态会让不同 CPU 的结果互相覆盖，还需要锁来避免竞态，所以论文把状态改成 per-core。其次，即使在 per-core 模式下，同一核上的多个线程也可能共用同一个 sleep duration。为此，只有“使用该 duration 的第一条完成 I/O”可以上报 sleep result，且只有“看见新 result 之后发出的第一条 I/O”可以真正更新 duration，其余请求只复用已更新的值。

`DPAS` 再加一个四状态机：classic polling、PAS-normal、PAS-overloaded 和 interrupts。在 PAS-normal 中，系统先发 `NPAS = 100` 个 I/O 观察平均 queue depth；如果深度是 `1`，就切到 classic polling，持续 `NCP = 1000` 个 I/O 后再回来。若 `PAS` 观测到 timer failure，也就是请求的 sleep duration 已塌到零，则进入 PAS-overloaded，重新观察 queue depth；当深度超过阈值 `theta` 时，就切到 interrupts，持续 `NINT = 10000` 个 I/O 后再回来判断下一步。论文将 `theta` 设为 NAND SSD 的 `1`、3D XPoint 的 `3`。

## 实验评估

实验平台是 Linux `5.18`、`20` 核 Xeon Gold `6230` 和三类 SSD：Intel Optane P5800X（`3D XPoint`）、Samsung 983 ZET（`Z-NAND`）以及 SK hynix P41（`TLC NAND`）。评测既有 `FIO` 微基准，也有 `Baleen`、`Systor'17`、`Slacker` 的 trace replay，以及 `RocksDB` 上的 `YCSB` 宏基准。

`PAS` 最直接的收益是省 CPU。对 `4 KB` random read，论文报告它相比 Linux Hybrid Polling 平均少用 `21` 个百分点的 CPU，同时保留 polling 路径的低延迟优势。另一方面，classic polling 在理想条件下的吞吐上限仍更高，例如在 Optane 上最多可比 interrupts 高 `30%` 的 read IOPS，这也是 `DPAS` 仍保留它作为一个模式的原因。

更关键的是鲁棒性。在同时存在 CPU contention 和脉冲式后台 I/O 的情况下，`DPAS` 相比 interrupts 的 `YCSB` 平均吞吐提升分别达到 Optane 上 `9%`、ZSSD 上 `7%`、P41 上 `5%`。`PAS` 单独使用时也有帮助，但在高线程数下仍可能被 timer failure 拖到不如 interrupts；`DPAS` 的价值就在于能及时逃离这种坏状态。trace 分析也支持这一点：`LHP` 和 `EHP` 在延迟尖峰结束后仍沿着陈旧 epoch 统计继续 oversleep，而 `PAS` 和 `DPAS` 会立刻收缩 sleep duration。论文还展示了盲目依赖 polling 的风险：在 ZSSD 上，classic polling 到 `90th` percentile 都接近 interrupts，但 `99.99th` 与最大延迟会分别膨胀到 `17x` 和 `30x`。

## 创新性与影响

相对 `LHP`、`HyPI`、`EHP` 这一串工作，这篇论文的新意不在于再换一个 attenuation 或 epoch 长度，而在于把控制信号从“统计出来的延迟值”改成“逐个 I/O 的睡眠结果”。相对那些把 polling 和 interrupts 分开比较的工作，`DPAS` 的价值则在于把多种完成机制放进同一个运行时决策器里。

因此，这篇论文最可能影响的是 Linux block layer、NVMe completion path 和 ultra-low-latency storage 研究。它把 scheduler contention 从存储路径外部的噪声，变成了 completion design 的一部分。

## 局限性

这套方案仍然紧紧绑定在 Linux NVMe 内核路径上。实现位于 multi-queue block layer，需要修改 kernel poll 路径，并且假设每个 CPU 同时拥有 polled queue 和 interrupt queue。当 CPU 数远多于设备队列数时，queue sharing 会拉低性能。论文也还没有把 interrupt coalescing 集成进来，因此 `DPAS` 一旦退回 interrupt mode，在极端高并发下仍可能遇到 interrupt storm。

评测覆盖了三类本地 SSD，但更宽泛的外推仍然有限。随着 I/O size 变大，收益会明显收缩；在 P41 的 `128 KB` read 上，`DPAS` 甚至比 interrupts 低约 `1%`。论文也没有考察 `io_uring`、SPDK、网络存储，或那些愿意用一点 IOPS 换更多 CPU 余量的 QoS 场景。最后，`theta` 虽然只按介质类型粗粒度设置，已经比较稳健，但仍不是完全自动推导出来的。

## 相关工作

- _Lee et al. (JSA '22)_ - `EHP` 用更短 epoch 的最小延迟替代平均值，但仍然受 epoch 边界约束，也无法区分 oversleep 与设备真实变慢。
- _Song and Eom (IMCOM '19)_ - `HyPI` 依赖离线 profiling 为不同系统挑 attenuation，而 `PAS` 直接从逐个 I/O 的睡眠结果在线学习。
- _Hao et al. (OSDI '20)_ - `LinnOS` 用神经网络预测 flash I/O 是快还是慢，但它并不给 hybrid polling 所需的精确唤醒时间。
- _Yang et al. (FAST '12)_ - "When Poll is Better Than Interrupt" 讨论了存储 I/O 中 polling 与 interrupts 的基本取舍，而 `DPAS` 把这种静态取舍变成了争用条件下的运行时模式选择。

## 我的笔记

<!-- 留空；由人工补充 -->
