---
title: "WASIT: Deep and Continuous Differential Testing of WebAssembly System Interface Implementations"
oneline: "WASIT 把模糊的 WASI 规范补成可求解约束和资源状态模型，生成深层差分测试，并在 6 个运行时里找出 48 个漏洞与缺陷。"
authors:
  - "Yage Hu"
  - "Wen Zhang"
  - "Botang Xiao"
  - "Qingchen Kong"
  - "Boyang Yi"
  - "Suxin Ji"
  - "Songlan Wang"
  - "Wenwen Wang"
affiliations:
  - "University of Georgia"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764819"
code_url: "https://github.com/yagehu/wasit"
tags:
  - fuzzing
  - formal-methods
  - isolation
  - security
category: verification-and-reliability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

WASIT 把仍在快速演化、描述又很粗略的 WASI 规范，当成一份可以被执行的接口契约来补强，而不只是带注释的参考文档。它给规范补上资源类型、调用前提和输出副作用，再结合 SMT 求解与 differential testing，生成跨 6 个运行时的有状态 WASI 调用序列。4 个月间，这套方法找到了 48 个新的 WASI 缺陷，其中包括 sandbox escape、数据破坏问题和 3 个 CVE。

## 问题背景

WASI 是 WebAssembly 走出浏览器的关键层，但它天生带着一组很难同时处理的性质。它像 system call 一样强依赖状态；它的实现又建立在 host OS kernel 的系统服务之上，而这些语义和 WASI 并不总是一一对应；更麻烦的是，WASI 自身规范仍然粗糙而且变化很快。像 `path_open()` 这样的函数，是否正确往往取决于此前创建过哪些 descriptor、传了什么 flags、路径长什么样、以及底层平台如何解释这些状态。这意味着只做单次、浅层调用测试，几乎碰不到真正麻烦的 bug。

现有 Wasm runtime 测试大多集中在 Wasm instruction，而不是 WASI 语义。少数触及 WASI 的方法，要么只能生成彼此孤立的调用，要么依赖难以扩展的启发式，无法维护深层的跨调用依赖。论文强调问题的严重性并不抽象：WASI 实现错误可能导致 silent data corruption、文件系统 sandbox escape，甚至已经出现过实际 CVE。最直接的替代方案看似是对白盒分析每个 runtime，但这在现实里并不成立，因为这些实现分布在 C、C++、Rust、Go 等不同语言和生态中。WASIT 解决的正是这个现实缺口：在不先形式化每个实现的前提下，如何系统性地测试一个 polyglot、underspecified、快速演化的接口。

## 核心洞察

论文最重要的判断是：测试 WASI，并不需要知道每个 runtime 的内部实现细节，只需要从接口本身恢复出“足够多的语义”。WASIT 通过三类补充信息做到这一点：什么对象算资源、一个函数在什么条件下才是语义上合法的、以及成功执行之后应如何更新抽象资源状态。一旦这三点被显式写出来，依赖关系复杂的调用序列就可以机械合成，而不必依赖人工脚本或大量启发式。

这个判断之所以关键，在于它把建模负担从各个 runtime 的实现层，转移到了一个更轻量的接口抽象层。同一个抽象 file descriptor 可以在不同 runtime 中被 lowering 成不同的整数值，执行后再被 lifting 回统一的抽象资源，并检查它们是否对同一个抽象文件产生了相同的语义效果。换句话说，WASIT 关注的不是 concrete value 是否相同，而是语义身份和状态迁移是否一致。

## 设计

WASIT 的设计可以分成三个阶段。第一步，它用一个小型 DSL 去增强 `witx` 风格的 WASI 规范。`@resource` 注解把普通 WASI 值提升成带结构的抽象资源，例如带有 offset、flags、type、path 等字段的 file descriptor。`@input` 注解把调用前提写成量词受限的布尔约束，`@output` 注解则描述一次成功调用会如何创建、消费或更新资源。因为这些注解复用的仍是 WASI 自身的值类型，所以它保持的是“接口内建语义”，而不是另起一套完全独立的形式系统。

第二步，WASIT 维护一个跨所有 runtime 共享的全局抽象系统状态，以及每个 runtime 各自的 resource context，用来把抽象资源映射到本地 concrete value。调用前，WASIT 把抽象资源 lowering 成各个 runtime 中对应的 descriptor 或 handle；调用后，再把返回的 concrete value lifting 回共享抽象状态。这使它能够容忍一些无害差异，例如某个 runtime 把文件打开成 fd 5，另一个打开成 fd 100，但两者仍然对应同一个抽象文件，并且都应当把同一个抽象 offset 更新正确。

第三步，框架把 SMT 求解同时用于“生成调用”和“更新状态”。它先把每个函数的输入要求编码到当前 live resources 上，并通过把资源引用 eager instantiation 到现有抽象状态中的成员，避免引入难解的显式量词。只要约束可满足，这个函数就进入候选集；随后通过重复求解并加入 blocking clause，为同一个函数采样多组合法参数。执行完成后，另一套约束编码器再根据函数的输出效果和实际返回结果，求出下一步抽象状态。输入和输出都复用同一套 symbolic machinery，是这篇论文设计上很干净的一点。

实现细节也很重要。WASIT 本体大约是 6.7 KLoC Rust，再加一个 C 写成的 executor；目标接口是 WASI preview1；在官方 1,301 行规范之外，作者大约补了 170 行 DSL 注解。论文还专门处理了几个容易被忽略的工程问题：先把不同 runtime 的初始 sandbox 状态做 normalization；对 short write 这类“允许部分完成”的调用进行透明重试；并在每次调用后对 sandboxed filesystem 做 snapshot，从而能检查隐式副作用，而不只是显式返回值。

## 实验评估

评估覆盖了 6 个主流 runtime：Node.js、WAMR、WasmEdge、Wasmer、Wasmtime 和 Wazero，并在 Linux、macOS、Windows 三个平台上运行。headline result 很强：4 个月的间歇式测试总共发现 48 个新的 WASI 缺陷，其中 41 个获得确认、37 个已修复、3 个获得 CVE。更有说服力的是，其中 15 个已修复缺陷在对应 runtime 中已经潜伏了 4 年以上。表中的 bug 也并不只是 crash，而是包括 offset 处理错误、path sandbox 违规、timestamp 语义错误、append flag 处理错误、目录校验错误等，这和论文的核心论点一致：真正难的是深层语义正确性，而不是单纯 parser robustness。

两个 case study 能把这种“深层”说清楚。一个 Wasmtime 缺陷来自这样的序列：先用 append 语义打开文件，再写入，再读取当前 offset，然后通过 `fd_pwrite()` 暴露出 stale offset tracking，最终导致文件内容被覆盖。另一个 Wazero 缺陷则出现在 reset descriptor flags 之后：runtime 重新打开 host file，却没有恢复之前的 offset，于是后续 `fd_tell()` 错误地返回 0。这两类问题都非常依赖跨调用状态，很难靠浅层、单调用测试击中。

与 Wasix、DrWASI，以及一个关闭资源跟踪、只保留 `syzkaller` 风格随机生成的消融版本相比，WASIT 的机制性优势也基本成立。论文报告它能达到远更深的 resource chain，最大资源深度达到 1,310，而 Wasix 与 DrWASI 基本停留在深度 1。它在所有可插桩 runtime 上也拿到最高的 branch coverage，例如 Node.js 上是 1,216 条分支，高于消融版的 1,204 和 Wasix 的 748。最后，在作者只花大约 10 个工时补语义约束后，WASIT 在一轮 10 分钟测试中不再报告任何 inconsistency，而其他工具在同样时间内会产生数百到上千个 inconsistency，并且全部都是 false positive。这里仍有一个公平性 caveat：coverage 实验排除了 Wasmer 和 Wazero，DrWASI 也无法适配 Node.js，但整体证据仍然足够有力。

## 创新性与影响

相对 WADIFF、WASMaker 这类 Wasm runtime tester，WASIT 的新意在于它真正把 WASI 当成一个有状态接口来测，而不是只测 Wasm instruction 或 binary generation。相对 DrWASI 和 Wasix，它贡献的是一套更显式的语义模型：live resource abstraction、可执行的 precondition/effect，以及把 testing strategy 与具体调用生成解耦的架构。这更像是一种新机制，而不是换了一组 benchmark。

它的影响也可能是双重的。对 Wasm runtime 维护者来说，WASIT 已经证明自己是一个有直接生产价值的 bug-finding tool。对系统测试研究者来说，它展示了一种介于“完整形式化”与“盲目 fuzzing”之间的设计点，特别适合那些接口本身不断演化、实现又跨语言分布的 resource-centric API。

## 局限性

当前实现只覆盖 WASI preview1，而不是更新的 0.2 体系；论文也明确承认，0.2 在当时还未稳定，而且各 runtime 的支持差异很大。这意味着论文提出的“与 WASI 共演化”目前更多还是架构潜力，而不是已经在下一代稳定接口上被完整证明。

另一个限制来自方法本身。注解负担相对完整形式化已经很轻，但它仍然是手工完成的，也仍然依赖人工 triage 来区分真正的 bug 与语义分歧。作为一种 differential tester，WASIT 在多个 runtime 共享同一种错误语义时会天然失灵；而当规范本身过于模糊、开发者对语义没有共识时，它也无法凭空给出权威答案。论文大幅降低了噪声，但并没有消除 differential testing 的根本边界。

## 相关工作

- _Zhou et al. (ASE '23)_ - WADIFF 在 WebAssembly instruction 层做 differential testing，而 WASIT 测的是有状态的 WASI 语义与资源依赖。
- _Cao et al. (ISSTA '24)_ - WASMaker 通过语义感知的 Wasm binary generation 测试运行时，但它不维护 live WASI resources，也不合成长链条的接口级调用。
- _Zhang et al. (TOSEM '25)_ - DrWASI 通过 LLM 生成 C 程序、再间接走 toolchain 触达 WASI；WASIT 则直接调用 WASI，并用显式资源跟踪进入更深的系统状态。
- _Ridge et al. (SOSP '15)_ - SibylFS 提供形式化程度更高的 POSIX 测试，而 WASIT 用较轻量的 symbolic model 在多样化 Wasm runtime 上换取可用性与扩展性。

## 我的笔记

<!-- empty; left for the human reader -->
