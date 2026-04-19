---
title: "Seal: Towards Diverse Specification Inference for Linux Interfaces from Security Patches"
oneline: "Seal 把安全补丁提炼成 Linux 接口的 value-flow 规格，再到其他实现和 API 用法里做路径敏感检查，找出长期潜伏的同类漏洞。"
authors:
  - "Wei Chen"
  - "Bowen Zhang"
  - "Chengpeng Wang"
  - "Wensheng Tang"
  - "Charles Zhang"
affiliations:
  - "The Hong Kong University of Science and Technology, China"
  - "Purdue University, USA"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717487"
code_url: "https://github.com/harperchen/SEAL.git"
tags:
  - security
  - kernel
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Seal 的主张很明确：Linux 接口规格不该靠多数派代码习惯去猜，而该从已经修过的安全补丁里学出来。它把补丁前后的代码变化抽象成 interaction data 的 value-flow 约束，再用路径敏感的可达性分析去检查别的实现和 API 用法是否违背这些约束。作者在 Linux v6.2 上从 12,571 个安全补丁里找出 167 个未知漏洞，bug report 精度为 71.9%。

## 问题背景

这篇论文盯住的是 Linux 开发里一个长期存在但很少被形式化处理的问题：子系统之间虽然通过 API 和 function pointer 协作，但内核通常只保证类型签名兼容，并不保证返回值、参数、全局变量和副作用该怎样流动、检查和收尾。真正会触发漏洞的，往往正是这些没被写清楚的隐含协议。

作者给出的例子很典型。某个 `buf_prepare` 实现调用 `dma_alloc_coherent` 后，局部其实已经察觉分配失败，但返回给上层的错误码不对，结果调用者继续沿着错误状态往下走，最后触发 null pointer dereference。对开发者来说，文档往往只解释接口做什么，不解释 interaction data 该如何处理；对静态分析器来说，没有接口规格就只能靠经验规则或相似代码去猜。论文对 158 个历史补丁做经验分析后发现，bug trace 只有 34.8% 完全局限在被修改函数内部，而且数据误用形态横跨 11 类漏洞。也就是说，如果方法既不能跨函数追踪，也不能同时表达多种接口行为，它就很难真正泛化。

## 核心洞察

Seal 的核心洞察是：安全补丁本身就是一份关于规格违例的证据，而补丁改变了哪些 value-flow path，恰好透露了原本缺失的接口约束。关键不只是看改了哪几行，而是把这些变化转成更抽象的 value-flow property，也就是某个值能不能到达某个 use、在什么条件下到达、以及多个 use 之间必须满足怎样的执行顺序。

这种表示法之所以重要，是因为它能把三类看上去差异很大的 bug 统一起来。论文里的第一个例子要求 `-ENOMEM` 必须沿着 function pointer 的返回路径往上传；第二个例子要求当 `smbus_xfer` 的 `arg2.len > MAX` 时，`arg2.block` 绝不能流到 `deref`；第三个例子则要求 `put_device` 只能发生在最后一次解引用之后。换句话说，Seal 不是把补丁原样背下来，而是保留 source、sink、相关条件和相对顺序，丢掉只属于某个补丁现场的局部变量与中间语句，这样规格才能迁移到兄弟实现上。

## 设计

Seal 的流水线分成四步。第一步，它分别为补丁前和补丁后的代码构建 program dependence graph，里面同时有 data dependence、control dependence 和 flow dependence。第二步，它围绕变化过的 interaction data 做 slicing，收集跨过程的 changed value-flow path；每条路径都带着 source、sink、路径条件 `Psi` 和执行顺序映射 `Omega`。

第三步是规格抽象。Seal 把变化路径分成四类：被删掉的路径、新增的路径、条件发生变化的路径、以及 use site 顺序变化的路径。然后，它先在具体程序变量层面形成关系，再把这些关系映射到接口层面的对象，比如 function pointer 参数、API 返回值、`deref` 这种敏感 use，或者接口向外输出的数据。量词也是从补丁变化里反推出来的，因此它既能表达某条路径必须存在，也能表达某类路径在特定条件下绝不能存在。正因为这一层抽象，错误码传播、缺少边界检查、API 调用次序颠倒，才能被塞进同一套规格语言里。

第四步是 bug detection。若规格涉及 function pointer，Seal 就把它应用到同一 function pointer 的其他实现上；若只涉及 API，则应用到其他 API 用法上。检测时它做 flow-sensitive、context-sensitive、field-sensitive 和 path-sensitive 的可达性搜索，并在遍历过程中同步检查路径条件，尽早剪掉不可能的路径。实现上也做了不少工程折中：PDG 按需生成，跨函数 slicing 在边界处做 memoization，分析运行在 LLVM SSA 上，逻辑约束交给 Z3，间接调用则用 type analysis 来缩小目标范围。

## 实验评估

评估规模是有说服力的，而且基本对准了论文想证明的点。Seal 面向 Linux v6.2，从 12,571 个安全补丁里一共抽象出 12,322 条接口关系，最终生成 232 份 bug report，其中 167 个被人工确认是真 bug，precision 为 71.9%。这些结果并不只集中在单一角落：146 个在 driver，13 个在 network，7 个在 filesystem，还有 1 个在 core subsystem。作者把发现主动提交给 maintainers 后，已有 95 个被确认，56 个已经被他们的补丁修掉；这些 bug 平均潜伏了 7.7 年，其中 29% 的潜伏期超过 10 年。

和已有系统的对比也很能说明问题。最接近的 patch-based baseline `APHP` 一共报出 28,479 个问题，但真正的 true positive 只有 60 个，因为它的规格形式基本只覆盖 API post-handling，而且路径分析也更受限。deviation-based 的 `CRIX` 报出 3,105 个问题，确认 44 个 true positive，和 Seal 只重合 1 个 bug。就这个结果看，论文的中心论点是成立的：把安全补丁当成高质量监督，再配上更有表达力的规格语言，确实能以更高精度覆盖更多种接口误用。

不过，实验也暴露出一个不能忽视的现实：规格本身的准确率低于最终的 bug precision。作者随机抽查 1,000 条推断出来的规格，只有 57.8% 被判为正确。他们的解释是，错误规格往往更局部、更难在别处形成可扩展的违例，因此不会按同样比例转化成误报。这个解释有道理，但也说明规格抽象阶段仍然很噪。效率方面，离线 mining 的成本还算可接受：处理全部 12,571 个补丁要 30 小时 39 分，平均每个补丁 8.78 秒；后续 bug detection 里，PDG 生成用了 5 小时 25 分，path searching 又用了 1 小时 48 分。

## 创新性与影响

Seal 最重要的创新，不是单纯把补丁拿来当输入，而是用补丁去学习一套足够通用的接口规格表示法。过去的 patch-based 工作大多停在 post-handling 这类窄模式上，deviation-based 工作则默认多数实现是对的。Seal 换了一个角度：把补丁当成规格违例的权威证据，再把这些证据统一投射到 value-flow property 这一层。真正新的是这个组合，而不只是某个单独的分析步骤。

这件事的意义在于，Linux 静态分析往往按 bug type 分裂成很多专用工具，今天抓 missing check，明天抓 memory leak。Seal 提供的是一层更可复用的中间表示：先把接口层面的规则挖出来，再去大范围检查 reachability、condition 和 ordering 是否被破坏。对做 kernel analysis、specification mining、patch-guided bug detection 的研究者来说，这篇论文应该会很有参考价值，因为它不仅给出机制，还拿 maintainer 确认过的真实漏洞证明这套机制确实能落地。

## 局限性

Seal 的上限首先受补丁质量约束。论文自己也承认，安全补丁可能过时、修不全，甚至人工审查后仍然有误，而 57.8% 的 sampled specification precision 已经把这个问题摆在台面上。文中的一个失败案例是，某条值同时受多个 API 影响，于是 Seal 会保守地把错误的 paired operation 也一起推断进去。

其次，规格表达能力并没有覆盖所有跨接口协作。Seal 能描述多个 API 之间的关系，但还不能优雅地表达多个 function pointer 共同完成某个协议的场景。为了控制成本，它的 bug detection 也刻意局限在同一 function pointer 的其他实现内，因此需要更大调用上下文的 bug 会漏掉。另外，当前 PDG 不直接建模并发关系，所以 data race 这类问题不在它的覆盖面里，除非以后把 lock dependence 或 happens-before 之类的信息补进去。

## 相关工作

- _Lin et al. (USENIX Security '23)_ - APHP 也是从补丁里学规格，但它主要建模 API post-handling；Seal 则把 reachability、condition 和 use-site ordering 一起纳入规格语言。
- _Lu et al. (USENIX Security '19)_ - CRIX 通过比较语义相近代码来找 missing-check bug，而 Seal 借助补丁证据建规格，覆盖范围也超出 missing check。
- _Yun et al. (USENIX Security '16)_ - APISan 建立在「多数用法是正确的」这个统计前提上；Seal 则直接把安全补丁当成违例证据，避免依赖多数派假设。
- _Min et al. (SOSP '15)_ - Juxta 通过交叉比对实现来总结潜在语义规则，Seal 则从 bug-fixing history 中直接抽出可迁移的接口约束。

## 我的笔记

<!-- 留空；由人工补充 -->
