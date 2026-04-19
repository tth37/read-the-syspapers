---
title: "Themis: Finding Imbalance Failures in Distributed File Systems via a Load Variance Model"
oneline: "Themis 把 DFS 的请求和重配置统一成一条操作序列，再用负载方差引导 fuzzing 持续放大节点差异，从而抓到不会自行恢复的失衡故障。"
authors:
  - "Yuanliang Chen"
  - "Fuchen Ma"
  - "Yuanhang Zhou"
  - "Zhen Yan"
  - "Qing Liao"
  - "Yu Jiang"
affiliations:
  - "KLISS, BNRist, School of Software, Tsinghua University"
  - "Harbin Institute of Technology"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696082"
code_url: "https://anonymous.4open.science/r/Themis-97C4"
tags:
  - filesystems
  - storage
  - fuzzing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Themis 盯住的不是普通 crash 或语义错误，而是另一类更难测的 DFS 故障：系统明明跑过 rebalance，节点负载却还是长期失衡。它把请求和重配置压成短操作序列，用负载方差而不是纯 coverage 做反馈，再通过强制 rebalance 做确认，最后在 4 个 DFS 上挖出 10 个新故障。

## 问题背景

论文先回头分析了 HDFS、CephFS、GlusterFS 和 LeoFS 里的 53 个真实失衡故障。结果说明这不是边角问题：82% 会影响整个系统或大多数节点，表现包括性能崩塌、不可用、崩溃和数据丢失。更关键的是，83% 的故障必须把两类输入叠在一起才能触发，既要有 create、delete、append 这类请求，也要有扩缩容、节点上下线之类配置变化。

现有工具大多只覆盖其中一半。SmallFile、Filebench 会把文件操作压得很猛，但配置基本不动；CrashFuzz、Mallory 更擅长 fault injection 和配置扰动，却没有把工作负载依赖建模好；Janus、Hydra 虽然会探索两个输入维度，但它们是在两个空间之间切换，而不是搜索那些短时间内交织发生的请求与重配置。检测也不容易，因为 DFS 追求的是大致均衡，不是绝对相等，瞬时偏差本身并不能直接等于 bug。

## 核心洞察

Themis 的核心判断是：失衡故障不是一次性爆出来的，而是很多次轻微偏差慢慢累积出来的。既然故障路径本来就在持续放大节点间差异，那么更合理的反馈信号就不是单纯的新 coverage，而是这条测试序列有没有继续扩大负载方差。

输入抽象也因此要改成统一序列。把 create、append、delete、add/remove node、expand/reduce volume 放进同一条操作序列后，fuzzer 搜索的就是故障真正依赖的执行顺序。最后再用持久性做判据：如果系统在 Themis 显式触发 rebalance 且确认完成之后，仍然超过失衡阈值，那更像是实现错误，而不是短暂波动。

## 设计

Themis 分成 Test Case Generator 和 Imbalance Detector 两部分。输入模型覆盖 17 类与负载相关的操作，分成 file、node、volume 三类；每个测试用例是长度 1 到 8 的操作序列，这个上限直接来自前面对 53 个历史故障的观察。文件名、节点 ID、文件大小都不是瞎填，而是参考当前文件树、节点列表和剩余空间来实例化，好让测试更容易撞上 rebalance 的边界场景。

变异策略本身并不复杂，还是 replace、delete、insert 三类，只是种子保留标准换成了失衡语义。每轮执行后，Themis 采集各节点的 CPU、网络请求与读写、存储占用，再把这些差异合成为 load variance model；能继续放大方差的序列，或触发候选故障的序列，会被优先留下。detector 则分别检查 computation、network、storage 三类失衡，用阈值 `t` 判断最热节点是否已经明显高于平均值。为了避免因为不同 DFS 的 rebalance 时机不同而误报，Themis 还会显式调用 rebalance API，等 rebalance state API 返回完成后，再把同一条序列重放一次；如果失衡还在，才算真故障。适配新 DFS 的成本也比较低，作者认为主要只需补 `operation.send()` 和 `LoadMonitor()` 两个接口。

## 实验评估

实验对象是 10 节点 Docker 集群里的 HDFS v3.4、CephFS v18.0.0、GlusterFS v12.0 和 LeoFS v1.4.4，单次实验运行 24 小时。Themis 共执行 60,000 多个操作，发现 10 个新故障，其中 GlusterFS 4 个、LeoFS 3 个、CephFS 1 个、HDFS 2 个；最强的基线只找到 4 个。历史故障复现也一样，53 个已知失衡故障里，Themis 能复现 48 个，而其他方法只能复现 9、11、16、21 或 23 个。

消融结果很说明问题。去掉 load variance model 后，新故障发现数从 10 个掉到 5 个，分支覆盖率也少了 11%。和固定请求、固定配置、交替探索、并发生成这四类基线相比，Themis 的分支覆盖率高出 10% 到 21%。阈值 `t` 也很敏感：25% 在这 4 个 DFS 上能把 false positive 压到 0 且不漏报，20% 还会误报，30% 则开始漏掉真实故障。

## 创新性与影响

这篇论文的新意不在于提出新的 DFS 负载均衡算法，而在于把失衡故障这类长期存在、却很难系统化测试的问题，收敛成一套专门流程。统一操作序列、负载方差引导、以及 rebalance 之后仍失衡才上报，这三个选择放在一起，才构成了它真正的新东西。

它对 DFS 维护者和系统测试研究者都很有价值。前者需要能提前发现生产环境里才会变成热点和停机的问题；后者则能从中看到，fuzzer 的目标函数如果贴着 bug 语义设计，收益会比追求泛化的新执行路径更大。

## 局限性

它最明显的局限还是 detector 的假设。论文默认节点大体同构，因此更适合比较同构集群里的相对负载；如果问题来自硬件异构、设备波动或平台差异，这套判据就未必稳。阈值 `t` 也是经验参数，25% 在这 4 个系统上最好，但不是从更一般的理论推出来的。

另外，自动化只覆盖到发现阶段，重放、定位根因和去重仍然要靠人工。CPU、网络、存储三类方差现在也是等权相加，作者自己也承认这只是第一版模型；他们的初步实验已经说明，调高存储方差权重后，存储失衡的触发时间能从 498 分钟缩短到 302 分钟。最后，Themis 只处理 imbalance failure，不覆盖 metadata inconsistency、fail-slow 等其他 DFS 缺陷。

## 相关工作

- _Xu et al. (S&P '19)_ - Janus 会探索两个输入维度，但它是在两个维度之间切换，而不是把请求和重配置合成同一条可执行序列。
- _Kim et al. (SOSP '19)_ - Hydra 针对的是文件系统语义错误；Themis 则专门瞄准分布式文件系统里的负载失衡故障，并把持续存在的跨节点偏差当成 oracle。
- _Gao et al. (ICSE '23)_ - CrashFuzz 用 coverage 引导集群 fault injection，不过它默认工作负载固定，因此抓不住很多请求与配置之间的触发依赖。
- _Meng et al. (CCS '23)_ - Mallory 通过时间线驱动的 fault injection 测试分布式系统，而 Themis 优化的是 DFS 特有的负载方差，并要求 rebalance 之后仍失衡才确认失败。

## 我的笔记

<!-- 留空；由人工补充 -->
