---
title: "When P4 Meets Run-to-completion Architecture"
oneline: "P4RTC 把 P4 带到 RTC ASIC：它加入后台 pipeline、数据面表项操作和负载感知编译，使 50M 流精确监控能接近线速运行。"
authors:
  - "Hao Zheng"
  - "Xin Yan"
  - "Wenbo Li"
  - "Jiaqi Zheng"
  - "Xiaoliang Wang"
  - "Qingqing Zhao"
  - "Luyou He"
  - "Xiaofei Lai"
  - "Feng Gao"
  - "Fuguang Huang"
  - "Wanchun Dou"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University, China"
  - "Huawei, China"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
tags:
  - networking
  - smartnic
  - compilers
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`P4RTC` 讨论的不是某个局部 extern，而是一个更大的问题：如果 `P4` 的目标不再是固定 pipeline 交换机，而是高性能 run-to-completion (RTC) ASIC，会发生什么？论文给出的答案是一套完整栈：新的 RTC 架构模型、支持后台任务和数据面表项更新的 extern、面向 RTC 的编译器，以及一个 SystemC 性能模型。在一颗 1.2 Tbps 的 Huawei 芯片上，这套方案既能把精确 50M 流监控做到接近线速，也能显著降低开发负担，并把一个案例程序从 39.4 Mpps 优化到 569.5 Mpps。

## 问题背景

论文首先指出，当前 `P4` 生态的问题不只是“语言不够强”，而是“主流硬件目标过于单一”。今天大多数 `P4` 系统默认面向 pipeline ASIC：数据包依次穿过固定 stage，每个 stage 拥有隔离的本地存储。这种结构为了高吞吐牺牲了可编程性。很多现实算法要么根本写不出来，要么只能依靠 recirculation、近似化或者额外折中。论文举的代表性例子是“更新多个计数器中的最小值”：在 pipeline 芯片上，一旦包离开存放最小值的 stage，就很难再次访问那个状态。

看起来最直接的替代方案是 RTC 硬件，因为 RTC 可以让同一个包执行更长的逻辑，并反复访问共享内存。但现有高性能 RTC 平台往往只能通过私有的 C 风格接口或 microcode 编程，开发者必须直接面对硬件细节，研究界也很难复用已有 `P4` 代码。已有把 `P4` 迁移到 CPU 的工作也帮不上这个忙，因为它们并不面向 Tbps 级专用 RTC 包处理器。真正缺失的，是一层公开的抽象：既保留 `P4` 的编程体验，又把 RTC 硬件真正暴露给 `P4` 程序员。

## 核心洞察

论文的核心判断是：`P4` core language 本身并不需要为了 RTC 重写，真正需要变化的是 target-specific architecture model。`P4RTC` 仍然保留 parser / ingress / egress / deparser 这些熟悉的编程块，但把它们从“物理 stage 串联的 pipeline”重新解释为“运行在许多 RTC core 上的逻辑 pipeline”。只要这一步成立，RTC 的额外能力就可以通过 extern 和 annotation 暴露出来，而不是去修改 `P4` 核心语法。

但这还不够。RTC 的灵活性会把性能问题从“固定上限”变成“共享资源竞争”。一个程序即使语义正确，也可能因为 bank 冲突、table-search engine 负载失衡或锁竞争而跑得很差。所以论文把“让 P4 适配 RTC”视为一个全栈问题：不仅要有语言抽象，还要有知道如何部署表、如何下沉到 microcode 的编译器，以及能够在部署前暴露瓶颈的性能模型。

## 设计

`P4RTC` 的新架构模型是这样的：包进入芯片后先被 dispatcher 分配给空闲 core，每个 core 在本地执行一个逻辑 `P4` pipeline；处理过程中，程序可以多次访问共享的片上或片外内存。这个模型和传统 pipeline 目标有三点本质差异。第一，它是 many-core，而不是单条物理 pipeline。第二，逻辑长度几乎不受 stage 数量限制，因为 core 执行的是 microcode。第三，它依赖共享内存子系统，而不是每个 stage 各自拥有隔离内存。

为了把这些能力变成 `P4` 可用抽象，论文设计了一组新的 extern。`Foreach` 允许后台 pipeline 遍历表项，而不必往 `P4` core language 里硬塞 `for` 语法。`Sleep` 用来控制后台 core 的触发频率。`Queue<T>` 支持前台和后台 pipeline 之间的并行安全通信，论文用它把结束流的通知从前台转给后台 aging 路径。`TableOperation` 允许数据面直接对表项做插入、删除和读取。`lastRowIndex()` 则把“刚刚命中的表项行号”暴露出来，方便把 counter、register 或 lock 挂到具体行上。对于跨 core 的 read-modify-write，系统提供 `Lock` extern 做同步。

表的组织方式也被扩展了。表既可以放在片上，也可以放在片外；既可以是 content addressing table (`CAT`)，也可以是 linear addressing table (`LAT`)；还可以通过 `@linear`、`@offchip(x4)` 之类的 annotation 指定布局。RTC 硬件允许把一张表切分到多个 memory bank 里，这有利于容量利用和负载均衡，但会消耗有限的 address-mapping entry。于是编译器把表部署建模成一个 ILP：既要满足每张表都放得下、bank 容量不超、mapping entry 数量不超，又要最小化最忙 bank 的负载。由于真实负载取决于工作负载，论文进一步叠加了 PGO，在部署后重新采样访问分布，再次求解部署。

代码生成部分同样体现了“先抽象、后落地”的思路。作者复用了 `P4C` 的前端和中端，但重写了后端，并在 `P4 IR` 与最终 microcode 之间插入 `Microcode IR`。这样做的好处是，像 `Foreach` 这种 RTC 特有控制流可以先在中间表示里展开成 loop、branch 和 action dispatch，再统一落到实际指令上，更容易检查依赖、顺序和目标约束。另一部分关键设计是性能模型。它基于 SystemC 建模 core、traffic manager、table-search engine、memory subsystem 与回压行为，不精确执行每个包的功能，而是重放功能仿真得到的概率化 microcode path，从而估计给定程序和流量下的吞吐、时延与部件利用率。

## 实验评估

原型运行在 Huawei NetEngine 8000 F1A-C 的 1.2 Tbps RTC 芯片上，带 8 GB HBM。第一个案例展示的是“可编程性到底换来了什么”。作者实现了精确 per-flow monitoring：用片外 flow measurement table 存流，用 `TableOperation` 在数据面插入新流项，再用后台 pipeline 完成 aging 和上报。结果是，在 4 GB 内存下系统可以跟踪最多 50M 并发流，并保持接近线速。与基于 Tofino 的 `TurboFlow` 相比，`P4RTC` 因为能在数据面直接处理哈希冲突，把上报带宽开销降低了 86% 到 90%；即使在并发创建流项时存在行锁竞争，失败包带宽也低于输入流量的 0.2%。

第二个案例关注开发效率。作者在五个项目上比较了 `P4RTC` 和 microcode 的代码量，包括精确流监控、`SpaceSaving`、`CocoSketch`、AES encryption 和 `ONTAS`。结果显示，`P4RTC` 版本的 LOC 比 microcode 少 4.6x 到 7.7x。更重要的是，对三个已有 `P4` 设计，迁移到 `P4RTC` 只需要修改 4.3% 到 13.0% 的代码，主要是替换 architecture-specific extern。这说明它不是另一个封闭 SDK，而是确实把已有 `P4` 资产带到了 RTC 硬件上。

第三个案例验证性能模型是否真能指导优化。作者从一个吞吐只有 39.4 Mpps 的基线程序出发，先根据模型做 table redeploy，把性能提升到 283.9 Mpps；再做 table-search-engine rebind，提升到 392.7 Mpps；最后把热点表项缓存到片上内存，提升到 569.5 Mpps。对应硬件实测分别是 38.3、279.4、401.9 和 561.0 Mpps，整体误差低于 3%。这足以支撑论文声称的优化工作流。不过评测本质上仍然是 case-oriented，并且只基于一类厂商芯片，而不是跨平台对比。

## 创新性与影响

这篇论文的新意不在单个 extern，也不只在一个 compiler pass。它真正贡献的是一套面向 RTC 硬件的 `P4` 栈：新的目标架构模型、暴露 RTC 能力的 extern、面向共享内存与 microcode 的编译器策略，以及部署前可用的性能模型。也正因为它把这些部分连成了一体，论文的主张才成立。

它的意义在于给后 pipeline-switch 时代的 `P4` 提供了一条具体路线。若这种思路被更多硬件采用，程序化数据面就不必继续被“固定 pipeline”这个默认前提绑死。像精确监控、更复杂的 in-network 算法、后台维护任务等过去难以在 `P4` 上自然表达的功能，都可能因此变得可实现。它既是新机制，也是在重新定义“`P4` target 应该是什么”这个问题。

## 局限性

论文对原型边界说得比较坦诚。当前实现仍然是厂商特定的，目标是 Huawei 的 RTC 芯片；更高吞吐芯片的适配仍在进行，`P4 Runtime` 也还只是计划中。语言层面也没有完全定型，作者明确提到内部已经根据应用需求加入了更多专用扩展，而 RTC 目标下到底该暴露哪些能力，还需要开放社区进一步讨论。

性能模型同样不是万能的。由于它重放的是概率化 code path，而不是逐细节复刻所有硬件交互，所以还无法刻画复杂锁行为，或者那些“包到达顺序本身决定性能与正确性”的场景。更广泛地说，RTC 的高可编程性也会带来新的性能陷阱。论文承认早期有些应用吞吐甚至不到 100 Gbps，开发者必须额外学习如何避免 bank 失衡、TSE 失衡和过度加锁。换句话说，`P4RTC` 扩大了能力边界，但并没有把 RTC 硬件变成 pipeline 那种天然确定、天然好调的目标。

## 相关工作

- _Bosshart et al. (SIGCOMM '13)_ - `RMT` 奠定了可编程 pipeline switch 的基础，而 `P4RTC` 认为当 stage 长度和隔离内存成为主要瓶颈时，需要把目标转向 RTC 硬件。
- _Hogan et al. (HotNets '20)_ - `P4ALL` 试图在 pipeline switch 内部提升表达力，而 `P4RTC` 直接改变目标架构，并用 extern 暴露 RTC 专属能力。
- _Yang et al. (SIGCOMM '22)_ - `Trio` 展示了可编程 RTC 芯片，而 `P4RTC` 补上了面向此类硬件的公开 `P4` 架构模型、编译经验和性能建模方法。
- _Salim et al. (EuroP4 '23)_ - `P4TC` 把 `P4` 带到 Linux traffic-control 栈，但它仍然保持 pipeline 视角，不包含 `P4RTC` 的 many-core RTC 模型和数据面表操作。

## 我的笔记

<!-- empty; left for the human reader -->
