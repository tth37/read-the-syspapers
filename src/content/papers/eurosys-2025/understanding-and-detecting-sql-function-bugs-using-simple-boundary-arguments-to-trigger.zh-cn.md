---
title: "Understanding and Detecting SQL Function Bugs: Using Simple Boundary Arguments to Trigger Hundreds of DBMS Bugs"
oneline: "Soft 把 SQL function 测试重心放到边界参数合成上，用字面量、类型转换和嵌套函数三类模式，在 7 个 DBMS 中挖出 132 个新 bug。"
authors:
  - "Jingzhou Fu"
  - "Jie Liang"
  - "Zhiyong Wu"
  - "Yanyang Zhao"
  - "Shanshan Li"
  - "Yu Jiang"
affiliations:
  - "KLISS, BNRist, School of Software, Tsinghua University, China"
  - "National University of Defense Technology, China"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696064"
tags:
  - databases
  - fuzzing
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文的判断很明确：built-in SQL function 里的崩溃类漏洞，大多数不是整条查询语句特别离奇，而是参数刚好落在边界上时，函数实现没处理好。作者先从 318 个历史 bug 中抽出 10 类边界参数生成模式，再把这些模式做成 Soft，最终在 7 个 DBMS 里找到 132 个已确认的新 bug。

## 问题背景

SQL function 不是数据库里的边缘功能，而是日常查询、格式转换、聚合和类型处理的基础设施，所以一旦这里出错，影响面和危险性都很高。论文举的例子很直接：PostgreSQL 自 2004 年以来公开过 121 个 CVE，其中 31 个直接来自 built-in SQL function，而且这批漏洞的平均 CVSS 分数还高于 PostgreSQL 整体平均值。只要上层应用把 regex、JSON、XML 或格式化能力暴露给用户，攻击者就可能靠一组特制参数把后端 DBMS 打进错误路径。

现有方法对这个问题又并不贴合。传统 library testing 关注对象之间的调用序列；SQL function 则是嵌在 SQL expression 里的，行为高度依赖参数格式、隐式类型转换和嵌套结构。通用 DBMS fuzzing 虽然能探索 clause、query shape 和 optimizer 路径，但它们主要在整条语句层面发力，并不会系统性地构造那种既语义上成立、又刚好逼近实现边界的 function arguments。

## 核心洞察

这篇论文最值得记住的观点是：要测 SQL function，不必先生成特别复杂的 SQL，而要先搞清楚边界参数从哪里来。作者分析 318 个历史 bug 后发现，87.4% 的问题都能归结为参数边界值处理不当，而这些边界值主要只来自三条路径：字面量、类型转换结果、以及嵌套函数返回值。再加上一条经验事实，87.5% 的触发语句里函数表达式数量不超过两个，于是测试空间一下就收缩了。

这也是为什么模式化生成能奏效。对 SQL function 来说，真正脆弱的地方常常不是语法树有多深，而是数值范围、字符串结构、长度、递归深度或内部类型状态是否压到了边界。只要把这些边界来源固定下来，测试就能从无目标随机生成，变成更像 domain testing 的定向构造。

## 设计

Soft 的起点不是 mutator，而是一轮手工 bug study。作者先从 PostgreSQL、MySQL 和 MariaDB 的公开 tracker 中，用 crash、signal 等关键词捞出 14,111 个候选报告，再结合 PoC、backtrace 和补丁把它们缩到 318 个真正的 built-in SQL function bug。由此得到几条后续设计直接依赖的统计结论：能定位阶段的 bug 里，70.0% 发生在 execution 阶段；string function 和 aggregate function 占了超过 40% 的触发函数出现次数；47.5% 的 bug 需要先建表并插入数据，而 41.5% 完全不依赖表即可触发。

在这些观察之上，论文把 10 个模式归成三组。P1 负责 boundary literals，包括极端整数和小数、空串、`NULL`、`*`，以及对 JSON、IP、hex、regex 这类结构化字符串做保格式扰动。P2 负责 boundary type castings，包括显式 `CAST`、借 `UNION` 触发的隐式类型转换，以及跨函数传参造成的类型错配。P3 负责 nested functions，比如借 `REPEAT` 造极长或极深的值，或者用另一个函数包裹、替换原有参数，让边界值通过返回值传播进目标函数。

Soft 的实现就是把这些模式接到真实函数表达式上。它先扫描 DBMS 文档和 regression tests，提取真实存在的函数名与 `func(...)` 形式的表达式，再按模式改写参数，把新表达式塞回 SQL 语句并通过 Python client 执行。实现里还有一个关键收缩策略：一旦表达式里已经超过两个函数，Soft 就不再继续扩展，因为历史数据表明，多数真实 bug 根本不需要更深的嵌套。

## 实验评估

实验结果很硬。Soft 在 Ubuntu 20.04 的 128 核 EPYC 服务器上，分别测试 PostgreSQL 16.1、MySQL 8.3.0、MariaDB 11.3.2、ClickHouse 23.6.2.18、MonetDB 11.47.11、DuckDB 0.10.1 和 Virtuoso 7.2.12。两周内它总共找到 132 个新 bug，其中 PostgreSQL 1 个、MySQL 16 个、MariaDB 24 个、ClickHouse 6 个、MonetDB 19 个、DuckDB 21 个、Virtuoso 45 个；全部都被厂商确认，论文写作时已有 97 个被修复。

覆盖率对比也解释了为什么它能挖到这些 bug。24 小时内，Soft 在支持范围内一共触发 2,956 个 built-in SQL functions，而 Sqirrel、SQLancer、SQLsmith 分别只有 74、202、446 个；按共同支持的 DBMS 计算，Soft 分别多触发 984、1567、181 个函数。built-in SQL function 模块的 branch coverage 也明显更高，论文给出的增幅分别是相对 Sqirrel 的 433.93%、相对 SQLancer 的 98.70%、相对 SQLsmith 的 19.86%。作者还把各工具生成的 query 重新统一执行，以减少 coverage 统计口径不同带来的偏差。

这些结果基本支撑了论文的中心主张：对 SQL function 这类目标，围绕 boundary arguments 做定向生成，确实比面向整条查询的通用 fuzzing 更贴题。需要补一句的是，baseline 都是通用 DBMS testing tools，而不是专门为 SQL function 写的工具。论文也很坦率地写出，Soft 会因为超大 `REPEAT` 参数产生 7 个 false positives，并额外触发 14 个 assertion failures。

## 创新性与影响

这篇论文的创新点，不只是又做了一个 DBMS fuzzing tool，而是把漏洞研究和生成策略直接焊在一起。以往很多 DBMS testing 工作的焦点是查询结构、变异策略或 correctness oracle；Soft 则把问题收缩到 built-in SQL function 的参数边界，并证明这个收缩不是拍脑袋，而是有 318 个历史 bug 支撑的。这个思路既像 domain testing，又保留了 DBMS fuzzing 的工程可落地性。

它的影响也会比论文表面范围更广。对 DBMS 开发者来说，这 10 个模式相当于一套函数实现的健壮性清单；对测试研究者来说，它说明抓住 type system、format parser 和 nested function 之间的边界传播，短小 SQL 也能打到很深的执行路径；对安全方向来说，论文进一步提醒大家，built-in SQL function 本身就是攻击面。

## 局限性

作者研究的是 crash 类问题，而不是返回错误结果的 correctness bugs，所以 Soft 的模式天然更擅长找 memory safety 和 robustness 问题，不擅长发现语义错误。公开语料本身也有偏差：一些高危安全漏洞不会出现在公开 tracker 里，而是直接走厂商的私有安全流程，因此论文对最严重漏洞的统计并不完整。

另外，历史 bug study 只覆盖 PostgreSQL、MySQL 和 MariaDB，虽然 Soft 后续在 7 个 DBMS 上展示了可迁移性，但它对其他 query language 或更特殊的 type system 能泛化到什么程度，论文并没有真正回答。实现层面上，Soft 把嵌套深度限制在不超过两个函数，所以更深链条上的 interaction bugs 可能直接被排除在搜索空间之外。再加上评测里缺少一个真正的 SQL-function-specialized baseline，所以论文更像是在证明方向有效，而不是证明这已经是最优做法。

## 相关工作

- _Zhong et al. (CCS '20)_ - Squirrel 通过 IR 级变异维持 SQL 合法性，但它没有把 boundary-valued function arguments 当作一等生成目标。
- _Rigger and Su (OSDI '20)_ - Pivoted Query Synthesis 主要服务于 DBMS correctness bugs 的 oracle 构造，而 Soft 面向的是 built-in SQL function 内部的 crash 与安全问题。
- _Fu et al. (ASE '22)_ - Griffin 解决的是更广义的 grammar-free DBMS fuzzing，Soft 则把范围收窄到 function expressions，并用人工归纳的 bug taxonomy 换来更强的针对性。
- _Fu et al. (ICSE '24)_ - Sedar 强调为 DBMS fuzzing 提供更好的 seeds，而 Soft 的核心贡献是沿着 literal、cast 和 nested-function 三类边界模式系统性改写参数。

## 我的笔记

<!-- 留空；由人工补充 -->
