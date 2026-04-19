---
title: "BESA: Extending Bugs Triggered by Runtime Testing via Static Analysis"
oneline: "BESA 把一次运行时触发的空指针解引用当作种子，沿调用栈反向找源变量，再顺着别名正向扩展，补出测试漏掉的同类 bug。"
authors:
  - "Jia-Ju Bai"
affiliations:
  - "Beihang University"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696089"
tags:
  - formal-methods
  - fuzzing
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

BESA 并不把运行时触发的空指针解引用当成终点，而是把它当成搜索种子。它先沿真实调用栈反向找出源赋值，再顺着别名、typestate 和可行路径正向扩展，于是能在不新增测试用例的前提下，从 25 个已知 bug 里再挖出 57 个额外 bug，其中 18 个是被开发者确认的新 bug。

## 问题背景

论文关心的不是 runtime testing 能不能抓到一个 bug，而是抓到之后还会漏掉多少同根同源的问题。fuzzing、组合测试、fault injection 以及带 sanitizer 的调试都能证明某条具体路径有错，但它们受覆盖率限制。少见的错误分支、另一条调用链上的同类使用点、或依赖特定上下文的空值传播，往往不会被这次运行踩到。

SQLite 的例子很典型。NPD1 和 NPD2 相隔 1.5 年才分别被报告，可它们的 buggy fields 其实别名到了同一条传播源。继续加测试不一定有效，因为缺的可能不是输入数量，而是那个少见执行情境；直接做整程序 static analysis 又会放大误报，因为可能别名的变量未必共享这次 crash 里的运行时状态。

## 核心洞察

作者的判断是，crash trace 正好补上了 static analysis 最缺的上下文。只要 runtime testing 告诉我们 buggy variable 和真实 call stack，静态分析就可以只沿这条栈反向恢复 source variables，再只在可行路径上搜索哪些变量会和同一份坏值建立别名关系。这样一来，目标就从泛化的 bug detection 变成了 bug extension：这次已经观察到的 NULL，还会在哪里再次出现？

## 设计

BESA 建在 LLVM bytecode 之上。它先完成编译并记录函数级元数据，再从 PoC 执行或 ASan/KASAN 风格 failure log 中抽取两项关键信息：buggy variable 和 crash call stack。

第一步核心分析是 backward propagation。BESA 从崩溃指令开始，只在真实出现过的调用栈里回溯赋值语句；跨函数时按参数位置映射回调用点继续向上找。为了保住结构体字段精度，论文用 access path 记录字段连接关系，再把被上游覆盖的 source instructions 去重。

第二步核心分析是 forward target tracking。对每个 source instruction，BESA 做跨过程、flow-sensitive、field-sensitive 的 dataflow analysis，维护一个 alias set，表示当前哪些变量还和 buggy variable 的关键字段共享别名。basic block 和 function 的 summaries 以 alias set 为键，专门用来剪掉重复遍历。即便找到了 target instruction，BESA 还要继续做两层过滤：先用 typestate 的 FSM 判断目标变量是否可能一直保持 NULL 到使用点，再用 Z3 检查路径是否可满足；两者都成立才报 bug。

## 实验评估

评估覆盖 25 个已知 null dereference：SQLite、VIM、GPAC 的 15 个应用层 CVE，加上 Linux kernel 的 10 个 bug。应用层 bug 通过真实 PoC 配合 ASan 和 BESA 复现；kernel bug 只分析 failure log。几套代码库从 20 多万行到 60 多万行不等，kernel 超过 2000 万行。

结果很直接。BESA 一共扩展出 57 个额外 bug，其中 33 个来自应用，24 个来自 kernel；有 18 个在评估时仍存活，作者提交后全部得到开发者确认。更关键的是，57 个额外 bug 里有 35 个不在原始 bug 所在函数里，这说明它真正抓住的是跨函数传播，而不是本地模式匹配。

补丁分析和效率结果进一步支撑论文主张。57 个额外 bug 里有 39 个后来已被提交修复，其中 36 个直接落在原 bug 的补丁系列里，说明 BESA 报出的常常是开发者最终也会承认的兄弟问题。性能上，完整 BESA 对每个 bug 的分析时间都低于 10 秒；去掉 summaries 之后，`BESA_NoSum` 在 25 个 bug 里有 10 个会在 300 秒超时，剩余 15 个平均也要 42 秒。对比 Clang Static Analyzer、Infer 和 CppCheck，这三者都没找到那 18 个新 bug。

## 创新性与影响

BESA 的新意，不在于再做一套独立的静态 bug detector，而在于把 runtime trace 变成静态分析的边界条件。过去的工作要么解释一次已经发生的失败，要么从源码上直接做 typestate 和 alias reasoning；BESA 则把第一次 crash 变成同一家族 bug 的入口。对 fuzzing 和 sanitizer 工作流来说，这很实用；对维护者来说，它也提醒你修掉第一个解引用点并不等于修掉根因。

## 局限性

BESA 的边界设得很清楚。它目前只支持 C 程序里单一 buggy variable 的 null-pointer dereference；buffer overflow、deadlock 这类多变量或并发型 bug 不在支持范围内。若没有可执行 PoC，输入还得是格式规整的 ASan 或 KASAN failure log。

另外，它的 static analysis 明确是不完备的。论文承认 callee 的 bottom-up 分析不完整，loop 和 recursive call 只展开一次，而且会主动跳过 global variable、非常量数组下标等难分析场景。这些选择帮助它控制误报，但代价是 recall 没法做强保证，更可能漏掉真实 bug。

## 相关工作

- _Bai et al. (TSE '21)_ - SDILP 也尝试从动态发现继续扩展 bug，但它只处理 data race，且主要依赖更简单的过程内、非别名分析；BESA 则把目标推进到 null dereference，并显式处理跨过程别名传播。
- _Li et al. (ASPLOS '22)_ - 该文用 path-sensitive、alias-aware typestate analysis 直接做 OS bug detection；BESA 借用了相近的静态分析味道，但先用真实 runtime failure 把搜索空间压窄。
- _Cui et al. (ICSE '16)_ - RETracer 关注的是如何解释一次已经发生的 crash；BESA 更进一步，把这份 trace 当作种子，继续找出尚未触发的额外 bug。
- _Rubio-González et al. (PLDI '09)_ - Error propagation analysis 研究的是错误值如何向前传播并被错误处理；BESA 的关键区别是先从已触发 bug 反推出 source，再顺着同一条坏状态去找别的使用点。

## 我的笔记

<!-- 留空；由人工补充 -->
