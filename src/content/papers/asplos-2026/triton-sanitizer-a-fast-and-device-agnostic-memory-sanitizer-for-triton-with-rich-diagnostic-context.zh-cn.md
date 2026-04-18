---
title: "Triton-Sanitizer: A Fast and Device-Agnostic Memory Sanitizer for Triton with Rich Diagnostic Context"
oneline: "Triton-Sanitizer 在 tile 语义层解释 Triton kernel，用 SMT 验证地址范围，并在间接访问时回退到 eager simulation。"
authors:
  - "Hao Wu"
  - "Qidong Zhao"
  - "Songqing Chen"
  - "Yang Chen"
  - "Yueming Hao"
  - "Tony CW Liu"
  - "Sijia Chen"
  - "Adnan Aziz"
  - "Keren Zhou"
affiliations:
  - "George Mason University, Fairfax, Virginia, USA"
  - "Google, Mountain View, USA"
  - "Anthropic, San Francisco, USA"
  - "Meta, Menlo Park, USA"
  - "OpenAI, San Francisco, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790241"
tags:
  - gpu
  - compilers
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文认为，Triton 的内存越界检查不该等到 PTX 或 LLVM IR 层再给每条访存指令打补丁，而应该直接在 Triton 的 tile 语义层完成。Triton-Sanitizer 通过符号化重建地址与 `mask` 表达式，用 Z3 判断在当前 launch 配置下是否存在真实越界，并只在间接访问打破纯符号推理时回退到 CPU 端 eager evaluation。这样做同时提升了诊断信息质量，并在论文评测的工作负载上取得了比厂商 sanitizer 更好的端到端成本。

## 问题背景

论文切入的是 Triton 生态里一个非常现实的缺口。Triton 已经成为深度学习 GPU kernel 开发的重要中间层：开发者可以用接近 Python 的 DSL 写出高性能 tile-oriented kernel，但内存访问错误仍然非常常见。作者从真实仓库里展示了两类典型 bug：一类是在 `tl.load` 或 `tl.store` 上完全漏掉 `mask`，另一类是写了一个“看起来合理”但实际上没有屏蔽掉所有非法索引的 `mask`。两种错误都会让 kernel 读写越过 tensor 的合法边界，最终造成 silent corruption、中间结果错误，甚至直接崩溃。

现有工具之所以不适合 Triton，论文给了三个理由。第一是效率问题。`compute-sanitizer` 和 GPU AddressSanitizer 一类方案都在更低层 IR 或二进制上为每次访存插入检查，这既拉高运行时开销，也可能让编译开销显著上升；而 Triton 的 JIT 特性又会在单个 workload 中生成大量 specialized kernel，使这个问题更严重。第二是可移植性问题。Triton 的意义之一就是面向多种 GPU 与 accelerator，而厂商 sanitizer 往往绑定某个后端。第三是诊断上下文太贫乏。低层工具最多告诉你某个地址非法、某一行出错，但通常说不清代码本来想访问哪个 tensor、哪个符号偏移量出了问题，以及这个 bug 是如何沿着 Python 调用链和 Triton 内部函数传播出来的。于是论文真正要解决的，不只是“能不能抓到越界”，而是“能不能以 Triton 原生的方式，在开发阶段可接受的成本下，给出足够能修 bug 的报告”。

## 核心洞察

这篇论文最值得记住的判断是：Triton 的 tile-oriented 编程模型恰好暴露了 sanitizer 最需要的结构。Triton kernel 的地址计算通常由一小组语义明确的操作构成，比如 `tl.program_id`、`tl.arange`、指针加法、broadcast、mask 以及有限的控制流。这些操作大多产生连续或规则 stride 的 tile，因此 sanitizer 往往不需要像低层工具那样逐个标量地址去检查，而是可以在 tile 粒度上推导一整个地址范围。

这带来的收益有两层。性能上，tile 级符号推理避免了对每次访存做 callback instrumentation，也绕过了大部分数值计算。可解释性上，同一份符号表达式既能证明访问安全，也能在不安全时解释“为什么”：它保留了 pointer provenance、`mask` 条件、生成错误偏移量的算术链条，以及触发问题的 Python/Triton 调用路径。论文的关键补充是 hybrid 机制：如果地址依赖于之前从内存里读出来的值，比如 jagged kernel 常见的间接访问，纯符号执行就不够了，这时 Triton-Sanitizer 暂时切到 CPU 端 eager evaluation 取回具体值，再继续后续的符号检查。

## 设计

Triton-Sanitizer 的工作方式，是在 Triton 进入正常“编译并 launch 到 GPU”流程之前把执行路径截住。用户可以通过 decorator、CLI 前缀或环境变量启用它。实现上，工具用 monkey patch 改写 Triton 的 kernel 入口和相关 operator，让一次 kernel 调用被重定向到 host 端解释器，而不是继续走 lowering、codegen 和 device execution。解释器会提取 launch grid、`tl.constexpr` 常量、运行时标量参数，以及 tensor 的 base address、shape、stride 等元数据；每个 tensor 都被包装成 `TensorHandle`，每个逻辑上的 Triton program instance 则在 host 上按顺序解释执行。

内部的核心表示是 `SymExpr` 树。每个节点记录操作类型、数据类型、常量值以及产生该值的子节点。当工具遇到 `tl.load` 或 `tl.store` 时，会自底向上遍历相关子树并将其翻译成 Z3 表达式。像 `tl.program_id` 和 `tl.arange` 这样的 range-initializing operator 会创建符号变量并附带取值域约束；普通算术操作负责组合这些范围；`tl.where` 被翻译成带路径敏感性的条件表达式；只改变形状而不改变底层字节范围的操作则可以直接忽略。如果地址或 `mask` 表达式里包含间接 `load`，Triton-Sanitizer 会把相关 tensor 拷到 CPU，一次性用 NumPy 对那段子表达式做 eager evaluation，恢复出具体值后再切回符号模式。

SMT 检查的形式化也很直接。对每个内存操作，工具构造地址公式 `A_o(x)`、掩码谓词 `M_o(x)`，以及覆盖当前 launch 中 program ID、循环迭代器和参数范围的域 `D(x)`；与此同时，它还会为每个 tensor 构造合法字节集合 `U`，对非连续布局则表示成多个连续切片的并集。之后交给 Z3 的问题就是：是否存在某个 `x`，使得 `D(x)` 为真、`mask` 为真、但 `A_o(x)` 落在 `U` 之外。若结果 `sat`，模型就是一个具体的越界见证；若结果 `unsat`，就说明该次 launch 下这次访问可以被证明为 in-bounds。发现错误后，诊断报告会指明目标 tensor、打印它的元数据和合法地址范围、把 faulting address 映射回 tensor offset、展示过滤过的 host 与 kernel 调用栈，并附上一棵带中间值的符号回溯树。为了控制开销，作者还加了四层缓存：SymExpr 到 Z3 的 memoization、循环迭代器缓存、每次 launch 复用的 solver `push`/`pop`，以及按函数指针、grid、tensor metadata 和参数组成的 kernel cache。

## 实验评估

评测分成两部分：真实 Triton 代码中的找 bug 能力，以及与现有 sanitizer 的开销对比。作者从七个广泛使用的开源仓库中收集了 112 个 Triton kernel，最终发现了 24 个此前未知的内存访问错误，其中 8 个修复已经被上游接受。错误类型包括 host 端分配大小与 kernel 预期不一致的 shape mismatch、缺失或错误的 `mask`，以及由于错误 alignment hint 引入的 misaligned access。论文还强调了一个很重要的能力：如果某次越界刚好落进了“另一个合法分配”的地址范围，传统工具可能把它当成合法访问，而 Triton-Sanitizer 能沿着 `addptr` 链回溯 pointer provenance，把访问归因到本来 intended 的 tensor 上，因此仍然会报错。

性能结果有一点细微但很有说服力。在 NVIDIA RTX 4090 上，Triton-Sanitizer 的端到端 normalized overhead 是 `0.86x-0.95x`，而 `compute-sanitizer` 在相同工作负载上是 `1.36x-1.59x`。论文甚至指出，Triton-Sanitizer 在不少场景下比“完全不加 sanitizer”的 baseline 还快，因为它直接绕过了 GPU 编译与 launch 流程，并在符号解释时跳过了大部分数值计算。在 AMD MI250x 上，启用两类 cache 后，Triton-Sanitizer 的平均开销是 `0.89x`，而 AddressSanitizer 是 `3.05x`。但 kernel-only 数字也揭示了真实权衡：Triton-Sanitizer 在 NVIDIA 上大约是 `10.22x`，在 AMD 上是 `10.11x`；相比之下，`compute-sanitizer` 在 NVIDIA 上达到 `34.06x`，而 LLVM 内联检查式的 AddressSanitizer 在 AMD 上只有 `2.10x`。作者给出的解释是成立的：Triton-Sanitizer 的优势主要来自端到端地避开 recompilation 与框架级 instrument，而不是说明符号检查在任何局部都更便宜。最后，ablation study 也证明实现细节不是点缀：完整四层 cache 相比未优化版本带来平均 `3.11x` 的提速，在高重复 workload 上最高达到 `38.95x`。

## 创新性与影响

和 `compute-sanitizer`、GPU AddressSanitizer 这类工具相比，这篇论文真正的新意并不只是“把 Z3 用到了 GPU 调试里”。更本质的一步，是把内存安全检查放回 Triton 的 tile 语义边界内，再结合一次具体 launch 的动态元数据完成证明，而不是等 Triton 把有用结构都擦掉之后，才在低层 IR 上补做检查。和 _Ibn Ziad et al. (PLDI '23)_ 相比，Triton-Sanitizer 的目标也不是做出最快的 CUDA sanitizer，而是利用更高层 DSL 的结构来保持 device-agnostic，并显著增强诊断上下文。与 _Lee et al. (ISCA '22)_、_Lee et al. (HPCA '25)_ 这类依赖硬件支持的方案相比，它则明确选择了“牺牲一些最优 kernel-time 性能，换取 commodity accelerator 上可部署的软件方案”。

因此，这篇论文的影响面会比较清晰。对 Triton kernel 作者来说，它提供了一个与实际编程抽象一致的调试工具。对编译器和后端工程师来说，它说明 DSL 层语义不仅能帮助优化，也能帮助正确性工具降低成本、提高解释力。对系统研究者来说，它还给出了一个很实用的范例：符号执行不一定非得追求全程序定理证明，也可以被收束成一个利用领域结构、只在必要处回退到 eager execution 的专用 checker。

## 局限性

它给出的保证是动态的，而不是普适的。Triton-Sanitizer 只能证明当前这次 launch 配置、当前 tensor metadata、当前运行时取值下的安全性，因此不能替代 sound static verifier。对间接访问的 hybrid 回退还需要把相关 tensor 复制到 CPU 上做数值求值；这个设计很务实，但在 pointer-heavy 的 kernel 上可能带来额外成本。

论文也坦承它对真实生产栈的覆盖还不完整。若一个 pipeline 同时包含 Triton kernel 和 CUDA 等低层 GPU kernel，Triton-Sanitizer 只能看见前者，看不见系统里所有内存操作。对 `torch.compile` 自动生成的 Triton kernel，它目前也缺少从错误 kernel 反向映射到原始 PyTorch 源码与具体 TorchInductor pass 的能力，所以报告对编译器工程师仍然不够“可行动”。最后，作者无法与 cuCatch、GPUShield、Let-Me-In 这些更强的研究型 sanitizer 做直接实验对比，因为它们依赖特定编译器、驱动或硬件；论文给出的定性比较是合理的，但也意味着性能与覆盖率设计空间里的最优点并没有被完全实证地锁定。

## 相关工作

- _Tillet et al. (MAPL '19)_ — Triton 奠定了 tile-oriented DSL 与编译栈的基础，而 Triton-Sanitizer 正是建立在这层语义之上做内存安全检查。
- _Ibn Ziad et al. (PLDI '23)_ — cuCatch 通过编译器插桩和驱动支持检测 CUDA 内存安全错误；Triton-Sanitizer 则用 Triton 原生语义换取 device-agnostic 与更强的诊断上下文。
- _Lee et al. (ISCA '22)_ — GPUShield 借助硬件支持做 region-based GPU bounds checking，而 Triton-Sanitizer 的目标是在 commodity 设备上纯软件部署。
- _Lee et al. (HPCA '25)_ — Let-Me-In 依赖指针内嵌元数据和硬件机制推进细粒度 GPU memory safety；Triton-Sanitizer 则依赖 DSL 语义和符号推理。

## 我的笔记

<!-- empty; left for the human reader -->
