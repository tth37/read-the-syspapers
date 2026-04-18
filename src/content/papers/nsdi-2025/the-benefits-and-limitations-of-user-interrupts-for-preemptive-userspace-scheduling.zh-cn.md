---
title: "The Benefits and Limitations of User Interrupts for Preemptive Userspace Scheduling"
oneline: "本文测量 user interrupts 作为用户态抢占原语的收益与边界：它把 signal 开销从 2.4 us 降到 0.4 us，但只有能利用细粒度调度的 runtime 才真正受益。"
authors:
  - "Linsong Guo"
  - "Danial Zuberi"
  - "Tal Garfinkel"
  - "Amy Ousterhout"
affiliations:
  - "UC San Diego"
conference: nsdi-2025
category: memory-serverless-and-storage
code_url: "https://github.com/LinsongGuo/aspen.git"
tags:
  - scheduling
  - datacenter
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文通过 Aspen-KB 和 Aspen-Go 两个实现来评估 Intel user interrupts 是否真适合用户态抢占。结论是：它把基础抢占开销从 signal 的 `2.4 us` 降到 `0.4 us`，在量子高于大约 `10 us` 时通常优于 compiler instrumentation，但只有当 runtime 真能利用细粒度抢占时，它才会带来明显的尾延迟收益。

## 问题背景

数据中心 workload 常把亚微秒级短任务和数百微秒长任务混在一起，短请求因此容易被长请求挡住，尾延迟迅速升高。内核调度器的抢占粒度太粗，不适合亚毫秒延迟；而用户态 runtime 往往干脆回避抢占，因为现有机制都不理想。signal 太贵，每次抢占都要跨两次内核边界；compiler instrumentation 虽然绕开了内核，但开销强依赖控制流，而且非常依赖调参。论文的问题因此是：user interrupts 能否把高频用户态抢占变成一件既便宜又可预测的事。

## 核心洞察

核心洞察是，user interrupts 只是把异步抢占做得更便宜、更稳定，并不会自动把调度问题一起解决。runtime 仍要跳过无意义的抢占、正确处理 non-preemptible code、保存寄存器状态、及时发现新工作，并让新到达的任务优先于已被抢占过的旧任务。也正因为如此，同一个硬件原语在 kernel-bypass runtime 里收益很大，在 Go 里却只剩有限改进。

## 设计

作者先在 24 个 benchmark 上直接比较 signals、compiler instrumentation 和 user interrupts。user interrupts 需要先向内核完成一次注册，之后中断发送与接收都在用户态完成，因此不再需要每次抢占都经过内核。

随后，作者实现了两个调度器。Aspen-KB 基于 Caladan 扩展而来，加入 timer core、user interrupt 递送，以及三种抢占机制的统一支持。它会通过共享内存查看 RX queue 和调度时间戳，只有当线程已跑满 quantum 且确实还有别的工作可做时才抢占。每个核还维护 new queue 和 preempted queue 两个队列，让新到达工作优先。对于 non-preemptible code，作者保留软件 deferral，因为 `clui`/`stui` 在 `malloc` 等高频区域代价过高；context switch 时则保守地保存通用寄存器与 AVX-512 寄存器。Aspen-Go 的改动更少：让 `sysmon` busy-spin、改用 user interrupts、增加网络 polling，但保留 Go 原本的 local/global queue 结构和对 OS network stack 的依赖。

## 实验评估

机制层面的结果很直接：signals 每次抢占大约要 `2.4 us`，user interrupts 只要 `0.4 us`。如果 slowdown 预算是 `10%`，signals 只能支持大约 `30 us` 的 quantum，而 user interrupts 还能压到 `5 us`。compiler instrumentation 在低于 `10 us` 的极小量子下有时会更便宜，但结果非常依赖 probe placement。

在 Aspen-KB 上，这种机制优势能转化为调度收益。对 `95%` GET、`5%` SCAN 的 RocksDB，user interrupts 在把 GET tail latency 控制在 `50 us` 内的同时，把 GET throughput 提升 `58.2%`；最优 quantum 是 `5 us`，而 signals 要到 `15 us`。fine-tuned Concord 可以接近，但默认配置很脆弱：一次 SCAN 会触发超过 `95,000` 次检查，在 `5 us` quantum 下造成 `31.2%` slowdown，调优后才降到 `2.3%`。在 DataFrame 上，任务跨度从 `5 us` 到 `250 us`，最优 quantum 变成 `20 us`；此时 user interrupts 让短任务吞吐比 non-preemptive 高约 `30%`，也比 fine-tuned Concord 高 `9%`，因为后者在 tight loop 上仍要付出 `3.3 us` 的额外代价，而 user interrupts 只增加 `0.37-0.32 us`。

Aspen-Go 则展示了它的边界。在 BadgerDB 上，Aspen-Go UINTR 在 `1000 us` 的 GET 尾延迟目标下，相比原始 Go 只把 GET throughput 提高 `17.5%`，而 compiler instrumentation 版本还要再高 `6%`。作者将原因归结为 Go 的结构：packet 可能滞留在内核网络栈里，新 goroutine 可能排到 global queue 后面，`sysmon` 看不到是否真有 packet 在等，落在 unsafe point 的抢占还会被丢弃。timer scalability 也说明同一件事：在 `5 us` quantum 下，一个 timer core 配合 user interrupts 能支撑 `22` 个 application core，compiler instrumentation 能支撑 `24` 个，而 signals 只能支撑 `2` 个。

## 创新性与影响

这篇论文的新意不只是“把 user interrupts 用到调度里”，而是解释它在什么条件下才真正有价值。作者把三种抢占机制同时放进一个低延迟 kernel-bypass runtime 和一个主流语言 runtime 中比较，最后给出一个非常实用的判断：当 quantum 大致在 `10 us` 或以上、且 runtime 能把新工作尽快提到前面时，user interrupts 往往是更好的默认选择；否则，更便宜的中断本身未必能带来对应的系统收益。

## 局限性

这项研究只覆盖两个 runtime，而且都运行在支持 user interrupts 的 Intel 平台上，因此数值结果更适合作为上下界参考，而不是普适常数。对于极小 quantum，compiler instrumentation 仍可能更优。与此同时，user interrupts 也没有消除 context switch、unsafe point、thread-local state 和 extended registers 带来的工程复杂度。它解决的是调度链路中的一个瓶颈，而不是整个问题。

## 相关工作

- _Kaffes et al. (NSDI '19)_ - `Shinjuku` 同样面向微秒级尾延迟的抢占式调度，但这篇论文更关注 Intel user interrupts 相对 signals 和 compiler instrumentation 作为底层原语时的取舍。
- _Iyer et al. (SOSP '23)_ - `Concord` 代表了基于 compiler instrumentation 的微秒级调度路线，而本文明确展示了这种方法在哪些场景仍有竞争力、在哪些场景会变得脆弱且依赖调参。
- _Li et al. (HPCA '24)_ - `LibPreemptible` 也使用硬件辅助的用户态抢占，而 Aspen-KB 更强调跳过无意义抢占和按核维护的双队列调度，以更好地控制 head-of-line blocking。
- _Fried et al. (NSDI '24)_ - `Junction` 在 kernel-bypass 的云系统里使用 user interrupts，而本文把重点放在机制本身的取舍，并进一步检验这些收益在 Go 这种主流 runtime 中还能保留多少。

## 我的笔记

<!-- 留空；由人工补充 -->
