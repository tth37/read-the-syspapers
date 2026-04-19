---
title: "Moko: Marrying Python with Big Data Systems"
oneline: "Moko 把普通 Python 数据科学脚本拆成多域 IR，再把跨系统的数据兼容性写成 trait lifting，让同一份脚本能自动拼接最合适的大数据后端。"
authors:
  - "Ke Meng"
  - "Tao He"
  - "Sijie Shen"
  - "Lei Wang"
  - "Wenyuan Yu"
  - "Jingren Zhou"
affiliations:
  - "Alibaba Group"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3696100"
tags:
  - compilers
  - pl-systems
  - databases
  - graph-processing
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Moko 是一个尽量不改 Python 写法的执行框架：它先把脚本提升成面向 SQL、图、学习和数据对齐的 MLIR dialect，再做 idiom rewrite，并把后端选择与格式转换放到同一个优化器里统一搜索。论文报告的结果是，端到端任务最高可加速 11x，数据对齐开销最高可降低 28x，而且比作者手工拼接的多系统流水线还快 2.5x。

## 问题背景

这篇论文要解决的是一个很现实的断层：大家愿意写的是 Python，因为 Pandas、Torch、NetworkX 让表、张量、图能放在同一份脚本里，再配上灵活控制流，写起来很自然；但数据一旦上到分布式规模，就不得不把不同阶段交给 Spark、Dask、GRAPE、Torch 之类的专用系统。问题在于，这些系统的 API、执行模型和专有数据格式彼此割裂，Python 在单进程里的便利到了集群上就不成立了。

现有办法都只补了一部分。wrapper 保住了语法，却把用户锁进单一后端生态；编译器能加速局部 Python 代码，却不会替你协调分布式表、图和张量；workflow optimizer 会做跨系统搜索，但默认输入更像静态 DAG，而不是原生 Python。工业界最常见的补救还是手工拼接：每段挑一个最快系统，把中间结果序列化、转换，再靠胶水代码接起来。论文认为真正耗时的往往就是这层胶水，而不是算子本身。

## 核心洞察

Moko 的关键判断是，Python 扩展到大数据场景，不能只靠 wrapper 或局部编译，而要把它当成「整段程序语义下沉 + 数据格式搜索」的问题。可优化的 Python 片段先被提升成 domain-aware IR，优化器看到的就不再只是库调用，而是 SQL 算子、图算法、学习算子和对齐步骤；专有格式的能力一旦被拆成可组合的 trait，跨系统共享数据也就从人工胶水变成了搜索空间的一部分。

这点重要，是因为端到端最优通常不是每一步都选最快系统就够了。某个后端单看自己很快，可能因为输出格式太别扭，反而把下一步拖慢；循环里的多次图查询也未必要逐次执行，完全可以重写成一个更合适的多源原语。Moko 的做法就是把后端选择、程序改写和数据对齐一起决定，识别不了的部分再退回 Python。

## 设计

Moko 的结构分成四层：IR layer、generator、optimizer 和 runtime。前端先把 Python 编成 MLIR dialect。论文具体实现了 SQL IR、graph IR、learning IR，以及处理 load、store、convert 的 alignment IR；generator 再把这些 IR 组织成任务并生成后端驱动代码。

在此基础上，Moko 做 idiom recognition 和 rewriting。它先匹配控制流模式，再匹配数据模式，从脚本里找出具有明确语义的片段。论文里的例子是循环调用 `nx.shortest_path`：如果后端支持，Moko 会把它改写成一个 multi-source shortest path；识别不到或者无法安全改写的代码，就继续交给 Python 解释器。跨系统数据共享则被建模成 trait lifting。格式先声明能力，Moko 再搜索从源格式到目标格式的 trait path；路径既可以是 method sharing，也可以是 sort、transpose、repartition 或布局构建这样的 physical conversion。

最后由优化器统一挑执行路径。论文用 `g` 估算计算代价，用 `h` 估算经 execution frame 做 load/store 的代价，两者都靠离线 profiling 校准；在线则枚举 physical plan，并在每个任务完成后根据真实 cardinality 与运行时间重新规划剩余部分。runtime 本身不重新发明执行引擎，而是调度 Spark、Dask、GRAPE、GraphX、Torch、TensorFlow 等已有系统，再用 Vineyard 或外部存储承接中间结果。

## 实验评估

原型大约 38 KLoC C++，实验平台是 16 节点的 AliCloud Kubernetes 集群，每节点 16 核、32 GB 内存。

最关键的是三个真实流水线。Fraud detection 里，Moko 用 Spark 做特征提取，用 Torch 做 RGCN 推理，并直接在 Spark dataframe 上模拟 GRAPE 方法，同时把多次 SSSP 合并成一个 multi-source shortest path，最终相对原始 Python 加速 11x，相对 hand stitching 加速 2.5x，内存为基线的 142.3%。Image-based recommendation 里，它引入 Dask 并行预排序 KNN 边，把图加载阶段压下来，所以比 Python 快 8.5x，比 hand stitching 快 1.5x，峰值内存是 100.8%。Who-to-follow 里，它把 common neighbors 留在 Dask 里计算，不再把图导出到另一套系统，因此相对 Python 和 hand stitching 分别快 3.5x 和 1.4x，内存为 122%。

微基准说明同一个工作负载族内部也不存在通吃的冠军。TPC-H `Q6` 更适合 Dask 和 ClickHouse，`Q17` 更适合 Presto；图算法和 Skip-gram 训练的优胜者也会随输入变化。Vineyard 把文件系统 round-trip 的 I/O 和序列化成本基本拿掉；alignment fusion 可以减少约 70% 的对齐开销；针对 BFS 选择合适图布局最多能再省 42% 运行时间。大规模 LDBC SNB 上，Moko 相对 hand stitching 在 100 GB、300 GB 和 1 TB 数据集上分别快 31%、39%、44%；跟 RHEEM 和 Musketeer 比，在 cross-community PageRank 上快 5x 和 27x，在 AML 工作流上也还有 2.9x 和 3.2x 的优势。论文没有单独量化的，是 `g`、`h` 代价模型本身的误差。

## 创新性与影响

Moko 的新意不在于再做一个 Python wrapper，也不在于把某个局部 UDF 编得更快，而在于把四件常被拆开的事情揉成了一个系统：面向领域的 MLIR dialect、基于 idiom 的程序改写、基于 trait 的格式对齐，以及把后端选择和转换路径一起搜索的整体优化器。它因此对跨引擎数据平台、MLIR 型编程系统，以及想保留 Python 前端的大数据系统都有参考价值。

## 局限性

论文没有回避原型的边界。当前系统只覆盖三个领域，主要面向 `pandas`、`networkx`、`torch` 三类包；类、generator expression、`try`/`except`、decorator、`async` 都还不支持，只能退回解释器，所以真实应用里到底有多少代码能受益，强依赖工作负载。

另一个限制是集成成本并不低。每接一个后端，都要补 wrapper、等价操作、代码模板和代价校准。论文给出的数字是单个后端需要 1-5 小时，整套实验环境累计 27 小时。再加上最亮眼的比较对象主要还是作者自己写的 hand-stitched pipeline 和少数 workflow manager，所以这些速度提升更像很有说服力的研究证据，而不是对所有生产环境都成立的终局结论。

## 相关工作

- _Agrawal et al. (VLDB '18)_ - RHEEM 也做跨平台数据处理搜索，但它假设输入是 workflow 计划，而不是带动态控制流的原生 Python，更没有把专有格式对齐建成核心优化对象。
- _Gog et al. (EuroSys '15)_ - Musketeer 同样会把一个逻辑工作流映射到多个执行引擎；Moko 的不同之处在于它直接从普通 Python 出发，并把数据转换纳入搜索空间。
- _Spiegelberg et al. (SIGMOD '21)_ - Tuplex 把 Python 分析代码编到接近原生速度，但它不负责协同分布式 SQL、图和学习系统，也不处理跨系统中间结果对齐。
- _Palkar et al. (CIDR '17)_ - Weld 提供统一 IR 和 runtime 来优化数据分析程序，而 Moko 保留现成后端系统，把重点放在跨系统 dispatch 与 alignment 上。

## 我的笔记

<!-- 留空；由人工补充 -->
