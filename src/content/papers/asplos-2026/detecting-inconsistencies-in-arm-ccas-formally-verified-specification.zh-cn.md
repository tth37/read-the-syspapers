---
title: "Detecting Inconsistencies in Arm CCA’s Formally Verified Specification"
oneline: "Scope 将 Arm CCA 的 RMM 规范重建成 Verus 模型，并交叉核对表格、图示与 ABI 规则，找出 35 个经 Arm 确认的不一致。"
authors:
  - "Changho Choi"
  - "Xiang Cheng"
  - "Bokdeuk Jeong"
  - "Taesoo Kim"
affiliations:
  - "Samsung Research, Seoul, Republic of Korea"
  - "Georgia Institute of Technology, Atlanta, GA, USA"
  - "Samsung Research / Georgia Institute of Technology, Seoul, Republic of Korea / Atlanta, GA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790152"
code_url: "https://github.com/islet-project/scope"
tags:
  - confidential-computing
  - verification
  - formal-methods
  - security
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Scope 在没有实现可对照的情况下审计 Arm CCA 的 Realm Management Monitor 规范。它先把 PDF 中的 RMM ABI 语义重建成一个 Verus 模型，再检查摘要表格、状态图和命令级规则是否彼此一致。作者在多个 RMM 版本上共报告了 38 个候选问题，其中 35 个被 Arm 确认为真实的规范缺陷。

## 问题背景

这篇论文抓住了形式化验证里一个很少被正面解决、但其实非常要命的问题：证明再严密，也只是建立在“规范本身是对的”这个前提之上。如果规范错了，那么实现即便满足规范，系统仍然可能不安全，而形式化证明反而会给错误的东西增加可信度。Arm CCA 是一个高风险目标，因为 Realm Management Monitor（RMM）位于 confidential computing 的可信计算基里，而且它的规范往往先于实现不断演进。

这使得常见的验证路线都不够理想。没有实现时，拿规范去和实现做对照测试根本无从谈起；手工证明规范的元性质，又很难跟上频繁变化的 ABI；而且 RMM 文档并不是一个紧凑、统一的形式模型，它被拆散在长篇 prose、摘要表格、状态迁移图、命令条件函数以及 ASL 片段里。于是，真正的问题变成：能不能在实现落地之前，就直接在规范内部发现相互矛盾之处，避免这些错误继续传播到实现、下游形式模型和衍生设计文档里。

## 核心洞察

论文的核心主张是：只要同一份规范文档里同时给出了“摘要视图”和“细节视图”，就可以让规范自己和自己对账。Scope 把表格和图示视为架构师表达系统意图的摘要，再去问更细的 ABI 语义与命令条件是否真的蕴含了相同事实。如果两种视图无法同时成立，那么至少有一处是错的。

这个想法之所以成立，关键在于先把文档中的细节部分变成一个可查询的逻辑预言机。Scope 的做法是把 RMM 规范重建成 Verus 上的机器可检验模型，再把“检测矛盾”作为主要审计原语。论文更深一层的洞察是，这件事不需要先得到一个位精确、可执行的实现模型。即便很多辅助函数仍然保持 uninterpreted，系统也足以发现缺失前置条件、不可能的状态迁移、以及遗漏输出语义这类高价值的不一致。

## 设计

Scope 有两条分析路径：formal reasoning 和 rule-based consistency checking。两者共享同一个前端。系统先运行 `pdftotext`，去掉目录、页眉页脚等噪声，再从 RMM PDF 中抽取逻辑成分，包括命令接口、数据类型、命令条件函数、footprint 和 ASL 片段。之后它把这些内容翻译成 Verus。每个命令都会变成一个关于输入、输出、旧状态和新状态的布尔规约函数，这样模型就能清楚地区分“执行前必须成立的条件”和“执行后应当出现的效果”。作者还会额外补出一些 deduced conditions，例如“如果没有任何 failure precondition 成立，那么命令应成功”以及“未被修改的字段必须保持不变”。

在 formal reasoning 路径里，Scope 把这个重建后的 RMM 模型当成 oracle。它把摘要表格或图示手工或半手工翻译成 proof query。比如，如果某张表声称某个命令只有在特定 `RIPAS` 或 `HIPAS` 状态下才能成功，Scope 就会生成 Verus 断言，检查所有成功执行是否都满足这些依赖与状态更新。如果求解器打破了断言，就说明表格和详细命令语义并不一致。同样的方法也被用于检查状态迁移图，以及从类型定义里抽出的隐式不变量，例如 Protected 与 Unprotected IPA 各自允许的状态约束。

另一条路径更轻量，但很实用。Scope 对解析出的命令应用启发式规则，专门查两类问题：缺失 footprint 和 dangling output。前者表示 success conditions 修改了某个状态，但 footprint 却没声明这个状态会被改；后者表示命令返回了某个寄存器输出，可规范里从未写清它在执行后的值。这些检查不依赖 SMT 推理，但同样能挖出会误导实现者和下游验证者的真实规范错误。

## 实验评估

这篇论文的实验说服力不错，因为它既看“找到了多少真问题”，也看“在持续演进的规范上能覆盖多少内容”。跨多个 RMM 版本，Scope 一共报告了 38 个候选不一致，其中 35 个被 Arm 确认。部分 bug 最长持续了 33 个月；而且 13 个问题出现在新加入的 ABI 上，这正好支撑了论文的主张：这种工具的价值就在于规范一直在变，人很难靠纯手工持续跟上。

在主要效果实验里，formal reasoning 在 `1.0-eac5` 和 `1.0-rel0` 上的 precision 分别是 `33.33%` 和 `25%`，而 rule-based checks 在两个版本上都达到 `84.62%`。当作者把 `1.0-rel0` 上的结果和 LLM baseline 对比时，Scope 的 precision 是 `61.90%`，而 GPT-o1 只有 `8.00%`，其他模型更低。覆盖率方面，Scope 在较老版本上覆盖了 `28/41` 个命令（`68%`），在 `1.1-alp12` 上最高达到 `79/101`（`78%`）；作为对比，VIA 只覆盖 `22` 个命令，Arm 已公开的 model-checking harness 只覆盖 `8` 个。

这些结果总体上很好地支持了论文主张，不过边界也很明确。论文非常擅长说明“规范内部矛盾很多，而且真的会造成后果”，但 precision 的损失仍然部分来自 uninterpreted functions 的欠定语义，以及解析器尚不能完全规整的文档写法。所以它的胜利不是“自动抽出全部真理”，而是“相比手工方法或 LLM 主导方法，能以更可扩展的方式抓到更多真实不一致”。

## 创新性与影响

和 _Reid (OOPSLA '17)_ 相比，Scope 不是依赖大量人工围绕 architect-defined views 做规范审计，而是把这种审计流程自动化成系统性的矛盾检查。和 _Goldweber et al. (OSDI '24)_ 相比，它关注的不是实现边界上“形式性质是否忠实表达开发者意图”，而是形式规范文档内部是否已经自相矛盾。和 _Li et al. (OSDI '22)_ 以及 _Fox et al. (OOPSLA '23)_ 相比，这篇论文的贡献也不是再去证明 Arm CCA 的某个安全性质，而是先追问“被证明的那个规范本身是否前后一致”。

因此，这篇论文最可能影响两类人：一类是做 confidential-computing 标准、固件和架构规范的人，另一类是关心 specification trustworthiness 的系统验证研究者。它的主要贡献是一种新方法，而不是新的 TEE 机制；但这是一种会直接影响安全性的工程方法。

## 局限性

论文很坦率地承认，Scope 不是 Arm CCA 的完整语义模型。它大量依赖 uninterpreted functions，不是 bit-precise 也不是 byte-precise，也不处理 failure conditions 之间的先后顺序。有些摘要图仍然需要人工翻译成 proof query。对于描述为空、非常散文化、或包含尚不支持 ASL 语法的命令，覆盖率也会下降，因此它目前还远不是一个可以直接吃下所有架构规范的通用解析器。

另外还有一个偏 reviewer 风格的担忧：如果摘要视图和详细命令文本恰好复制了同一个错误假设，那么“让两种视图互相对账”也发现不了问题。这个方法最擅长抓的是视图之间的不匹配，而不是从零开始重建唯一正确意图。不过从论文报告的 bug 数量来看，这种“不匹配型”错误已经足够常见，足以证明方法的价值。

## 相关工作

- _Reid (OOPSLA '17)_ — 用 architect-defined views 验证 Arm v8-M 规范，而 Scope 把这类思路推进成更自动化的矛盾检查流程。
- _Li et al. (OSDI '22)_ — 形式化验证 Arm CCA 的部分性质；Scope 则更往前一步，先检查底层 RMM 规范本身是否内部一致。
- _Fox et al. (OOPSLA '23)_ — 提出 Arm CCA 的验证方法学；Scope 对它形成补充，专门自动发现规范文本、表格和图示中的错误。
- _Goldweber et al. (OSDI '24)_ — 强调要用开发者意图审计形式规范；Scope 则用摘要表格、图示和规则检查把类似的信任问题具体化、自动化。

## 我的笔记

<!-- 留空；由人工补充 -->
