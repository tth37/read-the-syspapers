---
title: "Tai Chi: A General High-Efficiency Scheduling Framework for SmartNICs in Hyperscale Clouds"
oneline: "Tai Chi 把 SmartNIC 数据面的空闲周期变成可抢占 vCPU，让控制面借力提速，同时维持数据面 SLO。"
authors:
  - "Bang Di"
  - "Yun Xu"
  - "Kaijie Guo"
  - "Yibin Shen"
  - "Yu Li"
  - "Sanchuan Cheng"
  - "Hao Zheng"
  - "Fudong Qiu"
  - "Xiaokang Hu"
  - "Naixuan Guan"
  - "Dongdong Huang"
  - "Jinhu Li"
  - "Yi Wang"
  - "Yifang Yang"
  - "Jintao Li"
  - "Hang Yang"
  - "Chen Liang"
  - "Yilong Lv"
  - "Zikang Chen"
  - "Zhenwei Lu"
  - "Xiaohan Ma"
  - "Jiesheng Wu"
affiliations:
  - "Alibaba Group"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764851"
tags:
  - smartnic
  - scheduling
  - virtualization
  - datacenter
category: datacenter-scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Tai Chi 把 SmartNIC 控制面任务放进可抢占的 vCPU 上执行，同时让数据面服务继续运行在原生物理 CPU 上。统一 IPI 层和硬件 workload probe 让两者能在微秒级切换，最终把生产环境中的 VM 启动时延降到原来的 1/3.1 左右，同时把数据面平均开销压在约 0.7%。

## 问题背景

现代 SmartNIC 部署通常已经把 DPDK、SPDK 这类数据面服务，与设备初始化、监控、编排等控制面任务分开。为了避免控制面干扰延迟敏感的包处理和存储路径，运维系统会静态绑定 CPU。论文指出，这种做法既浪费，又越来越跟不上规模增长：在 Alibaba 的 IaaS 生产环境里，数据面 CPU 在 99% 的运行时间内有 67.5% 的周期处于空闲状态，但随着实例密度上升，控制面任务依然持续违反 SLO。在 4 倍实例密度下，控制面任务平均执行时间增加到 8 倍，VM 启动时间则超出目标 3.1 倍。

直接拿这些空闲周期给控制面也并不简单。控制面任务不是可随便延后的 best-effort 作业，它们自己也承载着严格的运维 SLO。更麻烦的是，它们经常进入毫秒级的内核不可抢占路径；如果直接和数据面线程同核运行，就会把长尾时延注入数据面。论文的生产 trace 在 12 小时内记录到超过 45.6 万次持续 1 ms 以上的不可抢占例程，最长达到 67 ms。已有 LC/BE 调度器大多面向 bare metal，默认任务语义不同，或者需要额外调度核心，或者要求对 300 到 500 个异构控制面任务做侵入式改造，因此不适合 SmartNIC 场景。

## 核心洞察

论文的核心想法，是把 virtualization 当成精细调度原语，而不是完整的 guest 隔离边界。只要把控制面任务放进 vCPU context，它们即使正在执行内核里的不可抢占路径，也能在 VM-exit 边界被打断。与此同时，数据面服务继续运行在 SmartNIC 原生 OS 的物理 CPU 上，就能避开传统 virtualization tax。

表面上看，这仍然可能太慢，因为从 vCPU 切回数据面大约要 2 微秒。Tai Chi 的第二个洞察是，SmartNIC 的 I/O accelerator 会先于软件看到新到来的工作。论文测得 accelerator 的预处理窗口是 3.2 微秒，足够在包真正到达 polling loop 之前触发抢占并恢复数据面线程。换句话说，硬件 offload 不只是加速器，也成了调度预告器。

## 设计

Tai Chi 在同一个 OS 镜像里同时暴露 virtual CPU 和 physical CPU。控制面任务通过普通 CPU affinity 绑到 vCPU 上，数据面服务继续固定在 pCPU 上。vCPU scheduler 通过专用 softirq 完成上下文切换：当数据面看起来空闲时，Tai Chi 选一个 runnable vCPU 放到该物理核心上执行；当时间片到期或新 I/O 到达时，再保存 vCPU 状态、恢复 pCPU 状态，并把控制权还给数据面。

DP-to-CP 调度由 software workload probe 驱动。每个 polling 数据面线程通过一个很小的 API 报告连续 empty polling 的情况，Tai Chi 再根据 VM-exit 原因自适应地调整“多空才算空闲”的阈值。若 VM-exit 由时间片到期触发，说明该核心比预期更空闲，阈值就降低；若 VM-exit 是因为新 I/O 到达而抢回数据面，说明前一次 yield 过于激进，阈值就提高。vCPU 时间片初始为 50 微秒，在持续空闲时翻倍，在硬件 probe 抢占时重置。

要让“同一个 OS 里同时有 pCPU 和 vCPU”真正可用，论文又加了两项关键机制。第一是 unified IPI orchestrator。它拦截 inter-processor interrupt，并在 pCPU 与 vCPU 之间正确路由，包括在必要时先唤醒 sleeping vCPU。Tai Chi 还把 vCPU 注册成 OS 看起来的“原生 CPU”，这样现有控制面进程不需要改代码就能用 standard affinity 机制跑到 vCPU 上。第二是硬件 workload probe。它运行在 SmartNIC accelerator 中，维护每个 CPU 的 P/V 状态，在 I/O 预处理前查看目标 CPU；如果该 CPU 当前在跑 vCPU，就立即触发中断。Tai Chi 把这个 VM-exit 与 accelerator 的 2.7 微秒预处理和 0.5 微秒 DMA 阶段重叠起来，从而把切回数据面的代价基本藏掉。论文还额外加入 lock-aware 规则：如果被抢占的控制面任务持有锁，就立刻把它迁到另一颗可用核心继续跑，避免死锁。

## 实验评估

实验平台是一个 IaaS SmartNIC 部署环境，SmartNIC 侧有 12 个 CPU，host 侧有 96 个 CPU，并运行接近生产的网络与存储服务。baseline 是生产里已经使用的静态分区方案：8 个 CPU 给数据面，4 个 CPU 给控制面。这个 baseline 很有部署意义，但也意味着论文主要依赖 ablation 来论证，而不是和先前学术调度器做完全同机条件下的正面对比。

在控制面上，Tai Chi 在 32 个并发 CP 任务时把 synthetic benchmark 的平均执行时间提升了 4 倍，同时把数据面利用率维持在生产 p99 的 30%。在 virtualization 成本方面，ablation 很清楚：如果把数据面也放进 vCPU，网络吞吐平均损失约 8%，存储 IOPS 损失 6%；如果采用 type-2 的 QEMU/KVM 设计，这两个损失会扩大到 26% 和 25.7%。完整 Tai Chi 则把开销压到 0.2% 和 0.06%，支持了“数据面必须留在物理 CPU 上”的论点。硬件 probe 同样关键：没有它时，ping RTT 会从 26/30/38 微秒的最小值、平均值、最大值上升到 32/37/115；有了它以后，Tai Chi 几乎与 baseline 一致，为 27/30/38。跨 netperf、sockperf、MySQL 和 Nginx 的总体数据面平均开销为 0.7%，最高 1.92%。最有说服力的仍是生产结果：系统在上线并稳定运行三年多之后，高密度集群的平均 VM 启动时延下降了 3.1 倍，而且 rollout 和长期运行期间都没有报告用户可感知的 I/O SLO 违例。

## 创新性与影响

Tai Chi 的新意，在于把三件通常分开研究的事拼成一个可部署整体：基于 vCPU 的可抢占性、virtual CPU 与 physical CPU 在同一 OS 中的原生 IPC，以及 accelerator 辅助的数据面恢复预测。它带来的不只是一个更好的 scheduler，而是一种新的 SmartNIC 执行模型，让云厂商可以把原本浪费掉的数据面空闲周期，视作安全且可回收的控制面容量。这篇论文会被 SmartNIC runtime 设计者、云控制面工程师，以及研究小 CPU 预算下异构负载调度的人持续引用。

## 局限性

这套方法依赖硬件辅助 virtualization，以及能够暴露预处理窗口的 programmable SmartNIC accelerator。实现层面还要求较深的内核集成、IPI 拦截，以及数据面增加一个很小的 API 去上报 idle polling，因此“zero code modifications”主要针对 legacy control-plane 系统，而不是整个软件栈。论文对跨厂商可移植性的论证更多是架构层面的，而不是实证层面的：真实部署来自单一云厂商，也没有在第三方 SmartNIC 平台上展示结果。评估在内部 ablation 和生产相关性上很强，但在与其他学术调度器的同平台直接对比上相对较弱。

## 相关工作

- _Ousterhout et al. (NSDI '19)_ - Shenango 在 bare metal 上为延迟敏感服务回收核心；Tai Chi 面向的是 SmartNIC 上数据面与控制面的共调度，而且被借用的控制面任务本身也有 SLO。
- _Fried et al. (OSDI '20)_ - Caladan 能在微秒尺度重分配核心，但仍依赖常规软件调度路径，无法切开 SmartNIC 控制面里的不可抢占内核例程。
- _Iyer et al. (SOSP '23)_ - Concord 关注微秒级调度效率，而 Tai Chi 通过 hybrid virtualization 和 accelerator hint 同时保住原生 IPC 语义与 SmartNIC 兼容性。
- _Barham et al. (SOSP '03)_ - Xen 展示了 type-1 virtualization 作为通用隔离基底的做法；Tai Chi 则只把控制面虚拟化，从而避免数据面承担 guest-mode 开销。

## 我的笔记

<!-- 留空；由人工补充 -->
