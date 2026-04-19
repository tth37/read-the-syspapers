---
title: "Impeller: Stream Processing on Shared Logs"
oneline: "Impeller 把共享日志里的 tag 直接变成 progress marker，让算子只靠一次追加就能同时提交多个下游子流的处理进度，避开 Kafka 式事务协调。"
authors:
  - "Zhiting Zhu"
  - "Zhipeng Jia"
  - "Newton Ni"
  - "Dixin Tang"
  - "Emmett Witchel"
affiliations:
  - "Lepton AI Inc."
  - "Google LLC"
  - "The University of Texas at Austin"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717485"
code_url: "https://github.com/ut-osa/impeller-artifact"
tags:
  - fault-tolerance
  - storage
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Impeller 是一个建在 shared log 之上的分布式流处理器。它把 progress marker 也写进日志，并给同一条 marker 打上多个 tag，让一个算子能用一次追加同时提交多个下游 substream、task log 和 change log 的进度，从而在不引入 Kafka 式事务协调器的前提下实现 exactly-once。基于 NEXMark 的结果是，相比 Kafka Streams，它的 p50 延迟可降低 1.3×-5.4×，或把饱和吞吐提高 1.3×-5.0×。

## 问题背景

流处理要做 exactly-once，最棘手的不是平时算数据，而是故障总发生在中间态。一个 task 可能已经消费了输入、改了本地状态，却还没把所有下游输出完整而一致地提交出去。放到分布式 DAG 里，这个问题更明显：一个输入会扇出到多个下游 substream，系统恢复时不仅要知道自己读到哪里，还得知道哪些输出和哪些状态变更已经构成正式结果，哪些只是半途留下的副作用。

现有路线各有明显代价。checkpointing 或 aligned checkpoint 的恢复逻辑最直接，但状态一大，正常路径就会被快照写入拖慢；Kafka Streams 用 logging 加 checkpoint 来减轻快照压力，可它仍然得额外协调已处理输入位置、状态更新和多条输出流的原子提交。论文真正追问的是：既然现代 shared log 已经给了 total order、selective reads 和 string tags，能不能把这部分协调直接下沉到日志里，而不是在流处理系统上层再搭一套事务协议。

## 核心洞察

论文最关键的判断是，进度本身就可以编码成一条原子追加的日志记录。如果一个 task 写出的 progress marker 同时带上所有相关下游 substream 的 tag，再加上自己的 task log tag，那么这条记录就成了多个逻辑流上的一致切面。下游只有在看到上游 marker 之后，才把对应输出当成已提交结果；原本需要两阶段协议才能完成的多流原子提交，就被收敛成了一次 append。

对 stateful operator，这个思路只需要再补上一条 change log。只要 progress marker 记录输入、输出和 change log 的 LSN 范围，恢复时就能重建一个一致前缀。shared log 的 total order 在这里尤其重要，因为进度可以用标量 LSN 表示，不必再维护更重的每流元数据或向量状态。

## 设计

Impeller 把一个 query 切成多个 stage 和 task。每个 stream 再分成若干 substream，日志记录通过类似 `(X, 2a)` 的 tag 指明应由哪个消费者任务读取，任务依靠 selective reads 只拉自己的那一段，而不需要为数据流图里的每条边单独准备物理日志。

无状态任务会周期性写出 progress marker，里面记录自己已经处理到的输入范围，以及由这批输入生成的输出范围。marker 本体只追加一次，但会同时打上所有下游 substream 的 tag，以及 `(T, task id)` 这个 task log tag。于是即便一个算子把同一份输入扇出到多个输出子流，下游也能在逻辑上看到同一个提交点。

有状态任务还会把状态更新写入 `(C, task id)` 标记的 change log。运行过程中，它可能先读到一些上游尚未确认的记录，所以需要先缓冲，再根据上游 progress marker 把这些记录分成 committed、uncommitted 和 unknown 三类。恢复时，任务先从 task log 找到最近一次 marker；如果有最近的 checkpoint，就从 checkpoint 开始，否则从头回放 change log 到该 marker。Zombie task 的处理同样依赖 shared log：task manager 在日志元数据里维护每个 task 的 instance number，再用 conditional append 保证只有最新实例能够提交 progress marker。异步 checkpoint 只是进一步缩短恢复时间，流数据、task log 和 change log 的真相来源仍然是 shared log。

## 实验评估

实现规模约为 16,895 行 Go，底层使用 Boki，并支持 scan、filter、map，以及 groupby、aggregate、stream-stream join、stream-table join、table-table join 等 stateful operator。实验部署在 13 台 EC2 c5d.2xlarge 上：4 台存储、4 台输入生成、4 台计算、1 台控制平面。

论文先做了一个很重要的对照：Boki 并不是天然比 Kafka 更低延迟的传输层。对于 16 KiB 的 append-to-consume 测试，Impeller 的日志在 p50 上反而比 Kafka 慢 1.3×-1.8×，所以后面的端到端优势不能简单归因于「底层日志更快」。到了 NEXMark，最简单的无状态 Q1、Q2 上，Impeller 和 Kafka Streams 的 p50 很接近；但在 stateful 的 Q3-Q8 上，Impeller 的 p50 延迟低 1.3×-5.4×，p99 低 1.2×-5.7×。如果把 p99 控制在 1 秒以内，它还能支撑 1.3×-5.0× 更高的输入吞吐。和在 Impeller 内实现的 aligned checkpoint 基线相比，progress marker 最多可把 p50 再降 4.5×、把 p99 降 5.8×。Q8 的故障恢复也明显受益于异步 checkpoint：恢复时间从 3.858-4.758 秒降到 0.270-0.297 秒，约快 14×-16×。

## 创新性与影响

Impeller 的新意不只是把流处理放到另一种存储层之上。真正新的地方，是把 tagged shared-log record 直接变成 exactly-once 的提交协议，让 Kafka Streams 里分散在 coordinator、transaction stream 和多条 bookkeeping 流里的工作，收敛成一个由日志语义驱动的统一机制。

这件事对 shared log、容错 dataflow 和低延迟 exactly-once 系统都很有启发。论文证明了日志系统里原本看起来像存储接口细节的能力，尤其是 total order 和 tags，其实可以反过来决定整个执行引擎的一致性设计。

## 局限性

这套设计前提很强：底层日志必须同时提供 global order、多 tag selective read、共享元数据和 conditional append。如果只有普通 partition 与 offset，Impeller 的核心技巧就用不上，系统又会退回 Kafka 式协调。

另外，评估范围比机制本身更窄。论文只用了 NEXMark，并且为了简化分析，为每个 query 单独分配一个 shared log 实例；它也明确承认更深入的数据倾斜处理和多查询干扰不在本文范围内。对 stateful operator 来说，系统仍然离不开 change log 和外部 checkpoint store，所以它减少的是 checkpoint 压力，而不是把恢复机制完全拿掉。最后，收益最明显的是 stateful workload；最简单的无状态场景里，Impeller 更多是和现有系统接近持平，而不是全面拉开差距。

## 相关工作

- _Wang et al. (SIGMOD '21)_ - Kafka Streams 同样依赖 logging 加 checkpoint 来实现 exactly-once，但它需要 coordinator 驱动的多流事务协议，而 Impeller 试图把这部分协调压缩进日志本身。
- _Carbone et al. (VLDB '17)_ - Apache Flink 的状态管理把 checkpoint-centric 的 exactly-once 路线做成了主流实现，Impeller 针对的正是这一路线在正常执行路径上的延迟代价。
- _Akidau et al. (VLDB '13)_ - MillWheel 通过物化 record ID 做去重；Impeller 则把已提交进度编码成日志位置和 change-log 范围。
- _Jia and Witchel (SOSP '21)_ - Boki 提供了带 tag 的 shared-log 底座，而 Impeller 补上的则是面向流处理的 progress protocol 与恢复逻辑。

## 我的笔记

<!-- 留空；由人工补充 -->
