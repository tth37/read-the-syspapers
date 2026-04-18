---
title: "Towards Energy Efficient 5G vRAN Servers"
oneline: "RENC 把低负载 5G vRAN 时段显式变成安全的节能模式，用 deadline slack 测量配合 MAC rate limiting 来降低 core 与 uncore 频率。"
authors:
  - "Anuj Kalia"
  - "Nikita Lazarev"
  - "Leyang Xue"
  - "Xenofon Foukas"
  - "Bozidar Radunovic"
  - "Francis Y. Yan"
affiliations:
  - "Microsoft"
  - "MIT"
  - "University of Edinburgh"
  - "Microsoft and UIUC"
conference: nsdi-2025
category: wireless-cellular-and-real-time-media
tags:
  - energy
  - networking
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

RENC 通过先构造“安全的低负载区间”，再只在这些区间内降低 CPU core 和 uncore 频率，来降低商用 5G vRAN 服务器的能耗。它不要求拿到源代码，而是用内核 eBPF 测量 interrupt-driven 线程的 deadline slack，并对 busy-polling 的 PHY 线程做轻量二进制插桩。作者在商用级测试床上报告，低流量时 CPU 功耗最高可降 45%，整机功耗可降 29%。

## 问题背景

这篇论文解决的是一个很现实但很难下手的问题：vRAN 的 DU 服务器很耗电，但运营商又不能直接把通用 CPU 节能策略套进去。原因首先在于实时性。商用 5G DU 的很多线程都绑定在 500 us 的 transmission time interval 上，错过 deadline 不是简单的性能下降，而可能导致掉话、功能异常，甚至把 vRAN 软件直接搞崩。更麻烦的是，负载在亚毫秒尺度上高度突发，相邻两个 TTI 可以从几乎空闲瞬间跳到满负载。

因此，常见的 CPU 节能机制都不合适。像 C6 这样的深睡眠态，在论文使用的 Ice Lake 服务器上需要 600 us residency time 和 170 us wakeup time，本身就超过了 5G 的 TTI 预算。固件控制的 P-state 也太慢，Intel HWP 在 core 频率上大约要 60 ms 才能跟上突发，uncore 也要约 10 ms，而 DU 需要的是毫秒级甚至更快的反应。所以生产环境中的 vRAN 往往干脆把 CPU 长期钉在高频。

第二个障碍来自软件封闭性。商用 vRAN 栈通常是供应商交付的专有二进制，运营商既不能随意往里面加 instrumentation，也不能按每家厂商的内部实现去重写调度逻辑。传统 energy-aware realtime 方法默认你看得到程序内部，而这里恰恰看不到。论文同时证明了“值得优化”的窗口确实很多：作者抓到的 LTE trace 显示，在一个繁忙小区里，超过一半的 50 ms 窗口低于峰值流量的 1%；另一个小区更是有 60-80% 的窗口低于这个水平。真正困难的不是找不到低负载，而是在闭源软件里安全利用这些窗口。

## 核心洞察

RENC 的核心命题是：只有把低负载区间从那些偶发但会吃满 deadline 的 spike 中分离出来，vRAN 的节能才变得可做。如果把 slack 按“所有时间”一起测，只要出现一次高负载 TTI，最小 slack 就会被拉到接近 0，系统便不敢安全地降频。相反，如果先隔离出“流量很低且没有昂贵控制操作”的区间，那么这些区间里的线程往往保留了相当可观的未用 deadline 比例，可以承受更低的 CPU 频率。

这个洞察同时改变了控制策略与测量策略。RENC 不试图精确预测每个 TTI 的需求，而是把系统切成低负载和高负载两种模式。高负载模式下，它保持保守，直接跑高频；低负载模式下，它先主动阻断新的突发，再测量线程是否仍然保有足够 slack。因为软件大多是黑盒，论文最重要的想法并不只是“空闲时降频”，而是“通过外部接口构造一个可被外部保守测量证明安全的低负载区间”。

## 设计

RENC 由一个外部 userspace agent 和一个很小的内核 eBPF 组件组成。它对厂商的要求不算多：只要知道 realtime 线程的名字和 deadline，知道少数 busy-polling PHY 线程关键函数的签名，并能拿到标准化的 DU telemetry 与 MAC control 接口即可。对于 MAC、RLC 这类 interrupt-driven 线程，RENC 把 eBPF 程序挂到 `sched_switch` 上，追踪每个 core 在什么时候处于 active 状态。由于 Linux eBPF 还拿不到 DU 对齐 TTI 的 wall clock，论文定义了一个保守的 “relaxed slack”：不按严格 TTI 边界，而是在任意一个 TTI 长度的窗口上看 active fraction 的最坏值。这样即便测量窗口跨过 TTI 边界，也仍然偏保守。对于完全不向 OS yield 的 busy-polling PHY 线程，RENC 则用 Dyninst 加 userspace eBPF probe 去包住少数 top-level 函数。

流量分类同样很务实。RENC 用每个 UE 的 buffer status report 估计上行需求，因为 BSR 会先于真正的数据到达；下行则用 CU 到 DU 接口上的吞吐量作为最早可见信号。只有当最近 50 ms 内所有样本都低于各自方向最大值的 1% 时，系统才进入低负载模式；只要最新样本越过阈值，就立刻切回高负载模式。进入低负载后，RENC 还会把 MAC scheduler 可分配的 resource blocks 限制到 10%，防止 CPU 还处于低频时突然闯入一波大流量。

真正关键的是切换顺序。低负载切到高负载时，RENC 先把 CPU 频率升上去，并把 eBPF 里的 load type 标成 high-load，等这两个变化都生效后，才取消 MAC rate limit。高负载切到低负载时，顺序反过来：先下发 rate limit，等其生效后，再降低 core 和 uncore 频率。正是这种耦合，让“限流 + 降频”从 best-effort 优化变成了带安全边界的 deadline 保护机制。除此之外，RENC 还专门处理控制面 spike：它会拦截 FAPI random-access 消息和 F1AP UE-context release 消息，因为这些事件会触发昂贵的 UE 状态建立与释放工作，于是系统会临时强制进入 high-load 模式。

具体调频采用迭代式过程。RENC 在一个观察窗口内收集低负载 slack 样本，以 10% slack 作为阈值，优先降低 uncore，因为它本身就是显著的功耗来源，而且一个旋钮会影响整个 package；如果所有 core 还有余量，再逐步下调各个 core 的频率。

## 实验评估

评估使用的不是教学性质的开源栈，而是商用级配置：HPE DL110 Gen10 telco server、Xeon 6338N、Intel FlexRAN PHY、CapGemini DU/CU 软件、两个 5G 100 MHz 4x4 小区，以及最多九台商用 5G UE。这个设置很重要，因为论文的主张本来就是针对“黑盒、生产风格”的 vRAN 软件，而不是仅在开源原型上验证。

最强的结果来自 idle 和低流量场景。九台 UE 挂网但不传业务时，在启用 C1 的基础上再打开 RENC，CPU 功耗从 119 W 降到 66 W，整机功耗从 225 W 降到 160 W，也就是相对 C1 baseline 分别节省 45% 和 29%。Intel HWP 仍然要消耗 123 W 的 CPU 功率，因为 realtime 线程即便空闲也会频繁醒来，足以把固件误导到较高频率。性能方面的代价则很小：SpeedTest 结果基本不变，不开 RENC 时下行 486-520 Mbps、上行 29.6-29.7 Mbps，开 RENC 后下行 499-520 Mbps、上行 29.7 Mbps；平均 ping 也只是从 27.1 ms 变到 27.9 ms。

动态业务实验说明 RENC 不只是 idle-mode 技巧。九台 UE 同时看视频时，平均 CPU 功耗从 121 W 降到 83 W，因为视频缓冲会形成一段一段的下载空隙，RENC 正好能利用这些 gap。更复杂的 traffic mix 下，平均功耗也从 121 W 降到 109 W。微基准进一步支撑其机制：短文件传输在 RENC 下的完成时间与静态 100% RB 配置相比只高不到 2%，而关键线程的 low-load slack 则从不开 RENC 时的 0-8% 提高到 64-79%。Table 6 对贡献拆分尤其有用：只降低 uncore 就能把 CPU 功耗从 117 W 降到 80 W，再叠加 core 降频则进一步降到 67 W。总体上，这组实验充分支持了论文关于“低负载区间可安全降频”的核心论点，但并没有声称高负载时也能取得类似节能。

## 创新性与影响

这篇论文的新意不在于单独发明了某个 DVFS 算法，而在于把此前分散处理的三件事合在一起：在大体闭源的软件里外部测量 deadline slack，显式构造安全的低负载区间，以及把 MAC rate limiting 与频率切换耦合起来，使低功耗状态真正安全。与 CRT、vrAIn 这类 vRAN 节能工作相比，RENC 对商用 DU 场景下的 deadline safety 讲得更具体、更工程化；与一般 realtime DVFS 文献相比，它补上了运营商在实践中最缺的“可观测性”这一环。

因此，它会影响两类读者。对 vRAN 厂商和运营商来说，这是一份无需重写 PHY 就能落地的节能蓝图。对系统研究者来说，它给出了一个更一般的模式：当硬实时软件既突发又不透明时，与其试图时时刻刻精确估计 worst case execution，不如先隔离“安全区间”，再在区间内做保守 slack 测量。这更像一个新机制，而不只是一次测量报告。

## 局限性

RENC 只优化低负载时段。只要业务真的很高，它就退回到保守基线，把频率拉满，因此高负载下的节能仍留给未来工作。论文中的阈值也带有经验性，例如进入低负载的 1% traffic threshold、rate limiting 时保留的 10% RB、以及进一步降频所需的 10% slack threshold。作者证明这些阈值在其平台上可行，但它们未必能无修改迁移到所有硬件和无线配置。

此外，所谓“透明”其实是部分透明，而不是零侵入。RENC 仍需要线程名、deadline、polling 线程关键函数签名，以及低延迟的 MAC telemetry/control 接口。作者的 DU 里甚至有一种 busy-polling 线程没有被完整插桩，而是通过人工确认其在最低频率下也安全。实验规模也不大，RU 侧功耗没有被精确测量，因此整个 RAN 端到端节能图景仍不完整。最后，它与 prior open-source 系统的比较主要是方法层面的，不是完全同硬件、同软件栈下的 head-to-head artifact 对比。

## 相关工作

- _Pawar et al. (GLOBECOM '21)_ - CRT 预先把 MAC 条件静态映射到 CPU 频率，而 RENC 在运行时测量 slack，并通过显式 low-load interval 来保证降频安全。
- _Ayala-Romero et al. (MobiCom '19)_ - vrAIn 用学习方法联合调 radio 与 compute 资源，但并不面向商用 black-box DU 中的硬 deadline 安全性。
- _Foukas and Radunovic (SIGCOMM '21)_ - Concordia 预测 PHY 执行时间，用来让 vRAN core 与其他工作负载共享算力；RENC 则把类似的 slack 用于节能。
- _Garcia-Aviles et al. (MobiCom '21)_ - Nuberu 通过重设计 PHY 来提升对干扰的容忍度，而 RENC 的前提是 deadline miss 仍然不可接受，因此尽量在不改动商用软件的情况下工作。

## 我的笔记

<!-- 留空；由人工补充 -->
