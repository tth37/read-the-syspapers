---
title: "ByteCheckpoint: A Unified Checkpointing System for Large Foundation Model Development"
oneline: "ByteCheckpoint 把张量元数据与字节数据分离，在加载时自动重分片检查点，跨框架和存储后端把 LFM 训练的 checkpoint stall 压到亚秒级。"
authors:
  - "Borui Wan"
  - "Mingji Han"
  - "Yiyao Sheng"
  - "Yanghua Peng"
  - "Haibin Lin"
  - "Mofan Zhang"
  - "Zhichao Lai"
  - "Menghan Yu"
  - "Junda Zhang"
  - "Zuquan Song"
  - "Xin Liu"
  - "Chuan Wu"
affiliations:
  - "The University of Hong Kong"
  - "ByteDance"
conference: nsdi-2025
tags:
  - llm-training
  - fault-tolerance
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ByteCheckpoint 把分布式检查点看成“由元数据索引的一组字节区间”，而不是绑定在某个 TP/DP/PP 并行配置上的文件集合。这样同一份检查点就能在预训练、后训练和评测阶段，被自动加载到新的并行布局里，同时统一的 planner、execution engine 和 storage I/O 层屏蔽不同训练框架与存储后端的差异。在作者的生产工作负载上，它把运行时 checkpoint stall 降低了 12.13x-161.50x，并在超大规模训练中把 stall 控制在 1 秒以内。

## 问题背景

这篇论文强调，LFM 开发里的 checkpointing 远不只是“宕机后恢复训练”这么简单。检查点还要在预训练和后训练之间流转，要被自动评测任务周期性拉取，也要在坏机下线、GPU 配额变化、上下文长度调整等情况下支持训练恢复。只要新任务使用的并行配置和旧任务不同，这个过程就需要 checkpoint resharding。作者统计其平台过去六个月的数据，发现训练恢复需要 resharding 1,870 次，跨阶段迁移需要 13,080 次，评测任务需要 19,844 次。

工业界常见做法是维护一堆离线 resharding 脚本，但这条路既慢又脆弱。脚本往往和具体训练框架、模型组件、优化器布局以及 TP/DP/PP 组合深度耦合。附录里提到，他们最大的脚本已经有 3,193 行 Python。即使脚本写出来了，执行成本仍然很高：论文给出的平均离线重分片完成时间分别是 1,870.38 秒、650.34 秒和 593.21 秒。更糟的是，这类脚本生成的新检查点依然绑定于某个目标并行配置，不能自由复用，反而进一步增加存储开销。

即便不考虑重分片，LFM 规模下的 checkpoint I/O 本身就已经很贵。作者给出的例子是，一个在 4,096 GPUs 上训练的 GPT 175B 模型，把检查点保存到 HDFS 的端到端时间可达 200 秒。异步 checkpointing 只能把一部分代价移出训练关键路径，无法消除保存、加载和评测准备阶段的真实耗时。现有系统要么默认并行配置不变，要么只支持很窄的框架和后端组合，要么在生产级规模下无法维持稳定性能。

## 核心洞察

论文的核心洞察是：只要把“检查点的存储表示”与“生成它时的运行时并行布局”彻底解耦，重分片问题就会从“写无数转换脚本”变成“做一次元数据匹配”。也就是说，保存时不要只留下按 rank 命名的文件，而要显式记录每个 tensor shard 属于哪个全局张量、它在原始张量中的位置，以及它的字节到底落在哪个文件、哪个偏移区间。这样，新的训练任务只需要根据自己的并行配置查询这些元数据，就能在加载阶段自动拿到需要的内容。

这个想法若只覆盖模型权重还不够，因为真实训练恢复还依赖 dataloader state。ByteCheckpoint 因此把 dataloader state 进一步拆成 replicated state 和 sharded state：前者只需保存一份，后者单独存放，后续可以根据并行度变化执行 copy、split 或 merge。这样一来，无论是切换 TP/PP，还是调整 DP 大小，都能在不重训、不漏数、不重复训练样本的前提下恢复数据读取进度。框架相关的复杂性被收敛到 planner 中，而统一的工作流和 I/O engine 负责执行。

## 设计

ByteCheckpoint 的结构分成四层：对用户暴露的 API、针对不同训练框架的 planner、执行 save/load 的 execution engine，以及屏蔽不同存储后端细节的 storage I/O layer。用户侧接口非常小，只需要把 model、optimizer、dataloader 和 extra state 组织成字典，再调用 `bytecheckpoint.save()` 或 `bytecheckpoint.load()`。Megatron-LM、FSDP、DDP 和 veScale 分别有自己的 planner，把框架原生的 sharding 语义转换成 ByteCheckpoint 的统一元数据格式。

检查点格式以“一个全局元数据文件 + 多个按 rank 存储的数据文件”为中心。对于张量，系统为每个 shard 记录三类信息。`BasicMeta` 保存 stride、device 等运行时恢复所需属性；`ShardMeta` 记录 fully qualified name，以及该 shard 在原始全局张量中的 n 维 offset 与 length；`ByteMeta` 则给出这个 shard 对应字节所在的文件和偏移。加载时，只要查询这三类元数据的映射关系，就能知道应该去哪些文件读哪些字节。对于 dataloader，replicated 部分只保存一次，而 token buffer、读取偏移等 sharded 部分则拆分独立保存，以便后续精确地 copy、split 或 merge。

论文对一个很关键的难点处理得比较扎实：ZeRO 风格优化器状态形成的 irregular tensor shard。经过 flatten 和 concatenate 之后，有些 shard 已经无法直接表示成原始张量上的规则 n 维切片。在论文描述的 DCP/FSDP 路径里，这类 shard 通常通过同步 all-gather 优化器分片、并与 D2H copy 交错执行的方式来规避；ByteCheckpoint 则采用 decomposition 策略，把一个 irregular shard 拆成多个 regular sub-shard，并为每个 sub-shard 建立单独的元数据条目。这样做会多出一些元数据，但省掉了保存路径上的同步通信。

加载时的自动重分片遵循一个统一流程。所有 rank 先读取全局元数据文件，然后根据目标模型和优化器的 shard 需求在元数据中做匹配，生成本地 load plan。协调者收集所有本地 plan 后，再做冗余消除与负载均衡，并把最终 plan 分发回各个 rank。随后 execution engine 用异步 pipeline 执行实际 I/O。对于 dataloader，如果只改了 TP 或 PP，token buffer 会被复制到新 worker；如果 DP 大小变了，token buffer 则要执行 split 或 merge，以保证恢复后的采样轨迹与原训练过程严格对齐。

ByteCheckpoint 的很多收益来自工程优化而不仅是数据格式本身。保存阶段，它用 worst-fit 负载均衡避免某个 DP group 成为检查点拖尾。加载阶段，它在 DP replica 之间消除重复读取，让一个 worker 读完后通过 all-to-all 分发给其他需要该 shard 的 worker。planner 和全局元数据还会被缓存，避免大模型每次 checkpoint 都重新做高开销 planning；论文提到，405B 模型在 8,960 GPUs 上若不缓存，仅 planning 就要 62 秒。I/O engine 方面，加载路径把 read、deserialize、H2D 和跨 GPU 传输流水化；保存路径把 D2H、serialize、dump 和 upload 流水化。针对 HDFS，系统还专门做了单文件多线程读取、子文件并行写入后再做 metadata-level concat，以及 dataloader state 预取来消除阻塞。

## 实验评估

评估使用了两个生产风格工作负载：一个在 A100 集群上通过 FSDP 微调的 4B 视频生成 transformer，以及一个在 H800 集群上通过 Megatron-LM 训练的 70B 文本 transformer，持久化后端统一为 HDFS。对比基线方面，FSDP 场景使用 PyTorch DCP，Megatron-LM 场景使用 MCP。以 128-GPU FSDP 为例，ByteCheckpoint 把 checkpoint stall 从 61.37 秒降到 0.38 秒，保存时间从 236.34 秒降到 23.74 秒，加载时间从 105.74 秒降到 12.01 秒，resharding 时间从 91.01 秒降到 13.64 秒。对 4,800-GPU Megatron 场景，它把 stall 从 4.70 秒降到 0.36 秒，保存从 76.21 秒降到 8.59 秒，同时也改善了加载与重分片时间。

总体来看，论文报告的收益是 checkpoint stall 降低 12.13x-161.50x，平均保存速度提升 6.05x，平均加载与重分片速度提升 3.88x，ETTR 提升 1.16x-1.29x。微基准也支撑作者的机制解释：异步保存、负载均衡和 plan cache 叠加后，可把较小 tGPT 模型的平均保存时间从 48.3 秒降到 19.27 秒；irregular tensor 的 decomposition 路径只带来约 0.20 秒阻塞，而 all-gather + D2H 的传统路径要 4-6 秒。

正确性验证也比较关键。论文展示了 PP、TP、DP 和 hybrid resharding 之后训练 loss 曲线的平滑衔接，还在真实的 175B 生产训练中证明：如果并行配置不变，恢复前后的 loss 可以做到 bit-wise 对齐。生产部署结果同样有分量。作者报告 ByteCheckpoint 已经支撑 405B Megatron-LM 在 8,960 GPUs 上训练，平均 checkpoint stall 只有 0.59 秒，端到端保存时间 51.06 秒，加载时间 129.49 秒。这说明它不是只在小规模实验里有效。

## 创新性与影响

与最接近的已有方案相比，ByteCheckpoint 的区别很明确。PyTorch DCP 提供了 FSDP 场景下的在线 resharding 元数据，但不覆盖 TP/PP 这类并行布局，而且在 irregular optimizer shard 上代价较高。Megatron MCP 则更多是 Megatron 生态内部的 checkpointing 扩展，没有真正解决跨框架统一工作流的问题。ByteCheckpoint 的创新点在于把三件通常分开的事情合到一起：并行无关的 checkpoint representation、跨训练框架与存储后端的统一 save/load workflow，以及足以支撑生产部署的全栈 I/O 优化与监控体系。

这篇论文最可能被大规模模型平台团队引用。它把 checkpointing 从“框架内部的一个工具函数”提升成“贯穿 LFM 开发生命周期的平台基础设施”，也说明未来的弹性训练系统如果想真正摆脱定制脚本，首先需要这种与运行时布局解耦的训练状态表示。

## 局限性

论文里最强的基线对比其实只覆盖 GPU states，因为 DCP 和 MCP 都不支持 dataloader state 的重分片。一旦把完整训练状态纳入，ByteCheckpoint 自己的重分片时间也会明显上升：例如在 2,400-GPU Megatron 场景里，full states 的 load-time resharding 达到 401.21 秒，主要瓶颈是 dataloader 中 token buffer 这类 unique state 的处理成本，以及这些状态只集中在少数 worker 上造成的 straggler。

此外，这套系统的很多收益都依赖作者所在环境里的深度工程定制，例如面向 HDFS 的优化、自研 C++ 实现和 NNProxy、基于 gRPC 的树形 collective、以及冷热分层存储策略。论文没有展示在更通用的云存储或控制力更弱的后端上，这些收益还能保留多少。最后，正确性证据主要是 loss continuity 和 exact resume，而不是覆盖多框架、多故障模式的大规模 fault injection study。

## 相关工作

- _Eisenman et al. (NSDI '22)_ - `Check-N-Run` 通过差分保存和量化降低推荐模型 checkpoint 成本，而 `ByteCheckpoint` 面向的是需要持久化、可重分片、可跨阶段流转的 foundation model 检查点。
- _Mohan et al. (FAST '21)_ - `CheckFreq` 重点是把 snapshot/save 与训练流水化并调 checkpoint 频率，`ByteCheckpoint` 则更关注与并行布局解耦的表示方式，以及 save/load/reshard 的生产级性能。
- _Wang et al. (SOSP '23)_ - `Gemini` 主要依赖内存内 checkpoint 加速故障恢复，而 `ByteCheckpoint` 假设检查点必须进入持久化存储，因为它们还要服务评测、调试和跨阶段迁移。
- _Thorpe et al. (NSDI '23)_ - `Bamboo` 提升了抢占式实例上的弹性训练能力；`ByteCheckpoint` 与其正交，提供了一种能减少定制重分片逻辑依赖的训练状态格式。

## 我的笔记

<!-- 留空；由人工补充 -->
