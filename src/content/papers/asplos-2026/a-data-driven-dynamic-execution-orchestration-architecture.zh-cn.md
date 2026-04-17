---
title: "A Data-Driven Dynamic Execution Orchestration Architecture"
oneline: "Canon 用编译器生成的 FSM 协调器和 time-lapsed SIMD，让同一片空间阵列按输入元数据重排执行，在稀疏与稠密内核上都逼近专用加速器。"
authors:
  - "Zhenyu Bai"
  - "Pranav Dangi"
  - "Rohan Juneja"
  - "Zhaoying Li"
  - "Zhanglu Yan"
  - "Huiying Lan"
  - "Tulika Mitra"
affiliations:
  - "School of Computing, National University of Singapore, Singapore"
  - "Lumai Ltd., Oxford, UK"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762226"
tags:
  - hardware
  - compilers
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Canon 的核心主张是，可编程加速器不必在“硬连线所以快”和“够灵活但容易脆弱”之间二选一。它把编译器生成的 FSM 协调器与 time-lapsed SIMD 的 PE 阵列结合起来：规则部分静态映射，稀疏或不规则事件再在运行时动态处理。结果是一种空间架构，既能在专用工作负载上逼近专用加速器，也能覆盖更广泛的稀疏、稠密和通用内核。

## 问题背景

论文瞄准的是一个很经典但一直没被真正解决好的权衡。领域专用加速器之所以快，是因为它们把计算和数据流直接烤进固定 datapath 里；但这种专用化也让它们在内核变化、输入模式变化时变得非常脆弱。CGRAs、FPGAs 和 GPU 则更灵活，可它们的控制开销、编译期决定的数据路由，以及对规则并行结构的依赖，会在执行受运行时稀疏性或不规则依赖影响时迅速掉效率。

稀疏张量内核把这个问题暴露得最明显。在 SpMM 和 SDDMM 里，硬件必须同时处理不规则内存访问、不同计算单元之间的不均衡工作量，以及 reduction 依赖造成的停顿。纯静态数据流没法根据输入及时调整，纯动态架构又要为控制、缓冲和 NoC 复杂度付出很高代价。于是，真正的问题变成：怎样保住空间加速器对“大部分规则执行”的高效率，同时只把动态控制预算花在真正不规则的那一小部分执行上。

## 核心洞察

Canon 最重要的洞察是，很多“不规则”工作负载其实并不是处处都不规则。高层数据流常常仍然足够稳定，可以静态放置；真正需要运行时判断的，是最后一公里的选择，例如某个稀疏元素是否存在、哪个 partial sum 应该被累加、某轮 reduction 应该继续还是绕过。只要把这些决定集中到一个轻量的协调器里，而不是在每个 PE 内部都塞进厚重控制逻辑，架构就能既保住效率，又不至于过度僵化。

time-lapsed SIMD 是这套思路的另一半。Canon 不是把一条指令同时广播给整行 PE，而是让指令波在多周期里沿着一行逐个传播。这样做把控制成本摊薄了，同时保持时间上的确定性：同一时刻不同 PE 可能处在同一指令流的不同阶段，但整行行为依旧足够可预测，因此同步和路由可以由阵列边缘的协调器来管理，而不必在每个 PE 里各自解决。

## 设计

Canon 是一个 2D mesh 的处理阵列。每个 PE 都有一个 4-lane vector lane、一个 router、本地 data memory 和一个小型双端口 scratchpad；每一行则配一个可编程 orchestrator。网络也被拆成两套：指令走专用 instruction NoC，数据走 circuit-switched NoC。这样的分离让计算阵列保持轻量，同时又能在运行时改写行为。

每个 PE 是一个三段流水（`LOAD`、`EXECUTE`、`COMMIT`）。指令只编码操作和操作数/结果地址，而 Canon 通过统一地址空间让同一格式同时指向寄存器、本地存储和路由动作。由于指令会以固定三周期偏移沿着一行传播，体系结构能得到一种确定性的“错峰复现”：前一个 PE 的计算、访存和通信行为，会在后续 PE 上按固定延迟重演。论文反复利用这一点，因为正是这种确定性，让“按行动态编排”变得足够便宜。

最有新意的是 orchestrator 本身。它是一个由编译器预编程的有限状态机，内部有 state register、state-meta registers，输入来自元数据流以及邻居 orchestrator 的消息。一个 LUT 支撑的可编程逻辑块会根据状态生成指令字段、地址、状态更新和输出消息。换句话说，它本质上是运行时的数据到指令翻译器：稀疏坐标、row-end 标记、上游 partial-sum 消息，都会触发不同的控制动作，而不需要在每个 PE 内部放一个通用控制处理器。

论文用两个稀疏内核展示这套机制怎么落地。对 SpMM，稀疏矩阵 `A` 的行以流的方式进入阵列，而稠密矩阵 `B` 的 tile 常驻在 PE 本地存储里；partial sum 沿列向下传播，scratchpad 负责暂存它们，使得某一行即便遇到上下游负载不均，也能继续推进。orchestrator 决定当前 PE 该继续做 MAC、累加一个传入 partial sum、把自己的结果 flush 给下游，还是干脆 bypass。对 SDDMM，mask 负责稀疏地激活计算，scratchpad 则被重新用作输入 `A` 向量的缓冲和复用。对规则内核，Canon 也能退化为更静态的空间执行模式；但作者也明确承认，编译器栈还没有完全自动化，目前仍需循环分析配合人工挑选映射。

## 实验评估

实验基于 `22nm` FDSOI 工艺下、目标频率 `1 GHz` 的综合结果，以及一个 cycle-accurate 模拟器。默认 Canon 配置是一个 `8 x 8` 的 INT8 阵列，每个 PE 带 `4`-lane SIMD、`4 KB` SRAM 和 `64 B` 双端口 scratchpad，整阵列有 8 个按行放置的 orchestrator，外部主存带宽为 `17 GB/s` LPDDR5x。基线覆盖了从高专用到高通用的几类架构：稠密 systolic array、支持 `2:4` 稀疏的 systolic array、ZeD 稀疏加速器，以及传统 CGRA。工作负载则包括 SpMM、非结构化和窗口化 SDDMM、PolyBench，以及 ResNet-50、LLaMA-8B、Mistral-7B 中的稀疏模型算子。

硬件成本并没有被掩盖。Canon 相比普通 systolic array 约多出 `30%` 面积，主要由 scratchpad、orchestrator 和 routing 带来；相比 ZeD 约大 `12%`，相比 CGRA 则反而节省约 `7%` 总面积。对纯稠密的 GEMM，这些灵活性几乎没有额外收益，因此 systolic 仍然在 perf/W 上略优，Canon 的控制和路由只带来不到 `13%` 的功耗额外开销。但一旦进入稀疏场景，传统稠密 systolic 因为无法吃到输入模式带来的好处，吞吐最低会掉到 Canon 的 `0.3x` 以下。

更有价值的结果是，Canon 往往能靠近“最强专才”，却不被锁死在单一模式里。它在 GEMM 上能贴近普通 systolic，在 `2:4` 稀疏 SpMM 上也能接近专门改造的 `2:4` systolic；对非结构化稀疏任务，它在较稠密的稀疏区间内与 ZeD 的差距控制在 `8%` 以内，而在更高稀疏度和部分输入上还能反超，最高约 `5%`。论文还声称 Canon 在窗口化 SDDMM 上优于所有基线。对“负载均衡机制真的有效吗”这个问题，文中也给了比较硬的证据：当稀疏度高于 `60%` 时，`16` 项 scratchpad 深度相比单项缓冲能把利用率提升 `10-20%`；若编译期已知大致稀疏区间，再去调节有效 scratchpad 范围，还能平均再拿到 `5%` 提升。整体来看，这组实验相当支持作者的主张：Canon 确实是在用有限、可量化的固定硬件溢价，去换取跨内核和跨稀疏模式时明显更低的性能脆弱性。不过需要注意，很多关键比较仍然是归一化图，而不是绝对吞吐表。

## 创新性与影响

和 _Dangi et al. (PACT '24)_ 这类专用稀疏加速器相比，Canon 的创新点不在新的稀疏 datapath，而在于重新划分编译期与运行时的职责。和典型 CGRA 相比，它的新意在于运行时重构不是通过停机重映射整个阵列完成，而是通过元数据驱动的 orchestrator 持续在线完成。和 dataflow-inspired 的通用处理器思路相比，它则把这种思想进一步推进到空间加速器里，让同一套机制同时统筹计算、路由和缓冲。

因此，Canon 的价值并不只在于把 SpMM 或 SDDMM 做快一点。对设计稀疏 ML 加速器、不规则 reduction 硬件、或者混合规则/不规则内核的研究者来说，这篇论文更像一套“怎样精准花控制预算”的架构模板，而不是一篇只优化单个算子的论文。

## 局限性

论文也相当坦率地承认，Canon 还不是一个开箱即用的平台。编译流程并不完整，全局最优 mapping 仍是开放问题，目前工作流依赖 polyhedral analysis 再加人工选择和微调数据流。这一点很重要，因为 Canon 的收益高度依赖映射质量，以及“某类不规则性该靠 NoC 吸收还是靠 scratchpad 吸收”的判断。

硬件本身也有清晰边界。低 DLP 的内核会吃不满 4-lane SIMD，作者也报告说某些低并行度的 PolyBench BLAS solver 更适合 CGRA。随着 arithmetic intensity 下降，off-chip bandwidth 压力会明显上升；在 `95%` 稀疏度下，Canon 可能需要大约 `7x` 带宽，但只换来约 `16x` 的等价稠密吞吐。最后，论文证据主要来自综合和模拟，而不是带完整软件栈的硅实现，所以真实集成成本和可编程性代价仍有一部分尚未完全落地。

## 相关工作

- _Dangi et al. (PACT '24)_ — ZeD 是面向可变稀疏矩阵计算的专用加速器，而 Canon 试图在支持更多内核和更多稀疏结构的同时，把效率拉回到同一量级。
- _Nguyen and Sanchez (MICRO '21)_ — Fifer 通过把不规则内核拆成规则阶段并用队列连接来处理 irregularity；Canon 则把决策留在单一 fabric 内，通过 orchestrator 驱动的在线执行完成。
- _Wang and Kim (ASPLOS '21)_ — DiAG 用 dataflow 思路改造通用处理器，而 Canon 把运行时数据驱动编排推到了面向高吞吐的空间 PE mesh 上。
- _Qin et al. (HPCA '20)_ — SIGMA 面向 sparse and irregular GEMM 设计了灵活互连，但 Canon 的目标是把这种适应性推广到更宽的可编程架构，而不只是一类稀疏内核。

## 我的笔记

<!-- 留空；由人工补充 -->
