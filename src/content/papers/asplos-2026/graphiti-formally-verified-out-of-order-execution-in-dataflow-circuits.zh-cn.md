---
title: "Graphiti: Formally Verified Out-of-Order Execution in Dataflow Circuits"
oneline: "用 refinement 检查的图重写框架把顺序 dataflow 循环改写成带标签的乱序电路，同时基本保留了既有未验证方案的性能收益。"
authors:
  - "Yann Herklotz"
  - "Ayatallah Elakhras"
  - "Martina Camaioni"
  - "Paolo Ienne"
  - "Lana Josipović"
  - "Thomas Bourgeat"
affiliations:
  - "EPFL, Lausanne, Switzerland"
  - "ETH Zurich, Zurich, Switzerland"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790166"
project_url: "https://zenodo.org/records/18328388"
tags:
  - hardware
  - verification
  - compilers
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Graphiti 给 dynamic HLS 提供的不是又一个“经验上看起来可行”的图优化，而是一套形式化重写底座。它在 Lean 4 中定义 dataflow 图的 refinement 语义，证明重写引擎健全，并验证把顺序循环改写成带 `Tagger/Untagger` 的乱序循环这一关键 rewrite。作者在 FPGA 基准上表明，该方案保留了既有未验证乱序方法的大部分收益，同时暴露出后者真实存在的一个编译错误。

## 问题背景

dynamic HLS 已经能把不规则 C 程序映射成 latency-insensitive 的 dataflow 电路，但下一步性能提升往往依赖重叠循环迭代、重排工作和利用可流水化算子。问题在于，这些优化本身也是最难信任的部分。一个局部看来合理的 rewrite，可能悄悄引入新行为，或者破坏 loop-carried state 的语义前提。

论文研究的是怎样在 dynamic HLS 生成的循环中安全启用 out-of-order execution。已有工作表明，把循环入口 `Mux` 改成无条件 `Merge`，再包一层 `Tagger/Untagger`，就能让多个循环实例重叠；但这个变换没有机械化正确性证明。

## 核心洞察

论文的核心判断是：只要给 dataflow 电路建立模块化 refinement 语义，dynamic HLS 里那些激进 rewrites 就可以被形式化验证。Graphiti 判断一条 rewrite 是否正确，不是看两边结构是否相似，而是证明右侧是否 refine 左侧，也就是优化后可以收紧行为，但不能凭空制造新行为。

这个视角让乱序循环优化变得可处理。作者先把循环规整到可推理的形状，让循环体收缩为单个 `Pure` 组件，再只对该形状证明一个参数化 loop rewrite；更大图中的实际应用则交给通用 rewrite engine 完成。

## 设计

Graphiti 有两层图表示。`ExprHigh` 接近前端 HLS 工具输出的 dot graph，方便做匹配；`ExprLow` 是为证明设计的归纳式图语法，由基础组件、product 和显式 connection 构成，经过验证的 rewriting function 运行在这一层。每个组件都被解释成一个 module，包含输入、输出、内部迁移和初始状态；整张图的语义则通过组合这些 module 并把连线折叠成内部迁移来获得。

真正的乱序优化是一条 rewrite 管线。19 条辅助 rewrites 负责把循环规整到标准形：合并重复的 `Mux`/`Branch`，消除中间性的 `Join`/`Split`，并把任意循环体压缩成单个 `Pure` 节点。被形式化验证的是核心 rewrite：它适用于“一个 `Mux`、一个 `Branch`、中间是 `Pure` 函数 `f : T -> T x Bool`”的循环，把入口 `Mux` 改成带标签的 `Merge`，插入 `Tagger/Untagger`，从而允许多个循环实例并发执行，同时在循环出口恢复输入顺序。

证明的难点不只是局部等价。作者先证明顺序循环确实实现了“不断应用 `f`，直到布尔退出条件为假”，再为乱序循环建立不变量：值不重复、tag 顺序保持、所有在飞值都能追溯到原始输入。最终的 simulation relation 就建立在这些不变量上。

## 实验评估

实现上，作者把 Graphiti 插进了 Dynamatic 流程：导入 Dynamatic 的 dot graph，用 Graphiti 执行 rewrites，再导回 dot，并继续复用 Dynamatic 做 buffer placement 和 VHDL 生成。实验平台是 Kintex-7 FPGA，时钟目标为 4 ns，比较对象包括 in-order dynamic HLS（`DF-IO`）、已有未验证乱序 dataflow 方法（`DF-OoO`）、Graphiti，以及 verified static-scheduling HLS 编译器 Vericert。

从 geomean 看，Graphiti 的 execution time 为 `47,335 ns`，`DF-IO` 为 `100,095 ns`，Vericert 为 `275,336 ns`。也就是说，Graphiti 相比 in-order dynamic baseline 约快 `2.1x`，相比 verified static-scheduling baseline 约快 `5.8x`。相较 `DF-OoO`，它多数 benchmark 已经接近，但有时会因为规范化 rewrites 引入额外同步而稍慢。

最有说服力的结果其实不是速度，而是 formalization 真正发现了 bug。作者证明时发现，既有未验证方案对 `bicg` 的变换并不安全，因为循环体里仍保留了 store，直接乱序会破坏内存状态一致性。

## 创新性与影响

相较于 _Elakhras et al. (FPGA '24)_，Graphiti 的贡献不在 tag 化乱序循环这个想法本身，而在于把它改写成建立在 refinement semantics 上的 verified graph rewrite。相较于 Vericert，论文处理的是更棘手的对象：带局部 nondeterminism 和重排行为的 dynamically scheduled dataflow 电路。相较于纯语义化工作，Graphiti 进一步补上了编译器真正需要的层次：rewrite engine，以及“局部 rewrite 可以组合”为全局正确性的证明。

这给 dynamic-HLS 研究者提供了一条让激进图优化更可信的路径。`bicg` bug 也说明了它的实践价值。

## 局限性

论文的验证故事还不是端到端闭环。被证明正确的是 rewrite engine 和那条参数化核心 loop rewrite，但用于规范化循环、构造 `Pure` 体的大多数辅助 rewrites 仍未验证，rewrite 放置策略也依赖外部 oracle。因此，这更像一个“部分验证”的优化流水线，而不是 fully verified 的 dynamic-HLS compiler。

它的成本和覆盖面也仍有限。整个 Lean 开发约 15.8k 行、耗时约一人年，而评估基本沿用了前一篇乱序 dataflow 论文的 irregular-loop benchmark；像 `img-avg` 这种需要另一类 branch-reordering 变换的例子就还没有被纳入。

## 相关工作

- _Elakhras et al. (FPGA '24)_ — 提出了 Graphiti 所重新表达并部分纠正的 tagged out-of-order dataflow 变换。
- _Herklotz et al. (OOPSLA '21)_ — Vericert 验证的是 statically scheduled hardware 的 HLS，而 Graphiti 面向带重排的 dynamically scheduled dataflow 电路。
- _Law et al. (OOPSLA '25)_ — Cigr/Cilan 提供了 dataflow 电路的 mechanized semantics，但 Graphiti 更进一步，把 rewrite 组合性和 refinement 证明纳入优化流程。
- _Lin et al. (OOPSLA '24)_ — FlowCert 做的是到异步 dataflow 的 translation validation，而 Graphiti 证明的是 dynamic-HLS 流程内部的局部电路 rewrites。

## 我的笔记

<!-- 留空；由人工补充 -->
