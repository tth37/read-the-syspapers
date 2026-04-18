---
title: "XSched: Preemptive Scheduling for Diverse XPUs"
oneline: "XSched 把加速器命令队列包装成可抢占的 XQueue，并用三级抢占能力把同一套调度策略扩展到 GPU、NPU、ASIC 和 FPGA。"
authors:
  - "Weihang Shen"
  - "Mingcong Han"
  - "Jialong Liu"
  - "Rong Chen"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
conference: osdi-2025
code_url: "https://github.com/XpuOS/xsched"
tags:
  - scheduling
  - gpu
  - hardware
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

XSched 把加速器工作负载表示成可抢占的 XQueue，并用三级抢占能力去处理 pending、in-flight 与 running 命令。这样，同一套调度器就能跨 GPU、NPU、ASIC 与 FPGA 运行；论文在十种 XPU 上把高优先级任务的 P99 延迟最多降低了 2.10x，案例研究还展示了 9.26x 的 NPU 帧尾延迟改善，以及 Triton 中高优先级推理延迟 30.0% 的下降。

## 问题背景

越来越多的系统会把一块 XPU 共享给多个互不相同的任务：云平台在一块 GPU 上复用多个租户，AI PC 在一块 NPU 上同时跑多个模型，自动驾驶和多媒体场景则会把实时任务和后台推理混在一起。可多数设备仍然依赖非抢占式 FCFS 队列，或者只在进程之间做很粗糙的 round-robin，于是高优先级任务可能被一长串已经提交的命令挡在后面。论文给出的动机例子很直接：在 Intel NPU 上，real-time fake-background 与 speech-to-text 共跑时，尾延迟会上升二十多倍。

另一个看似自然的方案是让主机 CPU 接管调度。问题在于，已有方案大多绑死在某一类加速器、某个驱动栈，或者某种特定能力上，比如内核改写、私有 ioctl，或某个厂商暴露的微控制器接口。它们没有给 GPU、NPU、ASIC 和 FPGA 提供统一的调度单位，也很难随着硬件能力的增减一起演化。XSched 的判断是，真正缺的不是又一个 GPU 专用优化，而是一套面向加速器调度的可移植抽象和能力模型。

## 核心洞察

论文最重要的主张是，跨 XPU 真正稳定的共同点不是计算核心，而是由主机下发的命令队列。尽管架构差异很大，多数加速器最终都把任务表示成按顺序执行的一串命令，例如 kernel、copy 或 operator。XSched 因而把任务抽象成可抢占的命令队列 XQueue，正如操作系统把 CPU 工作抽象成可抢占线程一样。

一旦从“命令处于什么状态”而不是“这是什么品牌的设备”来描述抢占问题，硬件异构性就能被整理成三级能力阶梯。第一级处理尚未启动的 pending 命令，第二级处理已经下发但还没真正执行的 in-flight 命令，第三级则处理当前正在运行的命令。能力弱的设备至少也能做 Level 1；能力强的设备再暴露队列停用或中断能力，就能提升到 Level 2/3。论文的第二个关键洞察是，主机想保留控制权，并不意味着必须每条命令都同步执行。只要软件只放行一个有界的 in-flight 前沿，就能同时保住流水效率和可预测的抢占延迟。

## 设计

XQueue 提供四个接口：`submit`、`wait`、`suspend` 和 `resume`。应用既可以直接调用这些接口，也可以依赖预加载的 XShim 去截获原生驱动 API，再把命令转交给 XSched。系统内部由三层组成：XPreempt 负责实现队列抽象，XAL 把抽象操作映射成具体设备机制，XScheduler 则以 daemon 的形式在进程或容器之间执行调度策略。

真正困难的地方在于：命令一旦下发，主机如何继续保有控制权。一个朴素做法是每条命令后都同步，但论文证明这会严重破坏 XPU 的异步流水，额外开销可达 8.2% 到 151.3%。XSched 的答案是 progressive command launching。每个 XQueue 维护 pending buffer、in-flight log、worker thread，以及一个限制有多少命令可以逃逸到硬件队列中的阈值。只要超过阈值，worker 就先等待其中一半完成，再继续下发，因此挂起时只需等待一个有界前沿，而不必等整项任务完成。

三级硬件模型则把这套机制扩展成一组实现路径。Level 1 最通用：停止继续 launch，并同步剩余命令。Level 2 新增 `deactivate` 与 `reactivate`，让 in-flight 命令还没开始执行就被拦住；XSched 在 Intel NPU 上用固件辅助的 stall，在 NVIDIA GPU 上则用动态二进制插桩注入 guardian 代码，由主机翻转每个队列的 flag，让 kernel 自行 abort。Level 3 再增加 `interrupt` 与 `restore`，去处理中途正在运行的命令。论文在较新的 NVIDIA GPU 上展示了 TSG 粒度的中断，以及更细粒度、基于未文档化 trap 处理路径的队列级中断，不过被打断的 kernel 仍然要从头重启，而且必须是 idempotent 的。

## 实验评估

从平台覆盖面看，评估相当扎实，也基本支撑了论文的核心论点。XSched 被移植到七种软件平台和十种 XPU 上，而最基础的 Level 1 支持每个平台只需 214 到 841 行 C++。

在调度效果上，fixed-priority 策略能把前台任务延迟拉回到接近独占运行的水平。使用原生调度时，foreground 的 P99 往往是 standalone 的 1.60x 到 2.19x；换成 XSched 后，这个比例收敛到 1.02x 到 1.30x，并且相对原生调度最高改善 2.11x。bandwidth-partition 策略在 75/25 的前后台配额下只带来 1.5% 的平均开销；对于异构平台，把 GPU 与 NPU 队列统一调度还能把 foreground NPU 任务的 P99 最多降低 2.63x。

更重要的是，实验确实验证了三级模型的意义。若 in-flight 阈值设为 8，且每条命令执行时间为 `T`，那么 Level 1 的 P99 抢占延迟大约是 `8T`，Level 2 下降到约 `T`，而 GV100 上的 Level 3 可做到与 `T` 无关的 32 us。与此同时，所有测试 XPU 的 Level 1 运行时开销都低于 3.4%。案例研究也很有说服力：XSched 在保护 production container 的同时，比 TGS 多回收 2.74x 的 opportunistic GPU 工作；把 Intel NPU 视频会议场景的帧 P99 从 880 ms 压到 95 ms；并且只用十行代码就把 Triton 中高优先级推理的 P99 再降 30.0%。不过，最深的低延迟机制主要还是在 NVIDIA GPU 和一款 Intel NPU 上验证得最充分。

## 创新性与影响

相对于 TimeGraph、EffiSha 和 FLEP，XSched 不是另一个只对某类加速器生效的抢占技巧。它真正的新意在于，把抢占拆成“可移植抽象 + 能力阶梯”，使同一套策略逻辑能跨越厂商和设备类型继续成立。相对于 REEF，它又把问题从单一 GPU 软件栈扩展成一组可替换实现路径，并且给出了作者声称首个面向 NPU 和 ASIC 的软件式抢占支持。这让 XQueue 成为类似线程的加速器调度单位，也让三级模型成为硬件逐步暴露调度能力的一种语言。

## 局限性

XSched 的可移植性是真实存在的，但并不均匀。Level 1 很容易复用，Level 2 和 Level 3 则明显依赖固件特性、未公开接口，或者设备特定的二进制插桩。尤其是 NVIDIA 上的队列级 Level 3 目前只支持 idempotent kernel，而且还需要人工识别，这在部署上是一个实际约束，而不是无关紧要的小问题。

此外，这套框架默认 XPU 遵循“主机下发命令、设备被动执行”的常见模式。对于不依赖主机命令队列、能够主动执行任务的设备，或像 CUDA graph、某些 NPU 单次推理那样的单命令任务，以及显存不足需要和调度一起处理内存置换的场景，论文都没有直接解决。最后，系统还默认访问路径受到中介控制；如果恶意租户绕过 XQueue 或 XShim，仍可能垄断设备，除非底层再配合虚拟化或 API remoting。

## 相关工作

- _Kato et al. (USENIX ATC '11)_ — TimeGraph 通过限制 GPU 命令提交来近似实现抢占式调度，而 XSched 把这一思路推广成可跨多类 XPU 的统一抽象。
- _Chen et al. (PPoPP '17)_ — EffiSha 通过改写 GPU kernel 来实现抢占；XSched 则把这类 flushing 技术收编为更大框架中的一种可替换 Level 2 实现。
- _Han et al. (OSDI '22)_ — REEF 在 AMD GPU 上实现了微秒级抢占，但 XSched 把抢占提升为跨厂商、跨加速器的模型，并提供多条实现路径。
- _Ng et al. (SOSP '23)_ — Paella 是面向 GPU serving 的专用调度器，而 XSched 提供的是可复用的底层调度基座，可以被 Triton 这类系统直接整合。

## 我的笔记

<!-- 留空；由人工补充 -->
