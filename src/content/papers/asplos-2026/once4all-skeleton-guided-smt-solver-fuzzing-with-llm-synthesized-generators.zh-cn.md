---
title: "Once4All: Skeleton-Guided SMT Solver Fuzzing with LLM-Synthesized Generators"
oneline: "Once4All 先把 SMT 文档离线编译成可复用 theory generator，再把生成的 term 填进真实公式 skeleton，以较低成本持续挖掘演化中求解器的 bug。"
authors:
  - "Maolin Sun"
  - "Yibiao Yang"
  - "Yuming Zhou"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University, Nanjing, China"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790195"
tags:
  - fuzzing
  - formal-methods
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Once4All 的核心观点是：在 SMT solver fuzzing 里，LLM 最合适的位置不是在线不停生成整条公式，而是离线一次性读懂 theory 文档，合成可复用的 generator。运行时系统从真实 benchmark 中抽出公式 skeleton，再用这些 generator 产生的 Boolean term 去填洞，并对多个 solver 或多个 solver 版本做 differential testing。这样既保留了真实 bug 输入常见的深层结构，又能较快跟上 SMT-LIB 新特性和 solver-specific extension 的演化。

## 问题背景

论文要解决的是 SMT solver 测试里的一个长期维护难题。求解器输入语言并不是静态不变的：SMT-LIB 2.7 在持续增加更复杂的语言特性，像 cvc5 这样的 solver 也在不断加入自己的扩展 theory。已有方法在这种持续演化下都不够理想。grammar-based 方法需要专家长期手写和维护规则；mutation-based 方法高度依赖人工设计的 mutation strategy；直接让 LLM 生成完整公式则会产出大量无效输入，而且每次生成都要重新付出模型调用成本。

这个问题之所以重要，是因为 SMT solver 位于 symbolic execution、formal verification 和 synthesis 系统的关键路径上。一个 solver bug 可能悄悄让上层工具接受错误结论，或者错误拒绝本来成立的模型。论文给出的 cvc5 motivating example 很说明问题：真正触发 bug 的不仅是 sequence theory 里的局部表达式，还包括外层 quantifier 这样的结构元素。也就是说，测试不仅要覆盖新 theory 和扩展操作符，还要保留那些会把 solver 带进脆弱执行路径的逻辑骨架。

## 核心洞察

Once4All 的关键洞察是把“理解不断变化的输入语言”和“高吞吐生成海量测试”拆成两个阶段。LLM 只在离线阶段使用：读取 theory 文档、总结 context-free grammar、再合成可反复调用的 Boolean term generator。之后的 fuzzing 主循环不再频繁调用模型，而是退化成普通程序执行，从而把成本摊薄到几乎可以忽略。

但论文并不认为只要有 generator 就够了。很多 SMT bug 依赖的是整条公式的形状，而不是单个 operator 的局部选择。因此 Once4All 还保留真实公式的 skeleton：它从 seed 中删掉部分 atomic subformula，留下 placeholder，再用 generator 产生的新 term 去填充。这样做的意义在于把两类优势叠加起来：generator 负责引入新的 theory 内容和新特性，skeleton 负责保留 quantifier、logical connective 和嵌套结构，让生成公式更容易触达更深的 solver 行为。

## 设计

Once4All 分成两个阶段。第一阶段是 generator construction。系统先收集标准 SMT-LIB theory 文档，以及 Z3 Unicode、cvc5 Set/Bag 这类 solver-specific feature 的说明，然后让 GPT-4 为每个 theory 总结 CFG，并进一步生成一个统一接口的 Python generator。这个 generator 需要输出 Boolean term，同时带上必要的声明，例如 `declare-fun` 或 `declare-datatypes`，并尽量遵守目标 theory 的 SMT-LIB 语法约束。

由于文档总结出来的 grammar 仍然可能漏掉语义约束，论文又加入了 self-correction loop。每个新 generator 先生成 20 个 sample term，框架把它们补上需要的 SMT-LIB 外壳，再交给多个 solver 做解析。如果出现 parse error，Once4All 会先去重和归纳错误信息，再把这些反馈喂回 LLM，请它修正 generator 实现。这个过程最多迭代 10 轮，并保留历史上生成有效表达式最多的版本。作者也明确承认，这个过程不能形式化保证所有输出都完美合法，但它足以把 generator 质量提升到工程上可用的程度。

第二阶段是 skeleton-guided mutation。系统随机选择一个 seed formula，删除若干 atomic Boolean subformula，留下 placeholder；然后随机选择一个或多个 theory generator 生成替换项，并在拼接前检查 sort 是否兼容。若 sort 匹配，生成 term 里的变量还会被替换成 seed 中已有的变量，从而增强新内容与旧结构之间的语义交互。最终得到的公式会被送去做 differential testing；若输入包含 solver-specific feature，则比较同一个 solver 的不同版本。对出现 `sat` 的情况，系统还会用 `get-model` 验证返回模型是否真的满足公式，以区分 soundness bug 和 invalid model bug。实现上，Once4All 用 Python 编写，只在 generator 构造期依赖 GPT-4，并且对每个 seed 默认执行 10 次 mutation。

## 实验评估

实验对象是 Z3 和 cvc5，运行在一台 20 核 Xeon 机器上，seed 则来自先前工作整理出的历史 bug-triggering formula，并先过滤掉在最新 trunk 上仍能直接复现旧 bug 的样例。整个 bug-hunting campaign 中，Once4All 总共生成了约 1000 万个测试输入，平均每条公式大小为 4,828 字节。由这些输入触发出的 727 个 bug-revealing formula 最终归并成 45 个报告的 bug，其中 43 个被开发者确认、40 个已经修复。确认 bug 不只是 crash：还包括 6 个 invalid-model bug 和 4 个 soundness bug。

我认为最有说服力的结果，不只是总数，而是 bug 所在的位置。45 个报告里有 11 个涉及 newly added 或 solver-specific theory，而这恰恰是旧 fuzzers 最容易覆盖不到的区域。论文还分析了 bug lifespan，发现其中 3 个 Z3 bug 在六年多前的 release 上就已经存在。这很好地支持了作者的论点：求解器语言一边演化，一边在新 feature 和边缘实现里积累盲点，传统手工规则驱动的 fuzzing 很难及时追上。

和现有 SMT fuzzers 的对比也比较扎实。在 24 小时 code coverage 实验里，Once4All 在 Z3 和 cvc5 的 line coverage 与 function coverage 上都稳定超过基线，而且手工检查显示它能够打到一些基线从未覆盖过的 solver-specific 目录。在 known-bug 实验中，Once4All 找到 11 个 unique bug，而没有任何基线超过 3 个。ablation 也说明了设计因果关系：去掉 skeleton guidance 后，known-bug 数从 11 掉到 7；把 GPT-4 换成 Gemini 2.5 Pro 或 Claude 4.5 Sonnet，结果则与原版相近。换句话说，论文的主要增益来自 skeleton 与 reusable generator 的组合，而不只是某个特定大模型碰巧表现好。

## 创新性与影响

相对 _Sun et al. (ICSE '23)_ 的 HistFuzz，Once4All 延续了“历史 bug 输入 skeleton 很有价值”这一判断，但把手工 mutation logic 换成了由文档驱动、可随 theory 演化而更新的 generator。相对 _Sun et al. (ASE '23)_ 和 _Xia et al. (ICSE '24)_，它的新意并不只是泛泛地“把 LLM 用到 fuzzing 里”，而是把 LLM 固定在离线 generator synthesis 位置上，让运行时循环保持廉价且高有效率。相对 _Winterer and Su (OOPSLA '24)_，它放弃了 exhaustively enumerate grammar 的路线，换来了更快适配 solver-specific extension 和新语言特性的能力。

因此，这篇论文的影响面很清晰。对 solver 开发者来说，它提供了一条更实用的 workflow，去测试那些太新、太冷门、还没有成熟手写 fuzzing support 的 feature。对研究者来说，它也给出一种更普遍的 structured-input fuzzing 模式：让 LLM 先把松散文档编译成可复用 generator，再把 generator 和领域特定的结构模板结合，而不是每生成一个测试用例都重新请求模型。

## 局限性

作者明确指出，Once4All 目前生成的是 Boolean term，而不是任意 SMT term。这样做能让 synthesis 过程更可控，但也限制了搜索空间，可能错过那些依赖更复杂非 Boolean 子项或更大范围公式构造选择的 bug。论文也承认 self-correction 主要优化的是 syntactic validity，并没有直接把 semantic novelty、rare solver state 或 coverage feedback 纳入优化目标。

第二个限制是对文档质量的依赖。solver 文档可能不完整、表述松散，甚至落后于真实实现，而抽取出的 CFG 会继承这些问题。skeleton 虽然能通过保留真实公式结构来部分补偿这一点，但当 grammar 演化时，generator 仍然需要重新生成。最后，bug triage 还没有完全自动化：crash clustering、theory grouping 和 reducer 选择已经减少了人工工作量，但在真正把问题提交给开发者之前，人仍然在流程里。

## 相关工作

- _Sun et al. (ICSE '23)_ — HistFuzz 同样利用历史 bug-triggering formula，但 Once4All 用 LLM-synthesized theory generator 取代了手工设计的 mutation strategy。
- _Winterer and Su (OOPSLA '24)_ — ET 基于专家编写的 grammar 做公式枚举，而 Once4All 从文档中派生可复用 generator，并保留真实公式 skeleton。
- _Sun et al. (ASE '23)_ — LaST 更直接地使用 LLM 生成 SMT 公式；Once4All 把模型调用前移到离线阶段，再把这份成本摊销到高吞吐 fuzzing 过程中。
- _Xia et al. (ICSE '24)_ — Fuzz4All 是通用的 LLM fuzzing 框架，而 Once4All 针对 SMT 场景把 differential testing、theory-specific generator 和 skeleton-guided synthesis 绑在一起。

## 我的笔记

<!-- empty; left for the human reader -->
