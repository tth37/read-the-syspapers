---
title: "Paralegal: Practical Static Analysis for Privacy Bugs"
oneline: "Paralegal 用 markers 把隐私策略与源码解耦，再在 Rust 的 PDG 上检查这些策略，并利用 ownership-aware 的类型信息近似库代码行为。"
authors:
  - "Justus Adam"
  - "Carolyn Zech"
  - "Livia Zhu"
  - "Sreshtaa Rajesh"
  - "Nathan Harbison"
  - "Mithi Jethwa"
  - "Will Crichton"
  - "Shriram Krishnamurthi"
  - "Malte Schwarzkopf"
affiliations:
  - "Brown University"
conference: osdi-2025
code_url: "https://github.com/brownsys/paralegal"
tags:
  - security
  - formal-methods
  - pl-systems
category: verification-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Paralegal 是一个面向 Rust 应用的隐私漏洞静态分析器。它的核心做法是先用 markers 把隐私策略与具体源码解耦，再在一个同时具备 flow-sensitive、context-sensitive 和 field-sensitive 特性的 Program Dependence Graph 上检查这些策略，并利用 Rust 的 ownership 与 lifetime 信息去近似库代码行为。在 8 个真实应用上，它共找出 7 个隐私问题，其中 2 个此前未知。

## 问题背景

论文试图解决的首先不是某个单点算法问题，而是隐私合规在工程实践里的落地问题。真实应用必须满足诸如“所有用户数据都必须可删除”“收集前必须先经过同意检查”“写入前必须先经过授权检查”这类规则，但现实里很多团队仍主要依赖人工审计。隐私专家或外部顾问手动看代码的方式既昂贵，又不可能频繁进行，更经不起多人持续改代码带来的语义漂移。

现有方案各有明显短板。面向特定领域的隐私分析器之所以实用，通常是因为它把应用模型、框架语义或查询语言都写死了，因此一旦跳出那个域就不再适用。信息流类型系统能表达一部分 secrecy 性质，但对“某件事必须发生”这种近似 liveness 的要求并不擅长，例如数据删除；而且它们往往要求侵入式注解或特殊编程风格。像 CodeQL 这样的通用代码分析系统虽然灵活，却迫使策略作者直接面向语法结构、标识符正则表达式以及手工维护的库模型来写策略。

Paralegal 试图同时解决组织协作问题。隐私工程师知道要满足什么策略，但往往不知道这些概念在代码里具体落在哪些函数、类型或参数上；开发者正好相反。因此，一个真正可用的系统必须允许两类人各管自己最擅长的那一层，而不是让任何一方独自维护整套规范。

## 核心洞察

论文的核心命题是：只有把工作拆成三层，隐私静态分析才会真正实用。隐私工程师应该只对 `user_data`、`deletes`、`executes` 这类语义标签写策略；开发者负责把这些标签附着到他们熟悉的代码实体上；分析器则负责回答这些被标记实体之间，是否存在策略要求的数据依赖或控制依赖路径。

这套分工只有在分析器仍能处理真实 Rust 程序时才成立，否则开发者最终还是得回去补库模型。Paralegal 的第二个关键洞察是，Rust 的类型系统已经给了分析器一套很强的近似工具。ownership 与 lifetime 对 mutation 和 aliasing 有严格约束，因此即便看不到某个库函数的实现，分析器也往往能从其类型签名推断它可能影响什么。再结合 markers，Paralegal 只需要展开真正可能接触策略相关代码的那部分调用图，而不是把整个程序都精细建模。

## 设计

Paralegal 的设计由三个部件组成：Program Dependence Graph、markers，以及 policy DSL。PDG 从 Rust 的 MIR 构造出来，并且显式保持 flow-sensitive、context-sensitive 和 field-sensitive。论文里的 Plume 删除漏洞例子很好地说明了这三种敏感性为什么缺一不可。没有 flow sensitivity，就可能把“先执行再构造查询”的错误顺序也看成合法；没有 context sensitivity，不同调用点对同一个 helper 的调用会被混在一起；没有 field sensitivity，`posts` 和 `comments` 这种同一结构里的不同字段会被折叠，原始漏洞就看不见了。

为了让这个 PDG 在真实代码上跑得动，Paralegal 深度依赖 Rust 语言特性。它先用静态可得的类型做 monomorphization，把 trait method 调用解析到具体实现；再用 function cloning 为每个调用点复制被调子图，以换取上下文精度。对拿不到源码或分析代价太高的库函数，它使用 modular approximation：先保守地假设参数会影响输出，再用 Rust 特有的事实把这个近似收紧。比如 immutable reference 不允许被修改，lifetime 又约束了返回引用可以别名到哪里，因此 Paralegal 得到的库模型要比“所有指针都可能互相别名”的语言精确得多。

Markers 是代码与策略之间的桥。开发者可以把 marker 挂到函数、参数、返回值和类型上，Paralegal 再把它们传播到具体 PDG 节点。类型上的传播策略是有意偏宽的：如果某个被标记类型嵌在另一个类型内部，外层值也可以继承该 marker。Paralegal 还利用 markers 做性能优化。如果某个被调函数以及它可达的后续代码都碰不到任何 marker，分析器就不继续展开其子图，而是直接用类型签名近似其效果。论文把这种机制称为 adaptive approximation，它是性能可用性的核心，而不是附属优化。

策略本身由一个受控自然语言 DSL 描述，最终编译成图查询。其基本关系并不多，但覆盖面很强：一个被标记值可以“go to”某个 sink，可以“affect whether”某个操作发生，也可以“only via”某个 disclosure 点后才到达 sink。基于这些原语，Paralegal 能表达删除、访问控制、purpose limitation 等不同类型的隐私规则。策略失败时，错误信息又会把违反的量化子句映射回具体源码位置，让开发者看到究竟是哪个 source 没有流到哪个 sink。

## 实验评估

评估足以支撑“practical”这一主张。作者把 Paralegal 应用到 8 个 production-style Rust 应用上，覆盖 graph database、social platform、payments、advertising、authentication 和 homework submission 等多种场景。总体上，他们形式化了 11 条策略，标记了 4 到 145 个程序位置不等的代码实体，并根据应用结构分析 1 到 72 个入口点。

最重要的结果是找 bug。Paralegal 在 Plume、Atomic 和 Lemmy 中共发现 7 个隐私问题，其中 2 个是此前未知且被 Lemmy 开发者确认的新问题。它也能重新抓出那些后来已经被修复的历史漏洞，这说明策略并不是只对论文里的玩具例子有效。与基线的对比也比较有说服力。IFC 只能表达 11 条策略中的 6 条，因为删除和保留策略属于典型的“must reach”模式，而不是 classic noninterference。CodeQL 的查询语言理论上能写出相关策略，但其分析引擎会在 interprocedural control flow、隐藏的库语义、alias analysis，以及 async/C++ 与 Rust 的错配上掉链子。作者进一步分析 CodeQL 查询结构，发现只有 36% 的 predicates 真正在表达策略本身，其余大多是在做标识代码元素、刻画外部库语义或补底层分析原语，这一点很好地体现了 markers 的工程价值。

维护成本和性能结果也不错。作者把一条 Atomic 策略回放到跨越 2.5 年的 1,024 个 commits 上，结果只有 2 个 commits 真正影响了 markers，而策略本身完全不需要修改。在 "Workspace Only" 模式下，大多数应用都能在 2.2 秒内完成，例外是 Hyperswitch 的 12 秒和 Lemmy 的 22.5 秒；按单个 endpoint 计，平均延迟是 0.8 秒，最坏也低于 5 秒。在 "All Dependencies" 模式下，多数应用依然低于 5 秒，只有 Lemmy 因为有 72 个 endpoints 上升到 94 秒。adaptive approximation 平均带来 35% 的运行时间下降，而且在固定深度对比里，它是 Lemmy 和 Plume 能否终止的关键。

## 创新性与影响

Paralegal 的新意不只是“把 PDG 用到隐私问题上”。真正新的地方在于，它把 marker-based policy decoupling、Rust-aware 的库行为近似，以及一个可以同时表达禁止流动和要求流动的 policy DSL 组合成了一个完整工作流。相较于领域专用的合规工具，它牺牲了一些预置语义，换来对更广泛 Rust 应用的适用性；相较于 IFC，它能覆盖更大一类策略；相较于 CodeQL 这类查询引擎，它把大量脆弱的“如何在语法层面找到正确代码实体”工作从策略本体中剥离了出去。

这使得它的影响面也不只局限于狭义隐私。论文已经提到，大型互联网公司正在考虑把它用于检查加密密钥保密性、静态验证 encryption-at-rest，以及确认 speculative-execution mitigation 是否真的被执行。更普遍地说，这篇论文展示了一条可信路径：如何把带有法律或治理语义的规则翻译成 CI 可以持续检查的程序属性，而不要求整个代码库迁移到某种专用框架或极度严格的类型纪律中。

## 局限性

论文对 soundness 并没有夸大。Paralegal 是静态 bug finder，不是“应用一定隐私正确”的证明。它的 soundness 与 completeness 都依赖具体策略，因为 PDG 可能引入 false dependencies，也可能在某些场景下漏掉真实依赖。unsafe code、interior mutability、共享内存同步原语，以及文件系统、数据库这类外部系统上的 effects，都可能让基于类型的近似失真。

它也有一些可用性边界。当前 marker 只能附着在函数、参数、返回值和类型上，不能直接标字段或常量，所以作者有时必须插入 no-op helper function 或重构代码。工具还会刻意丢弃 `await` 状态机带来的控制流，以减少让人困惑的 false positive，这意味着某些恶意 async 模式不会被检查到。最后，最快的本地分析模式可能漏掉依赖库里的 marker，因此论文建议把快速本地检查与较慢的全依赖 CI 检查配合使用。

## 相关工作

- _Crichton et al. (PLDI '22)_ - Flowistry 提供了 ownership-aware 的信息流分析基础，而 Paralegal 在此之上增加了 markers、policy DSL，以及面向隐私漏洞发现的完整工作流。
- _Johnson et al. (PLDI '15)_ - Pidgin 同样使用 program dependence graph 来表达安全约束，但 Paralegal 借助 Rust 的 ownership 类型去近似库行为，并把策略从低层分析细节里更彻底地剥离出来。
- _Ferreira et al. (S&P '23)_ - RuleKeeper 通过建模特定 web-framework 栈来实现 GDPR-style 合规，而 Paralegal 面向的是不依赖固定框架语义的一般 Rust 应用。
- _Albab et al. (SOSP '25)_ - Sesame 用 Rust 类型与 runtime policy containers 实现端到端隐私合规，而 Paralegal 则坚持完全静态的检查方式，目标是更轻量的 CI 式 bug finding。

## 我的笔记

<!-- 留空；由人工补充 -->
