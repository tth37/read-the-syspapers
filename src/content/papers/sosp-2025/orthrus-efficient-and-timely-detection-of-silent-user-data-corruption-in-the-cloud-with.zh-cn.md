---
title: "Orthrus: Efficient and Timely Detection of Silent User Data Corruption in the Cloud with Resource-Adaptive Computation Validation"
oneline: "Orthrus 让开发者标注数据路径算子，并用跨核异步重执行与边界校验和在线发现多数云端静默数据损坏，同时把开销压到较低水平。"
authors:
  - "Chenxiao Liu"
  - "Zhenting Zhu"
  - "Quanxi Li"
  - "Yanwen Xia"
  - "Yifan Qiao"
  - "Xiangyun Deng"
  - "Youyou Lu"
  - "Tao Xie"
  - "Huimin Cui"
  - "Zidong Du"
  - "Harry Xu"
  - "Chenxi Wang"
affiliations:
  - "University of Chinese Academy of Sciences"
  - "UCLA"
  - "UC Berkeley"
  - "Peking University"
  - "Tsinghua University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764832"
code_url: "https://github.com/ICTPLSys/Orthrus"
tags:
  - fault-tolerance
  - observability
  - datacenter
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Orthrus 试图在不支付整应用复制成本的前提下，拦住由部署后 CPU 错误引发的静默用户数据损坏。它要求开发者标注 user-data 类型和 data-path closure，再借助编译器插入的版本化内存、异步跨核重执行，以及 control/data 边界上的轻量校验和，在平均约 4% 的运行时开销下检测大多数损坏。

## 问题背景

论文的出发点是一个很现实的云端运维问题：现代数据中心 CPU 在上线后仍可能变成 “mercurial” core，在某些核心上持续、可复现地出现极少量计算错误。对云服务来说，最糟糕的不是程序崩掉，而是错误悄悄改坏了用户数据却仍然正常返回结果。错误的账户余额、错误的 KV 查询结果、错误的数据处理输出，都会直接变成 SLA 违约、人工排障和责任认定问题。

现有方案要么抓不住真正的损害点，要么太贵。离线 CPU 压测能在事后找出坏处理器，却无法告诉你在下一次巡检前到底有哪些用户数据已经被污染。普通 checksum 只能检查数据在存储或传输中是否被直接篡改，无法发现 “计算本身算错了、却写回了一个格式完全正确的错误值” 这种问题。另一端的 replication-based validation 会在另一台机器上重跑整套应用，instruction-level validation 甚至会近似逐指令比对执行。这些方法覆盖更强，但 CPU、内存和同步成本过高，不适合常驻在线云服务。

Orthrus 因而把问题缩小成一个更可落地的版本：能不能只验证那些真正对用户数据做计算的代码片段，并且让验证足够快、足够便宜，以至于生产环境愿意一直开着？

## 核心洞察

这篇论文最核心的判断是，许多云应用天然存在一条有用的边界：control path 负责解析请求、调度执行、搬运数据，通常并不真正“计算”用户数据；data path 则由 `get`、`set`、`insert`、`map`、`reduce` 之类紧凑算子组成，真正修改用户可见状态。只要 Orthrus 在另一颗核心上，用同一份输入和同一份初始堆状态重新执行这些 data-path 算子，就能捕获绝大多数真正危险的 CPU 引发损坏，而不必复制整个进程。

这个拆分还自然导向了一种 hybrid validator。data path 值得花重执行成本，因为错误计算就在这里真正改变用户数据；control path 则可以在数据穿越 control/data 边界时，用廉价 checksum 做完整性检查。换句话说，Orthrus 不想证明整程序正确，而是把有限的验证预算精确投到最可能造成静默数据损坏的位置。

## 设计

Orthrus 暴露两类注解：`user-data` 用来标记需要保护的类或结构体，`closure` 用来标记一个 data-path operator，也就是验证的基本单元。LLVM 编译器 pass 随后自动改写这段代码。被标注对象的分配会被替换成 `OrthrusNew`，进入一块版本化的共享用户数据空间；普通对象仍留在私有堆里。指向受保护对象的指针会被改写成 `OrthrusPtr`：`load()` 返回只读数据，`store()` 则执行 out-of-place 更新，生成一个新版本。编译器还做 escape analysis，把确定不会逃出 closure 生命周期的临时对象留在私有堆中，以减少版本和元数据开销。

运行时分成 application process 和 validator process。两者各自拥有私有堆，但共享同一块版本化 user-data space。每个 closure 执行结束时，Orthrus 会生成一条 closure log，记录 closure 身份、输入、输出、读过的数据版本，以及需要 replay 而非重执行的 system call 结果。因为日志和其引用的版本已经完整描述了 closure 的起始状态，validator 就能在另一颗核心上、在稍后甚至乱序地重新执行同一个 closure。其写入只发生在 validator 的私有堆中，最后再把输出与日志中的原始输出做比较；若用户自定义了相等运算符就调用它，否则退化为 bitwise comparison。

control path 的保护更轻。每个 user-data version 都带一个 16-bit CRC checksum。Orthrus 在创建新对象或新版本时生成 checksum，并在数据从 control path 进入 data path，或从 data path 回到 control path 时校验它。这样，解析请求、复制请求、转发请求等环节带来的边界损坏就能被低成本拦下，而无需对整条 control path 做重执行。

真正体现 “resource-adaptive” 的是调度器。Orthrus 维护 per-core validation queue，优先把验证放到同一 NUMA node 的空闲核心上，以复用缓存中的日志；资源紧张时再进入 sampling。它不是随机采样，而是优先挑选“最近没验证过”的 closure，或者在新的 caller context 下出现的同一 closure；同时，对包含 floating-point 或 vector 指令的 closure 给更高优先级，因为已有 fleet study 表明这些执行单元更容易出现相关错误。基于 Shenango 的 validator thread 还可以在某类 closure 的验证延迟升高时动态扩容，并通过 work stealing 避免长尾队列把损坏检测拖得太久。版本化内存带来的额外版本，则通过一个基于 visible window 与 closure active window 近似重叠判断的 GC 回收，避免内存持续膨胀。

## 实验评估

实验选了四个具有清晰 control/data 分离的真实应用：Memcached、Masstree、内存层的 LSMTree，以及 Phoenix MapReduce。硬件平台是三台双路 Xeon Gold 6342 服务器，机器间用 100 Gbps InfiniBand 互联。基线包括原始应用和 replication-based validation。由于真实 mercurial-core 错误很罕见，作者使用 LLVM 级机器指令注入框架，按 Alibaba 报告的 ALU、SIMD、FPU 与 cache 相关错误模式来构造故障。

最重要的结果是 Orthrus 基本贴着 vanilla 性能跑。跨 workload 平均下来，它只有约 4% 的运行时开销和 25% 的内存开销，而 RBV 分别达到约 2.0x 运行时和 2.1x 内存。Memcached 吞吐只下降 4.4%；Phoenix 的时间开销不到 2%；即便在刻意偏激的纯写 LSMTree workload 上，Orthrus 也仍保住了 95% 的原始吞吐。control/data 边界上的 checksum 额外成本不到 1%。

第二个关键结果是检测时效。Orthrus 的平均 validation latency 分别是 Memcached 1.6 微秒、Masstree 22.6 微秒、LSMTree 7.7 微秒、Phoenix 234 毫秒。在延迟敏感服务上，这比 RBV 低两到三个数量级，因为 Orthrus 只重执行 closure，使用共享内存日志，而且允许乱序验证，而不是把整套 replica 串行地跟在 primary 后面。

覆盖率则体现了它“有意不完美”的取舍。只给一个 validation core 时，Orthrus 平均能检测约 86.7% 的注入型 SDC；两核时升到约 91%；四核时升到约 96%。一核场景仍比纯随机采样高 1.41x。若给 Orthrus 与应用同样多的核，它在多数错误类型上的检测率会逼近 RBV，只是仍会略低，因为 RBV 会重放更多 control path 行为。

## 创新性与影响

相对 replication-based validation，Orthrus 的新意不在于“把备份副本做便宜一点”，而在于把冗余验证的粒度从整次请求执行缩小到被标注的 data-path closure。相对 instruction-level validation，它则主动放弃完备性，换取在 commodity cloud 服务器上的可部署性。真正让这个 trade-off 成立的，是编译器和运行时的一体化设计：版本化 user-data memory、closure log、跨核重执行与自适应采样并不是孤立点子，而是拼成了一套可以长期在线运行的机制。

它对数据存储和数据处理类云服务尤其有现实价值，因为这类系统往往本来就具有较清晰的 control/data 分界。更广义地说，这篇论文提供了一个值得复用的方法论：如果静默硬件错误是局部的、可复现的，那么在线保护机制不必镜像整个应用，只需镜像语义上真正危险的那一层。

## 局限性

Orthrus 从一开始就不是 complete safety net，而是 best-effort detector。它无法发现那些不会改变最终结果的 masked error。对于 closure 内部的非确定性 system call、同步原语或外部 I/O，它只能记录并重放结果，而不能直接验证这些操作本身，因此其中的损坏仍可能漏掉。它也可能错过 control path 把请求分发到错误 closure 的情况，因为 checksum 机制只验证边界上的数据完整性，不验证“跨越边界这件事本身是否正确”。

这套设计还依赖若干结构性前提。开发者需要识别 user-data 类型和 closure 边界；每个 closure 内部必须是单线程实现。sampling 意味着资源吃紧时一定会跳过部分执行，因此在 Phoenix 这类高度并行 workload 或 Masstree 这类写多、内存压力大的场景下，检测率会下滑。最后，Orthrus 能做的是检测并可选地在 strict safe mode 下延迟对外可见操作，但它本身并不负责恢复已损坏状态。

## 相关工作

- _Hochschild et al. (HotOS '21)_ - “Cores that don't count” 记录了生产环境中部署后 CPU 错误的现实存在；Orthrus 则把这种 fleet-level 观察转成了 application-level 在线防护。
- _Ngo et al. (OSDI '20)_ - Copilots 通过协调 replica 来验证 replicated state machine 的执行，而 Orthrus 只验证 data-path closure，并借助版本化共享内存避免全局副本同步。
- _Fiala et al. (SC '12)_ - 面向 HPC 的 SDC 检测与纠错依赖冗余和 checkpointing；Orthrus 的目标则是持续在线运行的云服务及其用户数据完整性。
- _Mukherjee et al. (ISCA '02)_ - 冗余多线程在指令粒度上做验证，保证更强但硬件与运行时成本更高；Orthrus 退到 closure 粒度以换取在通用云环境中的可部署性。

## 我的笔记

<!-- 留空；由人工补充 -->
