---
title: "Heimdall: Optimizing Storage I/O Admission with Extensive Machine Learning Pipeline"
oneline: "Heimdall 不再逐个猜哪些 I/O 会慢，而是判断 SSD 是否进入忙碌区间，并把这个判断做成可落到内核与 Ceph 的 28 KB admission controller。"
authors:
  - "Daniar H. Kurniawan"
  - "Rani Ayu Putri"
  - "Peiran Qin"
  - "Kahfi S. Zulkifli"
  - "Ray A. O. Sinurat"
  - "Janki Bhimani"
  - "Sandeep Madireddy"
  - "Achmad Imam Kistijantoro"
  - "Haryadi S. Gunawi"
affiliations:
  - "University of Chicago"
  - "MangoBoost Inc."
  - "Bandung Institute of Technology"
  - "Florida International University"
  - "Argonne National Laboratory"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717496"
code_url: "https://github.com/ucare-uchicago/Heimdall"
tags:
  - storage
  - kernel
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Heimdall 是一个面向复制式 flash storage 的 ML I/O admission controller。它最关键的改变，是把预测目标从单个慢 I/O 改成 SSD 的忙碌区间，并把训练数据清洗、特征工程、模型压缩和部署优化一起做完。结果是：相对 LinnOS 目前 67% 的准确率，Heimdall 把 `ROC-AUC` 拉到 93%，在 500 组 trace-driven 实验里把平均时延再压低 15-35%，同时把运行时模型做到了 28 KB、0.05-0.08 µs 推理延迟。

## 问题背景

论文关注的是复制式 flash storage 里的读请求准入问题。前端把读请求发给某个后端 replica 之后，后端可以选择直接在本地 SSD 上执行，也可以拒绝这次请求，让前端把同一份数据改发到另一份副本。之所以值得这么做，是因为 SSD 内部的 GC、buffer flush、wear leveling 以及突发负载交织在一起时，会把少量请求拖进很长的尾时延区间。对这种场景来说，继续等当前设备，常常还不如尽早换到另一个 replica。

难点不在于有没有 reroute 这条路，而在于什么时候该走。像 C3、AMS、Heron 这样的启发式方法，本质上都靠规则来猜设备是否繁忙。LinnOS 往前走了一步，用轻量神经网络做预测，但它按固定 4 KB page 粒度决策，又用单个 I/O 的时延 cutoff 做标注。作者把它放回微软、阿里和腾讯的新 trace 以及更快的 SSD 上重测，平均准确率只剩 67%。这类系统里两种错判都贵：false admit 会把读请求送进正忙的设备，false reroute 则会把另一边 replica 白白压热。所以真正的问题是，怎样把预测做准，同时又把 CPU、内存和部署复杂度压到足以放进 kernel path 和 distributed storage path 的程度。

## 核心洞察

Heimdall 最值得记住的判断是：admission controller 应该学习设备在一段时间内的状态，而不是事后判断某一个 I/O 为何变慢。SSD 的内部争用往往表现为一段时间里延迟抬升、吞吐下滑，而这才是系统真正需要识别的对象。单个大 I/O 即使落在健康设备上，也可能因为体量大而显得很慢；如果仍按单请求 latency cutoff 来打标签，模型学到的就会是错的目标。把标签改成 busy period 之后，模型面对的才是正确问题：这个 replica 现在是否处在不适合继续接单的阶段。

这也解释了作者为什么把大量篇幅放在数据清洗上。既然要识别的是持续性的忙碌状态，那么慢区间里偶尔命中 cache 的幸运请求、快区间里偶发的 ECC 或 retry 异常、以及只持续 3 个 I/O 左右的短促慢峰，都更像噪声而不是有用信号。只要标签能稳定对应「设备正在经历一段不健康时期」，一个很小的模型就足以根据最近的 queue depth、latency、throughput 和 I/O size 判断下一次请求应不应该被本地接收。

## 设计

Heimdall 的核心不是单个 classifier，而是一条完整的 ML pipeline。它先做 period-based labeling：当 latency 高且 throughput 低时，把这些 I/O 视为 busy period 的候选点，阈值通过梯度下降搜索得到，用来在 sensitivity 和 accuracy 之间找平衡；随后再把标签扩展到整个 tail period。接着是三阶段 noise filtering：去掉慢区间里的快异常点、快区间里的慢异常点，以及长度不超过 3 个 I/O 的短慢突刺。基于更干净的数据，作者再做特征工程，最终保留五个主特征：queue length、historical queue length、historical latency、historical throughput 和 I/O size；历史深度取 3，归一化方法选 min-max。

模型本身反而刻意做得很收敛。作者比较过多种 learner，最后选 neural network，不是因为它最复杂，而是因为它在准确率和跨数据集稳定性之间最平衡。最终网络按 per-I/O 粒度推理，隐藏层是两层，大小分别为 128 和 16，激活函数用 ReLU，输出层则是单神经元 sigmoid。和 LinnOS 相比，这个设计的关键优势不只是层数和参数量变化，而是 Heimdall 不再把一个大 I/O 切成许多个 4 KB page 逐个推理。

更重要的是，作者把部署也纳入设计目标。推理路径从 Python 手工改写到 C++，再用 `-O3` 编译，并把权重量化到乘以 1,024 的整数尺度，最后把推理时延压到亚微秒量级，同时把模型状态压到 28 KB。论文还加入了 joint inference：一次推理最多可以替最多 `P` 个 I/O 做决定，但输入并不会机械地拼接 `P` 份完整历史，而是只保留最近少量 I/O 的关键信息。这样一来，系统管理员就能在不重做整体架构的前提下，用 `P` 来换取吞吐和准确率之间的平衡。

## 实验评估

论文的实验覆盖面相当扎实。作者使用微软、阿里和腾讯的 2 TB 原始 block trace，生成 11 TB 中间数据；主实验从中随机抽取 500 个 3 分钟窗口，这些窗口在读写比、请求大小、IOPS 和随机性上都做了分层采样。在 user-level setup 里，作者用两块 Samsung 970 PRO 组成一个 2-way replicated 环境，对比 baseline、random、C3、LinnOS 和 hedging。作者先证明在启发式方案里 C3 可以代表 AMS 和 Heron 的最好表现，然后给出主结果：Heimdall 在各个 latency percentile 和平均时延上都最好，摘要里的结论是相对当下最强方案平均时延再降 15-35%，对 baseline 最多能快 2 倍。

更有说服力的是它的拆解实验。以重测后的 LinnOS 为起点，`ROC-AUC` 只有 67%。把 digitization 换成 min-max scaling 后到 67.5%；改成 period-based labeling 后到 73%；再加入更完整的特征工程，升到 77%；最后三阶段 noise filtering 再把准确率推到 93%。运行时开销也很漂亮：相对 LinnOS，Heimdall 把模型内存从 68 KB 降到 28 KB，CPU overhead 降低 2.5 倍，推理时延落在 0.05-0.08 µs。joint inference 则提供了另一条扩展路径：当 joint size 为 9 时，在 2 µs 延迟目标下，可承受负载从 0.5 mIOPS 提到 4 mIOPS，但中位准确率会从 88% 掉到 81%，所以作者认为 joint size 取 3 更稳妥。

论文还验证了这套方法能否离开 user-level replay。Linux kernel prototype 运行在异构的 Intel DC-S3610 和 Samsung PM961 上，Heimdall 依旧拿到最低平均时延，比其余非 baseline 方法快 38-48%。Ceph 部分则在 10 台机器、20 个 OSD 上做 wide-scale 评估，跨不同 scaling factor 也都优于 baseline 和 random。不过这里用的是 FEMU 模拟 SSD，而不是整套真实物理盘，因此这部分实验更能说明策略和控制路径可以迁移到 distributed setting，而不是证明集群里的绝对 flash 行为已经被完全复现。

## 创新性与影响

这篇论文的新意，不在于提出了某种全新的学习器，而在于它把 storage admission control 的问题重新定义对了，再把数据、模型和部署三个层面一起打磨到可落地。与 LinnOS 相比，Heimdall 不再预测单个 page 是否变慢，而是预测 busy period；它把 variable-sized I/O 当成一等公民；它还把模型压小到足够自然地塞进 kernel 和 Ceph。与 LAKE 这类通过 GPU batching 让 kernel-space ML 更易部署的工作相比，Heimdall 走的是另一条路线：先把模型和输入设计简化到 CPU 也能轻松跑，再把 GPU 当成可选项，而不是前提条件。

因此它对两个方向都会有影响。对 storage researchers 来说，这篇论文最重要的启示是：admission control 的上限，往往不是被模型家族卡住，而是被 labeling、noise handling 和 feature design 卡住。对做 deployable ML systems 的人来说，它则给了一个很具体的案例，说明 quantization、语言级重写和输入粒度设计，可能比继续堆更重的模型更关键。所以我会把 Heimdall 看成是一篇「问题重述 + 工程化机制」都做得很完整的系统论文。

## 局限性

Heimdall 终究还是一个需要训练和维护的模型系统，这意味着它的效果高度依赖 workload 与 device 是否仍和训练期相近。论文的长时间实验已经显示，如果只训练一次，8 小时内准确率会在 63%-82% 之间波动。作者提出了一个很初步的 retraining policy，但它假设系统能持续拿到最近一分钟的逐请求日志，而论文自己也承认这类 logging 往往代价很高，现实里默认甚至是关闭的。因此，真正长期在线部署时如何观测 drift、何时触发 retraining、以及如何避免无效重训，论文都还没有给出成熟答案。

此外，这套设计明确偏向 replicated flash array 上的 read-latency control，并不是一般意义上的通用存储调度器。joint inference 的吞吐收益需要拿准确率来换。Ceph 结果依赖 FEMU 而非真实 SSD。所谓 black-box 也不是完全自动化，因为系统仍建立在 storage-specific feature engineering、阈值搜索和人工设计的过滤规则之上。换句话说，它已经证明这条路线有效，但还没有证明任何设备、任何 workload 都能零成本套用。

## 相关工作

- _Hao et al. (OSDI '20)_ - LinnOS 是最直接的前作：同样用轻量神经网络做 flash admission control，但它依赖 per-4 KB cutoff-based labeling，因此在 variable-sized I/O 场景下既不够自然，准确率也被 Heimdall 拉开。
- _Fingler et al. (ASPLOS '23)_ - LAKE 关注的是如何把 kernel-space ML 通过 GPU batching 跑起来；Heimdall 则把模型和输入做轻，再用 joint inference 扩展吞吐，让 CPU 路径本身也足够可用。
- _Suresh et al. (NSDI '15)_ - C3 用启发式 replica selection 降低 cloud data store 的 tail latency；Heimdall 面对的是相似的 admit-or-reroute 决策，但它学习的是 SSD 的 busy period，而不是持续调规则。
- _Wong et al. (FAST '24)_ - Baleen 也把 ML 用在 storage admission 上，不过目标是 flash cache 的 admission 与 prefetching；Heimdall 则专注在复制式 flash 设备之间的 block-level I/O admission。

## 我的笔记

<!-- 留空；由人工补充 -->
