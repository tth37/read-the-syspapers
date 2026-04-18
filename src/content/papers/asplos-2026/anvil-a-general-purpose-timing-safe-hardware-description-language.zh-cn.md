---
title: "Anvil: A General-Purpose Timing-Safe Hardware Description Language"
oneline: "Anvil 用事件参数化的时序契约和静态类型系统，让 RTL 设计者在保留动态延迟表达力的同时编译期排除 timing hazards。"
authors:
  - "Jason Zhijingcheng Yu"
  - "Aditya Ranjan Jha"
  - "Umang Mathur"
  - "Trevor E. Carlson"
  - "Prateek Saxena"
affiliations:
  - "Department of Computer Science, National University of Singapore, Singapore"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790125"
code_url: "https://github.com/kisp-nus/anvil"
tags:
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Anvil 是一种把“值在多长时间内必须保持不变”写进类型系统的 HDL，而不是把这件事留给设计者经验和仿真排查。它用事件参数化的 lifetime、register loan time 与接口 timing contract，静态检查值使用、寄存器更新和消息发送是否越界。因此它既能表达 cache、page table walker 这类动态延迟模块，又能在编译期拒绝 timing hazard。

## 问题背景

这篇论文瞄准的是 RTL 里一种非常常见、但长期缺少语言级抽象的错误：设计者希望某个信号在多个周期里持续有效，但驱动它的寄存器被过早修改了，或者消费者在值真正准备好之前就读取了它。在 SystemVerilog、VHDL 以及类似 HDL 中，signal 本质上是当前寄存器状态的函数，所以语言本身并不会直接表达“这个地址必须一直稳定到 memory 回复”为止，或者“这个输出只有在请求完成后才有意义”。作者把这类问题统一称为 timing hazards，其中既包括 stale read、错过请求、无效输出，也可能包括 TOCTOU 风格的硬件漏洞。

论文里的 memory 例子很能说明问题。客户端周期性地拉高 `req`、递增地址，并假定 memory 会在下一拍返回数据。如果真实 memory 需要两拍，客户端就会在上一个请求仍在处理中时改变地址，同时还会提前读取尚未准备好的输出。作者想强调的不是“设计者永远找不到这种 bug”，而是现有 RTL 语言让时序契约变成了跨模块、靠默契维持的隐式知识，因此非常容易被无意间破坏。

当然，也可以靠验证补救。断言、模型检查和仿真都可能发现这类问题，但作者认为那已经发生在设计完成之后了：反馈回路更长，需要额外写实现相关的 assertion，而且还会遇到状态爆炸。于是论文提出的核心问题是：能不能有一种 HDL，在保留 RTL 级别 cycle control 的同时支持动态延迟，并在语言层面静态排除 timing hazards？

## 核心洞察

论文最重要的命题是：只要 HDL 不仅跟踪“值是什么”，还跟踪“这个值在什么时间区间内保证不变”，timing safety 就可以被静态强制。Anvil 的做法不是只用固定 cycle count 描述时间，而是引入抽象事件。事件可以是静态的，比如“再过一拍”；也可以是动态的，比如“某个 channel message 被对端确认的时刻”。有了这些事件，编译器就能为每个值推导 lifetime，为每个寄存器推导 loan time，再检查值使用、寄存器修改和消息发送是否违反契约。

这件事的关键在于动态时序。像 Filament 那样的 timeline type 很适合固定延迟 pipeline，但难以自然表达 hit/miss 延迟不同的 cache 或 runtime 才知道响应时间的 page table walker。Anvil 的洞察是：真正该被类型化的不是“固定 N 个周期”，而是“从 `req` 到下一次 `res` 之间”这类事件关系。只要契约以事件为参数，就既能精确覆盖动态延迟，又仍然可以静态推理。

## 设计

Anvil 把模块建模为通过无状态双向 channel 通信的 process。发送和接收都是 blocking 的，因此一次 send/recv 配对天然定义了一个双方共享的同步事件。每种消息在 channel 定义中都带有 message contract：数据类型、何时过期，以及收发两侧的 sync mode。也就是说，接口时序不再只是文档里的口头约定，而是进入了编译器可检查的语言对象。

它的编程模型依然更像低层 RTL，而不是 HLS。process 里显式包含寄存器、channel 和并发线程；`loop` 表达重复行为，`recursive` 允许迭代之间流水化重叠；`recv`、`send`、`cycle N`、`t1 >> t2`、`t1; t2` 这些 term 则直接控制计算在什么时候发生、顺序执行还是并行执行。作者特别强调，Anvil 不是通过“隐藏寄存器和 wire”来规避问题，设计者仍然保留对 cycle-level timing 的完整控制权。

类型系统建立在三个抽象之上。第一，每个值都有 lifetime `[e_start, S_end)`，表示它从某个起始事件开始一直到某个结束事件模式之前都保证稳定。第二，只要某个值来自某个寄存器，而且该值被承诺在一段时间内持续有效，这个寄存器就在对应区间里被视为 loaned，不能被修改。第三，所有事件及其时序关系会形成一个 event graph，这是一张 DAG，记录“恰好一拍之后”“某个消息下次完成时刻”之类的关系；编译器再从图上导出 `<=_G` 之类的顺序关系和区间包含关系。

真正的安全检查有三类。其一，值使用必须完全落在它的 lifetime 里。其二，寄存器写入不能与任何 loan time 重叠。其三，消息发送必须保证被发送值在契约要求的整个区间内都保持 live，而且同一消息类型的连续发送不能让需要保持 live 的区间互相重叠。论文里的 Figure 5 很直观：不安全的 memory client 会在前一个请求契约尚未结束时改写地址，因此被拒绝；而安全版本改为等待动态的响应事件，再进行后续动作，于是可以通过类型检查。

实现方面，Anvil 编译器用 OCaml 编写，先做 type checking，再 lowering 到可综合的 SystemVerilog。event graph 同时扮演编译器 IR。编译器会在 code generation 前做一系列事件合并与 join 简化优化；lowering 时，只有在 sync mode 真正需要时才生成 `data`/`valid`/`ack` 形式的握手端口。因此 timing safety 的代价主要停留在编译期推理，而不是运行时硬件开销。

## 实验评估

这篇论文的实验问题设置很对路：Anvil 能不能表达真实硬件？它抓到的安全问题是不是有意义？生成 RTL 的综合开销有多大？作者实现了 10 个组件，包括 Common Cells 的 FIFO、passthrough stream FIFO、CVA6 的 TLB 与 page table walker、OpenTitan AES cipher core、AXI-Lite mux/demux router，以及两个拿来和 Filament baseline 比较的流水线设计。

表达力结果是最重要的一条主线。对所有 SystemVerilog baseline，Anvil 都保持了原始的 cycle latency，不管是简单 FIFO 还是像 CVA6 page table walker、AES core 这种动态延迟组件都没有额外拍数。Table 1 给出的平均综合开销相对手写 SystemVerilog 为 area `4.50%`、power `3.75%`，额外 cycle latency 为 `0`。具体看，PTW 的 area/power 开销分别是 `12%` 和 `4%`；两个 AXI-Lite router 的 area 开销是 `11-12%`；AES core 几乎没有 area 开销，但 power 高了 `22%`，作者把它归因于宽 datapath 上 bundled switching activity 的增加。对两个和 Filament baseline 比较的流水线设计，Anvil 平均 area 甚至更小（`-11.0%`），power 则高 `6.5%`，但 latency 同样不变。

安全性部分的数字没有那么多，但论证仍然有说服力。作者在复现实验中发现，Common Cells 的 stream FIFO 实际上并没有完全执行文档承诺的读写契约，而是主要依赖 warning assertion 和设计者自觉规避错误时序。Anvil 的价值恰恰就在这里：它把这类时序契约从“文档+经验”升级为接口的一部分，并在编译期强制执行。论文还在附录里列出了更多开源硬件中的同类例子，说明这不是为了论文刻意构造的玩具问题。

整体来看，实验较好地支撑了论文主张。benchmark 不是几个玩具算术 kernel，而是包含动态 memory management 逻辑和协议处理 router 的真实组件。比较欠缺的是更大规模子系统级别的采用故事，但对一个首版编译器原型来说，这样的覆盖面已经相当不错。

## 创新性与影响

相对 _Nigam et al. (PLDI '23)_，Anvil 的创新不只是把 timing contract 放到接口里，而是把它推广为以抽象事件为参数的动态契约。相对 HLS 风格语言，它的贡献在于不通过“抽掉时间”来回避 hazard，而是保留显式 cycle control 以及 register/signal 区分。相对以验证为中心的工作流，它的影响则在于把 timing safety 前移到写 RTL 的过程本身，让契约语言直接嵌入 HDL。

因此这篇论文会同时打动两类读者。对 PL 研究者而言，它展示了一个面向并发硬件、支持动态时序的非平凡类型系统。对硬件设计者而言，它提供了一个可信的论点：想要静态检查 timing hazard，并不一定要退回只能处理固定延迟 pipeline 的语言，或者接受过于软件化的抽象。如果这些想法被继续吸收进后续 HDL 设计中，它很可能会影响可复用 IP 的接口规范写法。

## 局限性

Anvil 证明的是一类特定 bug 的安全性，而不是完整的 RTL 正确性。它不声称能消除协议不匹配、deadlock、combinational loop 或与 lifetime 无关的功能错误。对于这些问题，设计者仍然需要传统验证手段。这一点很重要，因为否则读者容易把它误解为 RTL verification 的通用替代品。

它的编程模型本身也带来约束。通信需要被表述为基于 channel 的 blocking message passing，设计者还得把 timing contract 显式写到足够让类型系统推理的程度。为了换来安全性，这个代价是合理的，但对高度依赖临时共享 wire 或某些习惯性 SystemVerilog 写法的设计来说，迁移未必总是自然。

实现证据虽然已经很强，但仍然是研究原型级别。论文明确称编译器还是 early-stage prototype；实验覆盖的是 10 个模块，而不是完整 SoC；并且实现里对底层事件顺序关系使用了 sound approximation。它们不会推翻论文贡献，但意味着当前的 Anvil 更像一个非常有说服力的研究系统，而不是可以立刻替代成熟工业 HDL 的现成方案。

## 相关工作

- _Nigam et al. (PLDI '23)_ — Filament 是最直接的前作：它用 timeline type 实现 timing safety，而 Anvil 把这个思路扩展到事件参数化的动态 timing contract。
- _Majumder and Bondhugula (ASPLOS '23)_ — HIR 引入显式时间变量来描述 accelerator IR，但它抽象掉 lifetime，且只支持静态 timing behavior。
- _Han et al. (ASPLOS '23)_ — ShakeFlow 用 latency-insensitive interface combinator 处理 structural hazard，而 Anvil 面向的是通用 RTL 中共享值的 timing hazard。
- _Zagieboylo et al. (PLDI '22)_ — PDL 提升了 pipelined processor 的设计抽象层次，而 Anvil 的目标模块更广，并把 value lifetime safety 作为首要静态性质。

## 我的笔记

<!-- 留空；由人工补充 -->
