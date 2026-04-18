---
title: "Aeolia: A Fast and Secure Userspace Interrupt-Based Storage Stack"
oneline: "Aeolia 直接把 NVMe 完成中断送到用户态，并用 MPK 保护的可信组件和 sched_ext 把 kernel-bypass 存储做成可共享、低延迟的通用栈。"
authors:
  - "Chuandong Li"
  - "Ran Yi"
  - "Zonghao Zhang"
  - "Jing Liu"
  - "Changwoo Min"
  - "Jie Zhang"
  - "Yingwei Luo"
  - "Xiaolin Wang"
  - "Zhenlin Wang"
  - "Diyu Zhou"
affiliations:
  - "Peking University"
  - "Zhongguancun Laboratory"
  - "Microsoft Research"
  - "Igalia"
  - "Michigan Technological University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764816"
code_url: "https://github.com/TELOS-syslab/Aeolia"
tags:
  - storage
  - filesystems
  - scheduling
  - security
  - ebpf
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Aeolia 证明，userspace storage stack 不必依赖 polling 才能获得低延迟。它用 user interrupt 处理 NVMe 完成，用 MPK 保护的可信代码维护权限与元数据安全，再通过 `sched_ext` 避免无谓的睡眠和唤醒。这样一来，`AeoDriver` 在单任务 I/O 上接近 SPDK，而 `AeoFS` 则能像真正的共享文件系统那样扩展。

## 问题背景

现代 NVMe SSD 的介质延迟已经降到几微秒量级，于是软件路径而不是设备本身开始主导端到端 I/O 成本。现有设计基本落在两个角上。像 SPDK 这样的 polling-based userspace stack 之所以快，是因为它避开了 kernel crossing 与层层抽象；但它很难安全共享磁盘，而且 polling 会持续吞掉 CPU，使调度器难以及时运行 I/O 刚完成的线程。传统 kernel interrupt-based stack 则擅长权限仲裁与多任务共享，却始终要承担 trapping、layering 和内核调度带来的通用开销。

文件系统层把这个矛盾放大了。uFS 这类系统通过把文件系统放进单独的 polling 进程来恢复 protected sharing，但每个操作都要付 IPC 成本，还得依赖更集中、更保守的 worker 结构来压低 polling 开销。论文因此追求的是更强的组合：direct access、coordinated scheduling、protected sharing，以及真正高性能的文件系统。

## 核心洞察

这篇论文最重要的洞察是：userspace stack 快，并不意味着“轮询”本身就是关键原因。作者对 `io_uring` 的分解显示，`4 KB` 读请求里 default interrupt 和 polling 之间 `2.8 us` 的差距，只有 `0.6 us` 来自 interrupt mechanism，本质上的大头 `1.8 us` 来自“把发请求的线程先睡掉，再在完成后重新唤醒”。如果在没有别的 runnable 线程时继续运行当前线程，那么 interrupt 就能拿到大部分 polling 的低延迟，却不用像 polling 那样浪费核心时间。

这就打开了一个新的设计点：只要完成中断能直接送到用户态，并且用户态存储栈内部存在小型可信执行体去维护权限与元数据不变量，那么 kernel-bypass stack 就不必继续在“快”和“可共享”之间二选一。

## 设计

Aeolia 由三部分组成。`AeoKern` 负责设置 queue pair、权限与调度状态；`AeoDriver` 是直接提交请求并在用户态处理完成的 NVMe driver；`AeoFS` 是建立在其上的 POSIX-like library file system。

最难的机制是把 device completion 变成真正的 userspace interrupt。Aeolia 让设备中断向量与线程的 `UINV` 匹配，并把线程的 `UPID` 映射进 `AeoDriver` 的可信区域，使 handler 能在用户态直接重写 `PIR`，不必再 trap 回内核。对于线程不在运行态时到来的 completion，它先让中断进内核，以便调度器及时把目标线程标记为 runnable。

安全共享依赖 MPK 进程内隔离，而不是单独的 privileged server。可信代码运行在受保护域内，`AeoDriver` 维护 per-block permission table，`AeoFS` 则把可信 core metadata 与不可信 cache 分开，从而能对 `create`、`rename`、inode 更新等操作做 eager checking。

调度协调来自 `sched_ext`。可信用户态从 eBPF map 读取与 `EEVDF` 等价的调度状态，只在内核本来也应该 reschedule 的决策点调用 `sched_yield()`。在这个基础上，`AeoFS` 再构建可扩展 cache、per-inode 锁和 per-thread ordered-mode journaling。

## 实验评估

实验平台是一台 128 核 Xeon Platinum 8592 机器，配 Optane P5800X。这个平台对 Aeolia 是偏苛刻的，因为设备延迟极低，会把 interrupt overhead 放大到最显眼的程度。对比对象包括调优后的 Linux 路径以及 SPDK。结果显示 `AeoDriver` 明显优于传统内核路径、同时又接近 SPDK：在 `512 B` 读上，它相对 POSIX 达到 `2x` 吞吐、`48%` 更低的中位延迟；最差的小 I/O 情况下，它比 SPDK 低 `10.7%` 吞吐。

真正关键的是 shared-core 场景。当 latency-sensitive I/O 线程与 compute-bound 或 throughput 线程共核运行时，`AeoDriver` 相比 `SPDK`/`iou_poll` 的 tail latency 改善达到 `8.18x` 到 `291.72x`，说明 interrupt-driven userspace 的调度协调能力明显强于 polling。

`AeoFS` 也从这套底座中获得直接收益。单线程 `4 KB` 数据访问上，它相对 `ext4` 和 `f2fs` 最多快 `12.6x` 与 `12.8x`；`64` 线程 `2 MB` 写负载下，又分别超过 `ext4`、`f2fs`、`uFS` 达到 `19.1x`、`28.9x` 和 `8.4x`。在 Filebench 上，它最多比 `ext4` 和 `f2fs` 快 `3.1x` 与 `6.6x`；在 LevelDB 上，又最多超过 `ext4`、`f2fs`、`uFS` 达到 `2.9x`、`3.4x`、`8.2x`。论文还报告了针对可信组件手工构造的 `96` 个攻击用例，并称 Aeolia 全部成功阻挡。总体上，评估覆盖面较广，但 crash consistency 仍只做了 unit test，而且有一组 `uFS` macrobenchmark 因初始配置跑不稳，作者后来改用其仓库自带设置重跑。

## 创新性与影响

Aeolia 的创新点不是“更快的 SPDK 克隆”，而是把 userspace direct access、interrupt delivery、protected sharing 和 scheduler awareness 放进同一个过去被认为不现实的设计点里。它的重要影响在于提出了一个更强的判断：kernel bypass 不必等价于 polling，这对必须与其他任务共享核心的系统尤其重要。

## 局限性

Aeolia 依赖较新的平台特性：Intel user interrupts、MPK 风格的进程内隔离，以及 Linux `sched_ext`。对小于 `4 KB` 的请求，interrupt 也仍会略输给 polling。原型还没有实现用于支撑保护不变量的 launch-time signature registration 与 privileged launcher。

`AeoFS` 在多个不可信应用频繁更新同一文件或共享目录时会输给 `uFS`，因为重建 auxiliary state 与同步 eager checks 的成本较高。另一个现实问题是，论文虽然较详细地描述了 journaling 方案，但 crash consistency 仍只用 unit test 验证，没有更强的崩溃注入测试。

## 相关工作

- _Yang et al. (CloudCom '17)_ - SPDK 奠定了 polling-based direct userspace storage 的性能基线，而 Aeolia 保留 direct NVMe access、改用 user interrupts，并补上 protected sharing。
- _Liu et al. (SOSP '21)_ - uFS 同样追求高性能 userspace file system，但它依赖 IPC 与 dedicated polling worker；AeoFS 则把 fast path 收回到应用进程内部，并用进程内可信组件保障安全。
- _Zhou et al. (SOSP '23)_ - Trio 为 NVMM 上的 secure library file system 提出了 core state 与 auxiliary state 分离；AeoFS 借用这一思路处理 SSD，并把 lazy verification 改成 eager metadata checking。
- _Zhong et al. (OSDI '22)_ - XRP 通过把用户定义的存储逻辑推入 kernel NVMe driver 来保留文件系统语义，而 Aeolia 选择把栈移向用户态，再在用户态解决隔离与调度问题。

## 我的笔记

<!-- 留空；由人工补充 -->
