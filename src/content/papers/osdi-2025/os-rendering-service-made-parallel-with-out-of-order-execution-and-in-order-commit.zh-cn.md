---
title: "OS Rendering Service Made Parallel With Out-of-Order Execution and In-Order Commit"
oneline: "Spars 把顺序式 OS rendering 拆成自包含任务，按乱序执行、按需顺序提交，从而提升折叠屏与多屏设备的帧率。"
authors:
  - "Yuanpei Wu"
  - "Dong Du"
  - "Chao Xu"
  - "Yubin Xia"
  - "Yang Yu"
  - "Ming Fu"
  - "Binyu Zang"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Engineering Research Center for Domain-specific Operating Systems, Ministry of Education"
  - "Fields Lab, Huawei Central Software Institute"
conference: osdi-2025
code_url: "https://github.com/SJTU-IPADS/Spars-artifacts"
tags:
  - scheduling
  - gpu
  - energy
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Spars 是一个面向智能设备 GUI 的并行 OS rendering service，与之配套的是 Spade2D drawing engine。它的关键做法是保留一次很快的顺序 dry run 来计算完整绘制状态，把生成的自包含 rendering task 交给多个 worker 乱序执行，再只在存在重叠约束时按顺序提交。

## 问题背景

这篇论文要解决的瓶颈，来自手机和嵌入式设备从单屏走向折叠屏、三折屏以及 one-chip multi-screen 之后的现实压力。设备每帧需要处理的像素与图元明显增多，但 iOS、OpenHarmony 这类系统里的 rendering service 仍主要围绕 render tree 的顺序 depth-first 遍历组织。作者说明，这种设计之所以开始失效，是因为 2D 场景里的瓶颈主要不在 GPU rasterization，而在 CPU 侧的准备工作；他们测得平均 82% 的端到端 frame rendering time 都花在 CPU 上。

这种顺序性并不是偶然的工程习惯。Render-tree 节点只保存相对父节点的状态，因此 renderer 通常必须做 depth-first traversal 才能恢复绝对的 transform 和 clipping。与此同时，绘制顺序本身又有语义：前景与背景图元一旦重叠，就不能交换顺序。再往下，生产级 2D engine 还暴露 stateful API，并依赖 command batching 这类 stateful optimization。现有的粗粒度方案并不能真正解决问题。Inter-frame parallelism 会把整帧做成流水线，但会增加 latency，也受制于最慢阶段；multi-window parallelism 只有在窗口很多时才有意义，而且会引入额外 buffer 与 composition 开销。作者在 Mate X5 上观察到，render thread 会把一个 core 顶到约 80% 利用率，而其余大多数 core 仍基本闲置。

## 核心洞察

论文最重要的判断是：OS rendering 实际上比它当前的实现方式更适合并行，因为真正制造大部分依赖的并不是“执行 draw command”本身，而是“恢复绘制状态”和“维持输出顺序”。如果 renderer 先做一次廉价的顺序 preparation，把相对状态解开为每个任务独立完整的 drawing state，那么真正昂贵的 CPU 工作，也就是把图元翻译成 GPU object 的过程，就可以在多个核心上独立并发。

第二个洞察是，正确性并不要求保留完整的顺序遍历，只要求保留由 overlap 引出的 partial order。Spars 因此非常认真地借用了标题里的处理器类比：先按序准备任务，再乱序执行，最后只在需要的地方按序提交。这个思路之所以成立，是因为 Vulkan 这类现代 GPU API 本身已经大体是 stateless 的，于是 stateful 的兼容层可以从真正的并行执行内核中被分离出来。

## 设计

Spars 把 rendering 分成三个阶段。第一阶段是 in-order preparation。主线程仍然 depth-first 遍历 render tree，但这次遍历只是 dry run：它为真正包含 draw command 的节点计算绝对 transform、clipping、primitive parameter 和 style，再把这些信息打包成自包含任务。未变化的绝对状态可以跨 frame 复用。作者指出，draw command 在树里其实很稀疏；在一个 desktop 场景中，800 个节点里只有大约 200 个真正携带 draw command，而保存这些绝对状态额外只增加约 2 MB 内存。

Preparation 阶段还负责为正确性和优化准备元数据。Spars 不去构造完整依赖 DAG，而是保留一条从 depth-first 顺序导出的简单任务链，并为每个任务记录 axis-aligned bounding box。这样 commit 阶段就能判断两个未完成任务是否可能彼此影响。同一个 pass 还保留了传统 stateful optimization 里最有价值的部分，也就是 command batching：如果相邻命令能共享同一条 GPU pipeline，它们就会被合并，因此 Spade2D 经常接收到的是一批 rectangle 等图元，而不是单个 primitive。

第二阶段是 worker thread 上的 out-of-order execution。每个 worker 从 single-producer/multi-consumer 队列中取任务，并调用 stateless 的 Spade2D，把任务翻译成 mesh、texture、pipeline 等 GPU object。Spade2D 的内部围绕 thread-safe resource manager 组织，因为并行 rendering 否则很容易把同一张 image 或同一个 pipeline 创建两次。资源因此会处于 unprepared、preparing、prepared 三种状态：第一个任务负责原子地标记并真正创建资源，后续竞争者只在 condition variable 上短暂等待，而不会重复工作。由于现代 GPU API 支持并行创建和使用许多对象，论文认为这部分锁竞争很有限，也基本不在关键路径上。

第三阶段是 commit thread 的 in-order commit。它从 multi-producer/single-consumer 队列中收集已完成任务的输出；如果任务正好位于链头，或者它之前所有未完成任务都与它的 AABB 不重叠，就立即提交。否则它会等待必要的背景任务先完成。这正是论文里最重要的 control path / data path 分离：主线程负责恢复状态和做 batching 决策，worker 线程负责 CPU 最重的 geometry 与 GPU-object 生成，而 commit 线程只在最后串行化真正还需要保留的顺序约束。

## 实验评估

实验设计的优点在于，它尽量把“并行架构本身”的收益单独隔离出来。作者用 C++ 和 Vulkan 实现了 Spars 与 Spade2D，从 OpenHarmony 真实场景导出 render tree，然后同时对比 commercial renderer，以及一个保持同样代码结构、但使用传统串行流程的 Sequential 版本。对 Mate 70、Mate X5、Mate XT 上的 42 个代表性 smartphone 场景，Spars 中有 76% 的 frame time 可并行，按 Amdahl's Law 估算，3 个 worker 的理论上限是 2.14x，5 个 worker 是 2.65x。

真实收益虽然低于理论上限，但仍然相当可观。把 5 个 worker 固定在 medium core 上时，Spars 相比 Sequential 可把 CPU frame-rendering time 降低 43.2%，平均 frame rate 提升 1.76x；42 个 smartphone 场景中有 27 个顺序基线无法稳定维持 120 Hz，而 Spars-5 全部可以做到。在更重的 multi-window 与 picture-in-picture 场景下，提升最高达到 2.07x。对 one-chip multi-screen 配置，平均 frame-rate 提升达到 1.91x，在屏幕数量最多的场景里甚至超过 2x。

这些次级结果也支撑了论文的系统论点，而不只是 benchmark 叙事。更均衡的多核利用使整机功耗在相同 frame rate 下下降 3.0%；若固定 120 Hz 时间预算，Spars-5 可以比顺序基线多渲染 2.31x 的随机图元。实验在公平性上做得不错，因为 core 和 clock 都被控制，而且顺序基线来自同一套代码；但它还不是一个完全生产化的 drop-in 替换：Spars 目前是绕过原生 renderer 运行，并通过导出的 render tree 来重建工作负载。

## 创新性与影响

这篇论文的新意，在于它是在 rendering-service 层面做“单帧内部”的并行化，而不是依赖整帧流水线或多窗口这类更粗粒度的机会。相对于 _Wu et al. (ASPLOS '25)_ 的 D-VSync，后者利用 rendering/display 解耦后的 slack 去吸收波动负载，而 Spars 是直接重构 rendering engine，使其在持续重负载下也能动用更多核心。相对于那些试图把更多工作推给 GPU 的 mobile 或 graphics 系统，Spars 接受了 2D GUI rendering 仍然高度 CPU-heavy 这一事实，并正面攻击 CPU 侧的依赖结构。

因此，它的贡献更像是一种体系结构重组，而不只是某个局部算法。构建 mobile OS、cockpit software stack、或者大屏设备 graphics middleware 的读者很可能会引用它，因为它给出了一个不依赖更强单核性能的 rendering scalability 路径。更深的启示是：未来的 OS rendering service 应该围绕显式的 state untangling 和 order-preserving commit 来设计，而不是继续把一切塞进一条长长的 stateful traversal 里。

## 局限性

Spars 不是小修小补。作者明确把它描述成对 rendering service 与 drawing engine 的完整重构，并估计要做到功能完整的部署，需要修改传统栈中超过三分之一的代码。即便内存开销并不致命，也并非没有代价：thread creation 是主要来源，Spars-5 在现代设备上最多会增加约 50 MB 额外内存，不过论文认为这对 8 GB 以上内存的设备仍属可接受范围。

实验与部署层面也存在边界。Spade2D 目前仍缺少一些原生 renderer 已有的特性，这也是作者采用“导出 render tree 后重建负载”而不是直接替换日常系统 renderer 的原因。该设计在任务丰富、图元多的场景下收益最大；对于更轻的页面和较小的屏幕，收益会更有限。最后，动态调节 worker 数量的问题仍未解决，而 commit 策略采用的是有界 AABB 检查而非更完整的依赖图，这个工程选择很务实，但也可能放弃一部分潜在并行度。

## 相关工作

- _Wu et al. (ASPLOS '25)_ — D-VSync 同样面向 smartphone graphics，但它利用 display/render 解耦后的 slack，而不是并行化 rendering core 本身。
- _Arnau et al. (PACT '13)_ — Parallel frame rendering 在 mobile GPU 上流水化整帧，而 Spars 挖掘的是单帧内部并行度，从而避免 inter-frame staging 带来的额外 latency。
- _Chen et al. (LCTES '22)_ — DSA 扩展了 Android 的 dual-screen 应用模型，而 Spars 解决的是更底层、由大屏与多屏硬件暴露出来的 rendering-service 瓶颈。
- _Yun et al. (WWW '17)_ — Presto 通过放松 display stack 中的 synchrony 来降低交互延迟，这与 Spars 重构 render-tree 执行路径是正交思路。

## 我的笔记

<!-- 留空；由人工补充 -->
