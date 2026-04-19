---
title: "Optimizing Task Scheduling in Cloud VMs with Accurate vCPU Abstraction"
oneline: "vSched 在 guest 内部探测 vCPU 的容量、活跃度和拓扑，再把 CFS 从慢、叠放或即将沉睡的 vCPU 上引开，不改 hypervisor 也能把调度做对。"
authors:
  - "Edward Guo"
  - "Weiwei Jia"
  - "Xiaoning Ding"
  - "Jianchen Shan"
affiliations:
  - "Hofstra University"
  - "The University of Rhode Island"
  - "New Jersey Institute of Technology"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3696092"
code_url: "https://github.com/vSched"
tags:
  - scheduling
  - virtualization
  - kernel
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文的出发点很直接：云上 VM 里的 Linux 一直在拿一份错误的 CPU 抽象做调度。guest 看到的是静态、对称的 vCPU，可真实世界里的 vCPU 会掉速、会被 host 抢走、也会在不同拓扑之间变化。vSched 用 guest 内部的轻量探测把这些特征补回来，再给 CFS 加上三条策略，最终做到 p95 延迟平均下降 42%、欠载超卖场景下吞吐最高提升 82%，而在默认抽象本来就正确的环境里平均额外开销只有 0.7%。

## 问题背景

论文抓住的是一个长期被低估的事实：vCPU 根本不是普通 core。任务明明已经 runnable，却可能因为 host 抢占了对应 vCPU 而完全不前进；一个 idle vCPU 看起来像是理想目标，实际却可能容量很低；guest 里看到的拓扑也可能已经过时，甚至一开始就是错的。Linux 现有很多 capacity-aware 和 topology-aware 启发式都默认这些信息可信，于是放到 VM 里就会把任务放错位置。

更麻烦的是，连 work conservation 在 VM 里都可能反着来。把任务塞到一个极弱的 idle vCPU 上，会制造 straggler；把任务塞到和别的 busy vCPU 叠放的 idle vCPU 上，又会诱发 priority inversion 一类双重调度问题。XPV、CPS、UFO 这类方案都依赖 hypervisor 协同，这在多云和公有云环境里并不现实。论文要回答的是：如果 hypervisor 不改，guest 自己能不能把足够准确的 vCPU 真相探出来，再据此把调度做好？

## 核心洞察

作者的核心判断是，guest 不需要知道 hypervisor 的一切，只要补齐最影响调度决策的三件事：当前 vCPU 实际有多强、它多久能再次真正运行任务、以及它和其他 vCPU 的有效拓扑关系。只要这三项信息足够准，Linux 就能继续沿用大部分 CFS 逻辑，只在默认抽象明显失真的地方补少量虚拟化感知策略。

## 设计

vSched 分成 `vProbers` 和三条策略。`vcap` 用 steal time 加周期性高优先级采样估计动态容量，再用 EMA 平滑；`vact` 用 heartbeat 和 steal-time jump 推断 vCPU 是否 active，并估计平均 inactive period；`vtop` 用 cache-line transfer latency 区分 SMT、同 socket、跨 socket 和 stacking 关系。

这些信号再喂给 `bvs`、`ivh` 和 `rwc`。`bvs` 把小而延迟敏感的任务引向高容量、低延迟、且马上能真正运行的 vCPU。`ivh` 会把 CPU-bound running task 主动从快要 inactive 的 vCPU 上搬走，关键在于先唤醒目标、等两边都 active 再完成迁移，这样迁移延迟才不会把收益吃光。`rwc` 则故意把有害的 idle vCPU 藏起来，重点是 straggler 和 stacked vCPU。原型基于 Linux 6.1 CFS，用 kernel module 和 BPF hook 实现，总计 1612 行代码。

## 实验评估

实验组织得比较扎实：先证明探测真的准，再证明现有 Linux 优化在正确 vCPU 抽象下会变好，最后才看新策略的整机收益。`vtop` 的速度已经足够在线使用，在资源受限 VM 上完整探测要 547 ms、在高性能 VM 上要 665 ms。

这些探测信号不是摆设。容量不对称时，`vcap` 能把 Sysbench 落在高容量 vCPU 上的执行占比从 44% 提高到 81%，吞吐提升 32%；即便容量对称，也能把错误迁移减少 74%，吞吐仍有 4% 提升。拿到正确 SMT 和 socket 信息之后，Linux 在一个欠载测试里能把活跃 core 数从 11-12 个提升到 15-16 个；在混合负载下 Matmul 吞吐最高提升 18%；在 Dedup、Nginx、Hackbench 上平均吞吐提升 26%，IPI 最多减少 99%。

真正体现论文个性的，是 activity-aware 两条策略。`bvs` 让 Tailbench 的 p95 延迟平均下降 42%；以 Masstree 为例，没有 best-effort 干扰时 queue time 从 32.73 ms 降到 9.92 ms，有 best-effort 时也能从 20.66 ms 降到 15.47 ms。`ivh` 在欠载但超卖的 VM 里把吞吐最多拉高 82%，线程数到 16 时平均仍有 17% 提升。端到端看，完整的 vSched 在资源受限 VM 上平均把吞吐提高 69%、把延迟改善到 1.6x；在高性能 VM 上平均把吞吐提高 18%、把延迟改善到 2.3x。若默认 vCPU 抽象本来就准确，平均性能退化只有 0.7%。需要保留一点距离感的是，实验主要建立在 KVM、pinning 和受控干扰之上，离真实公有云仍隔着一层。

## 创新性与影响

这篇论文最有价值的地方，不是又造了一个 hypervisor-side 机制，而是重新划了边界。它把 guest-side scheduling 先看成探测问题，再看成策略问题。和 XPV、CPS 相比，它绕开了 paravirtualization；和 UFO 相比，它关注的是租户拿到现有 vCPU 之后，VM 内部还能做什么。这既给虚拟化调度失真提供了一个清晰的分析框架，也给不能指望云厂商配合的 guest kernel 一个务实方案。

## 局限性

最大的问题还是可部署性。vSched 需要修改 guest kernel，包括 CFS 周边逻辑、插桩、module 和 BPF hook，所以它不是 stock guest 或商业 OS 能直接拿来用的功能。它还是采样式设计，响应尺度是秒级，不是 hypervisor 事件级，因此亚秒级变化更适合 XPV、CPS 这类 host-guest 协同方案。

实验范围也有限。结果主要建立在 x86 Linux over KVM 上，且有些依赖用户态自旋同步的 workload 在拓扑被纠正后会因跨 socket 不平衡更明显而略有退化。再加上 vSched 控制不了 host 侧 vCPU 调度，所以它能缓解很多问题，但不能替代真正的 hypervisor 修复。

## 相关工作

- _Bui et al. (EuroSys '19)_ - XPV 由 hypervisor 向 guest 暴露 NUMA 变化，而 vSched 试图在 guest 内部把足够有用的拓扑与容量信息自己探出来。
- _Liu et al. (ASPLOS '23)_ - CPS 协同暴露 cache 拓扑和 core load；vSched 追求的是类似的调度收益，但把 hypervisor 修改从部署路径里拿掉。
- _Panwar et al. (ASPLOS '21)_ - vMitosis 在 VM 内探测 NUMA 局部性以优化 page-table 访问，vSched 则把这种探测思路扩展到调度相关的 SMT、stacking 和 socket 关系。
- _Peng et al. (NSDI '24)_ - UFO 在 hypervisor 层做面向 QoS 的 core management，而 vSched 假设 VM 只能接受现有 vCPU 供给，并在 guest 内把这些 vCPU 用得更对。

## 我的笔记

<!-- 留空；由人工补充 -->
