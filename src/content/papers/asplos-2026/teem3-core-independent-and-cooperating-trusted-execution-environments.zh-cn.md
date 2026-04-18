---
title: "TeeM3: Core-Independent and Cooperating Trusted Execution Environments"
oneline: "把 TEE 隔离从 CPU 模式移到每个 tile 的 TCU 上，用独占内存区、锁定通道和 RoT 让 CPU 与加速器 TEE 能安全协作。"
authors:
  - "Nils Asmussen"
  - "Sebastian Haas"
  - "Carsten Weinhold"
  - "Nicholas Gordon"
  - "Stephan Gerhold"
  - "Friedrich Pauls"
  - "Nilanjana Das"
  - "Michael Roitzsch"
affiliations:
  - "Barkhausen Institut, Dresden, Germany"
  - "TU Dresden, Dresden, Germany"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790232"
code_url: "https://github.com/Barkhausen-Institut/M3-Bench"
tags:
  - confidential-computing
  - security
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TeeM3 的核心主张是，面向异构系统的 TEE 不该继续做成某种 CPU 特权模式。它把隔离能力放进 tile 级别的通信控制器里，再配上独占内存区、可锁定的通信通道、小型 root of trust 和 bare-metal 运行时，让通用 CPU tile 与加速器 tile 上的 TEE 能在统一模型下协作。作者在 FPGA 原型上的结果表明，这样做的运行时开销较低，同时相对标准 M3 把硬件 TCB 缩小了 `1.8x`，软件 TCB 缩小了 `3.42x`。

## 问题背景

这篇论文抓住的是一个越来越现实的矛盾：真实工作负载已经跨越 CPU、加速器、内存和 I/O 设备，但主流 TEE 仍主要绑定在某一种处理器架构上。对于工业控制、车载设备或 IoT 终端这类系统，数据路径可能先由传感器采集，再交给加速器预处理，最后由 CPU 负责加密和联网。只保护 CPU 而不保护加速器，TEE 边界就会在最关键的地方断开；如果再额外给每种加速器各做一套 TEE，又会把系统复杂度和信任链条迅速推高。

作者认为，现有 TEE 的第二个结构性问题是“把安全性绑在复杂核心内部”。当 TEE 被实现为处理器里的特殊执行模式时，它不可避免地与别的软件共享微架构状态，也就继承了大量 side channel 风险。论文回顾了多类攻击，说明这种设计不仅让应用 TEE 容易泄密，连 RoT 的签名密钥都可能受影响。再加上许多现有方案依赖封闭固件、微码或特定 ISA，系统设计者几乎无法真正审计或替换这些关键部件。

作者所基于的 M3 平台虽然已经有按 tile 隔离的硬件/操作系统协同设计，但还不能直接当作 TEE。M3 内核可以重配所有 TCU，父服务仍然拥有子活动的初始资源，TileMux 在装载应用时会持续改变自身状态，而内核又必须保留回收失控 tile 的能力。于是论文把问题明确成四个挑战：如何把内核移出机密性与完整性的 TCB，如何让 TEE 真正独占自己的资源，如何在不重新信任内核的前提下保留资源回收能力，以及如何让远程证明时要测量的状态足够稳定、可预测。

## 核心洞察

这篇论文最值得记住的命题是：异构 TEE 之所以难，不是因为 CPU 和加速器本质上不同，而是因为隔离机制被放错了位置。只要把隔离从“某个核心内部的特殊模式”改成“每个 tile 外侧都有一个统一的硬件执法点”，CPU、加速器、甚至 RoT tile 就都能被放进同一个安全模型里。TeeM3 选择的执法点是 TCU，因为跨 tile 的内存访问与消息传递本来就要经过它。

但单有“外置执法点”还不够，关键在于要给 TEE 两种真正的所有权。第一种是独占内存所有权，保证内核、loader、pager 之类的上层服务不再天然拥有 TEE 的内存访问权。第二种是通信控制所有权，保证内核无法在 TEE 运行后把已有通道偷偷改线、插入中间人或把旧通道接到新进程上。作者的判断是，只要这两类所有权成立，操作系统就可以降级为 remote system software：它负责装载、配置和可用性，但不再默认参与机密性与完整性。

## 设计

TeeM3 对 TCU 的第一项扩展是 exclusive memory regions。与 M3 主要在“发送方”控制访问不同，TeeM3 把一部分授权信息放到“接收方” TCU 中。每个 TCU 可以登记多个按 2 的幂大小、按大小对齐的独占区域；任意传入的内存请求若命中这些区域，就必须额外通过 owner tile ID 检查。这样，某个 TEE 的私有 DRAM 区域或加速器本地 SPM 就不再因为内核或父服务曾经参与装载而默认对它们可见。更重要的是，这套机制也支持 cooperating TEEs：只要 RoT 允许，就能把特定区域共享给少数协作 tile，而不是对全系统开放。

第二项关键机制是 tile locking。TEE 把自己的 lock bit 打开后，内核不能再直接改写该 tile 的 endpoint 配置，但 TeeM3 又没有把系统做成完全静态。它采用 propose-freeze-accept 协议：内核若想改 endpoint，会先把它冻结并写入“提议配置”；TEE 自己检查这个配置，确认无误后用新的 TCU unfreeze 命令解冻。这样做既保住了动态建链能力，也把最终控制权留在 TEE 一侧。为防止内核通过 reset 旧 tile、复用旧通道的方式偷换通信对象，作者还给每个 TCU 加了 generation counter；通道两端若发现代数不匹配，就直接判定失效。

软件层面，作者没有继续沿用 TileMux，而是把它替换为一个更小的 Rust 库 UniMux。UniMux 只支持单 activity、单地址空间、eager mapping，并拒绝内核发来的页表修改请求。这样做一方面绕开了“运行时本身还在变动，却又必须被测量”的自指问题，另一方面也把 TEE 运行时收缩成更像 unikernel 的形态。TEE 因而可以 bare-metal 跑在 tile 上，同时仍通过 TCU 协议访问文件系统、pager 等 OS 服务。

最后是专门的 RoT tile。它带有 boot ROM、多阶段固件、SHA-3 加速器和 remote attestation service。RoT 先测量后续固件阶段并派生证明密钥，再测量内核与基础服务，最后锁定自己并对外提供 RAS。RAS 还负责管理独占区域：记录区域是否已 closed、只在拥有者 tile 代数增加后才允许内核删除区域，并在最后一个 sharer 离开时清零内存。这样，区域生命周期本身也被纳入证明链条，而不是由不可信内核私下决定。

## 实验评估

实验平台是作者基于 AMD Xilinx VCU118 FPGA 做出的完整原型，而不是只在模拟器里验证概念。系统包含 8 个处理 tile、2 个内存 tile、2x2 star-mesh NoC，用户 tile 上使用 Rocket 与 BOOM RISC-V 核心，RoT 和 AES 加速器 tile 上使用 PicoRV32。这个设置很重要，因为 TeeM3 的卖点就是“同一底座上既能跑通用核心 TEE，也能跑加速器 TEE”，实验确实覆盖了这两类路径。

底层开销结果基本支持论文的主张。通信端点创建在 TEE 下的额外开销低于 `4%`，而 steady-state 通信几乎没有额外代价，因为 TCU 通道直接绕过内核，不需要像 SGX 或 TDX 那样在每次跨边界时做 enclave exit 或额外加密。独占区域检查对 DRAM 密集访问的影响也很小：即使 `16` 个 region 全部启用，最坏 slowdown 仍低于 `1.5%`。原因是 DRAM 本来就慢，检查可以与离片访问并行进行。真正明显的代价出现在片上 SPM，这里最坏 slowdown 约为 `20%`，说明对极低延迟本地存储而言，保护逻辑确实不是零成本。

更能体现系统意义的是加速器与应用级实验。无论是通过 AES tile 进行文件流式加密、通过 RoT 的 SHA-3 单元做文件哈希，还是模拟 IoT 场景中“先加密再哈希”的异构流水线，TEE 版本的额外开销都低于 `5%`，主要来自 lock / unlock、exclusive region 配置和 RAS 调用。LevelDB 在作者的工作负载下作为 TEE 运行时则没有可测的 slowdown。硬件与 TCB 结果也很关键：为 TCU 增加 TEE 支持大约让其 LUT 增加 `19%`、FF 增加 `27%`，但相对标准 M3，TeeM3 仍把机密性/完整性相关硬件 TCB 缩小到 `1.8x`，并把软件 TCB 从 `248,308` 条 RISC-V 指令降到 `72,587`。这些证据最能说明它在 M3 式 tile 架构上的价值；至于通用商用 SoC，论文还没有给出直接数据。

## 创新性与影响

和 SGX、TDX、Keystone 这类把 TEE 做在处理器内部的方案相比，TeeM3 最核心的新意是把执法点移到核心之外，并把它统一成每个 tile 都有的机制。和 CURE、HECTOR-V 这些更接近的学术系统相比，TeeM3 的关键区别在于它把 heterogeneous cooperation 做成了第一等能力：通用核心 tile、加速器 tile 与 RoT tile 都复用同一种 TCU 执法模型，同时仍能访问远端 OS 服务。再加上作者系统化地量化了硬件面积、软件复杂度与 TCB 缩减，这篇论文不只是“又一个 TEE”，而是在给异构平台上的 TEE 设计重新划边界。

我认为它最可能影响的是做工业控制、边缘设备和可信嵌入式平台的人，以及研究异构 confidential computing 的系统作者。它提出的是一条很明确的设计路线：如果未来系统天然由多种处理单元组成，那么 TEE 也必须从“每种核心各自封装”走向“平台级统一隔离底座”。

## 局限性

TeeM3 并没有消灭内核的影响，而是把内核留在 availability TCB 中。恶意内核仍可以冻结 endpoint、拒绝创建通道、频繁 reset tile，或者通过垃圾消息与调度干扰制造 DoS。论文也明确假设 TCU 与 NoC 本身可信，并把 timing attack、power side channel、rowhammer、NoC/DRAM 争用侧信道等问题留在范围之外；若没有额外的 SoC 边界内存加密或完整性保护，这些风险并不会自动消失。

另一个实际限制是“一 tile 一 TEE”。作者直说，如果同一 tile 内跑多个 TEE，TCU 就难以再保证消息真正送达哪一个 TEE，也难以证明某块内存只属于其中之一。消息传递本身也故意不像内存访问那样强限制，TEE 需要根据不可伪造的 sender tile ID 自己过滤意外消息。最后，这整套设计建立在 M3 和自定义 FPGA 原型之上，所以它已经是完整系统论文，但还不是“主流商用多核 SoC 可以低成本采纳”的证据。

## 相关工作

- _Lee et al. (EuroSys '20)_ - Keystone 仍把 TEE 支撑建立在 CPU 固件与 security monitor 上，而 TeeM3 把执法点外移到对不同处理单元都一致的 tile 级机制。
- _Bahmani et al. (USENIX Security '21)_ - CURE 也尝试把部分保护逻辑放到核心外，但 TeeM3 更强调异构 TEE 协作，并报告了比 CURE 更小的机密性/完整性硬件 TCB。
- _Nasahl et al. (AsiaCCS '21)_ - HECTOR-V 在结构上更接近，但 TeeM3 认为自己更灵活，因为通用 TEE 与加速器都能通过同一套 TCU 抽象访问 OS 服务并建立协作。
- _Tang et al. (ASPLOS '19)_ - HIX 关注的是 CPU-GPU 这一类专用组合的安全执行，而 TeeM3 追求的是任意加速器与其他 tile 都可复用的统一执法模型。

## 我的笔记

<!-- empty; left for the human reader -->
