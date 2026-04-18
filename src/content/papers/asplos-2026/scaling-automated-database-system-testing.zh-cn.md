---
title: "Scaling Automated Database System Testing"
oneline: "SQLancer++ 在线学习目标 DBMS 真正支持的 SQL 特性，再结合通用逻辑错误 oracle 和特征集去重，把数据库测试扩展到更多引擎。"
authors:
  - "Suyang Zhong"
  - "Manuel Rigger"
affiliations:
  - "National University of Singapore, Singapore, Singapore"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790215"
project_url: "https://doi.org/10.5281/zenodo.18289297"
tags:
  - databases
  - fuzzing
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SQLancer++ 不再要求先为目标 DBMS 手写完整 generator，而是在线学习它真正接受的 SQL 方言。借助这种做法，它把通用 logic-bug oracle 扩展到 18 个系统，并报告了 196 个此前未知的 bug，其中 180 个已被修复。

## 问题背景

oracle-based DBMS testing 已经证明自己有能力发现 logic bug，但它在工程上并不容易规模化。像 SQLancer 这样的工具需要为每个数据库单独编写 statements、expressions、metadata access 和各种方言细节的 generator。CrateDB 的案例很说明问题：即便复用 SQLancer 的 PostgreSQL generator，最小适配仍然要改 1,296 行代码；如果放任语法失败不管，查询有效率会跌到不到 1%。而且就算移植完成，测试活动也常常会吐出成百上千个 bug-inducing case，其中很多只是同一底层 bug 的重复表现。真正的问题因此不只是“有没有好 oracle”，而是能否把每个 DBMS 的接入成本和后续 triage 成本都压下来。

## 核心洞察

核心洞察是用在线特性学习取代人工方言建模。SQLancer++ 把关键字、运算符、函数和类型约束都视为候选 SQL features，先尝试生成，再通过执行反馈推断目标 DBMS 真正支持哪些特性。为了让这件事可落地，系统又补了两个配套机制：用内部 schema model 取代 DBMS-specific 的元数据查询接口；用 feature set 概括 bug-inducing case，把后续失败样例按“可能重复”来降优先级。也就是说，这篇论文的新意不是发明新 oracle，而是给现有 oracle 补上一层 portability layer。

## 设计

SQLancer++ 的中心是 adaptive statement generator。实现里覆盖了 6 类常见 statements、10 类 clause/keyword、58 个函数、47 个运算符和 3 种基础数据类型，还会记录系统更像动态类型还是严格类型。对于建库阶段特性，反复失败就会被关掉；对于 query 特性，论文用一个 Bayesian 成功率估计来判断是否继续保留。generator 还会先从浅表达式开始，逐步增加深度，以便更早识别不被支持的特性。

第二个关键设计是内部 schema model：成功执行的 `CREATE TABLE`、`CREATE VIEW` 会更新 SQLancer++ 自己维护的表、列和类型表示，后续生成直接查询这个内部模型。其上再接入两个 DBMS-agnostic 的 logic-bug oracle，TLP 和 NoREC。若 oracle 发现不一致，系统就保存对应的 feature set；如果历史 bug 的 feature set 是新样例的子集，新样例就被视为潜在重复项并降低优先级。

## 实验评估

实验最有力的地方是广度。作者在 18 个 DBMS 上做了大约四个月的密集测试，最终报告 196 个 bug，其中 140 个是 logic bug，180 个已被修复；很多目标系统，如 CrateDB、Dolt、RisingWave、Umbra、Virtuoso 和 Vitess，都不在 SQLancer 原本的支持范围内。论文也实证说明了“为什么需要自适应学习”：在 cross-DBMS feature study 里，只有 8% 的 bug-inducing tests 能在超过 90% 的 18 个系统上成功执行，整体跨系统有效率只有 48%。

反馈机制确实带来了明显收益。在 SQLite 上，有效率从无反馈时的 24.9% 提升到 97.7%；在 PostgreSQL 上，则从 21.6% 提升到 52.4%。SQLancer++ 在 SQLite、PostgreSQL 和 DuckDB 上的覆盖率仍低于手写 generator 的 SQLancer，但这个代价并没有让它失去价值：论文仍然报告了 SQLancer 漏掉的新 bug，包括 DuckDB 的 10 个和 SQLite 的 3 个。CrateDB 上的 prioritization 结果尤其有工程说服力：每小时超过 67K 个 bug-inducing cases 最终被压缩到 35.8 个优先处理样例，平均包含 11.4 个 unique bugs。

## 创新性与影响

相较于 _Rigger and Su (OSDI '20)_，这篇论文的新意不是新 oracle，而是给 oracle-based DBMS testing 补上一层 portability layer。相较于 _Liang et al. (USENIX Security '22)_，SQLancer++ 放弃 coverage guidance，换取更广的 DBMS 与实现语言适用性。它最直接的影响因此是实践层面的：让中小型 DBMS 团队不必先写出几千行方言 generator，也有机会接入 logic bug testing。

## 局限性

限制依然存在。SQLancer++ 目前只覆盖偏标准化的 SQL 子集，因此很多强 DBMS-specific 特性仍然触达不到；而且它对特性的建模大多是独立的，还没有显式表示互斥、依赖等更复杂关系。bug prioritizer 也是启发式方法，不是语义级去重器，所以既可能把不同 bug 合并，也可能把同一 root cause 拆成多类。最后，虽然移植成本已经显著下降，但每个新 DBMS 仍然需要基本的连接和运行时接线，平均约 16 行代码。

## 相关工作

- _Rigger and Su (OSDI '20)_ — SQLancer 证明了 oracle-based DBMS testing 能有效发现 logic bug，而 SQLancer++ 关注的是移除限制 SQLancer 扩展性的每库手写 generator 成本。
- _Rigger and Su (OOPSLA '20)_ — Ternary Logic Partitioning 提供了 SQLancer++ 直接复用的通用 logic-bug oracle，说明这篇论文的重点不在 oracle 设计本身。
- _Liang et al. (USENIX Security '22)_ — SQLRight 把 coverage-guided 思路带入 DBMS logic-bug testing，但没有解决跨 SQL 方言复用 generator 的问题。
- _Fu et al. (ASE '22)_ — Griffin 试图减少 DBMS fuzzing 对 grammar engineering 的依赖，但它主要面向 crash bug；SQLancer++ 则把重点放在 logic bug。

## 我的笔记

<!-- empty; left for the human reader -->
