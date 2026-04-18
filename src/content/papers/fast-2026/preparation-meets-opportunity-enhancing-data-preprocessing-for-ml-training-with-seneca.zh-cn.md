---
title: "Preparation Meets Opportunity: Enhancing Data Preprocessing for ML Training With Seneca"
oneline: "Seneca 先用 DSI 性能模型把缓存切分给 encoded、decoded 和 augmented 数据，再在随机采样时优先命中缓存，让并发训练任务彼此受益。"
authors:
  - "Omkar Desai"
  - "Ziyang Jiao"
  - "Shuyi Pei"
  - "Janki Bhimani"
  - "Bryan S. Kim"
affiliations:
  - "Syracuse University"
  - "Huaibei Normal University"
  - "Samsung Semiconductor"
  - "Florida International University"
conference: fast-2026
category: ai-era-storage
code_url: "https://github.com/swiftomkar/seneca-fast26-pytorch"
tags:
  - ml-systems
  - caching
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Seneca 把 ML 输入预处理看成“缓存分配 + 采样策略”的联合优化问题，而不只是单纯的 I/O 加速。它的 Model-Driven Partitioning (MDP) 决定 encoded、decoded 和 augmented 三种数据形式各占多少缓存，Opportunistic Data Sampling (ODS) 则在不破坏 epoch 语义的前提下把随机 minibatch 重写为更偏向缓存命中的版本。对并发训练任务，Seneca 相比 PyTorch 将 makespan 降低 `45.23%`，并把 DSI 吞吐提升到比次优 dataloader 高 `3.45×`。

## 问题背景

论文关注的是多媒体模型与推荐模型训练中的 data storage and ingestion (DSI) pipeline。GPU 真正开始训练之前，CPU 必须先把样本从远端存储取回、解码、做变换与增强、再整理成 batch。作者认为，这一段已经成为越来越严重的瓶颈，因为 GPU 的吞吐增长速度快于 CPU 端预处理能力。以 SwinT 为例，他们测得预处理吞吐与训练吞吐之间的差距，从 RTX 5000 服务器上的 `4.63×` 扩大到 A100 服务器上的 `7.66×`，说明越新的加速器越容易把 DSI 的短板暴露出来。

既有缓存方案之所以不够，论文指出了两个原因。第一，数据在流水线里有三种关键形态：encoded 数据体积小、但解码开销高；decoded 数据省掉了解码、但体积膨胀；augmented 数据最接近训练可用状态、却最不适合跨 epoch 复用。最优选择会随缓存容量与硬件条件变化。比如在 `450 GB` 缓存下，缓存预处理后的数据能让预处理时间平均下降 `69.91%`，而抓取时间只增加 `34.85%`；但在 `250 GB` 缓存下，同样做法只带来 `11.36%` 的预处理收益，却让抓取时间平均上升 `87.2%`。第二，并发任务即便共享同一数据集，也不会天然互相受益，因为随机采样并不关心缓存里已有些什么。OpenImages 上四个 PyTorch 任务要做 `7.16` 百万次预处理来消费 `1.7` 百万个样本，而单纯加共享缓存后，总吞吐也只提升 `11.81%`。

## 核心洞察

这篇论文最核心的判断是：预处理瓶颈必须同时在两个层次上优化。第一层是用性能模型决定缓存应该在三种数据形式之间如何切分；第二层是把“严格遵守既定伪随机顺序”放宽为“在一个 epoch 内每个样本仍然只消费一次、整体顺序仍看起来随机”。这样做之所以成立，是因为缓存哪种形式真正有价值，取决于瓶颈究竟落在存储、CPU 解码、CPU 增强、网络、PCIe 还是 GPU ingestion；而共享缓存能否转化为收益，则取决于采样器能不能利用其他任务已经制造出的命中。如果系统能把这两个问题显式建模并协同决策，那么并发训练就不再是重复劳动，而会变成相互预热。

## 设计

MDP 把一次样本访问分成四种互斥情况：请求的数据已经以 augmented 形式在缓存里、已经以 decoded 形式在缓存里、已经以 encoded 形式在缓存里，或者只能从存储取回。对每一种情况，Seneca 都把 DSI 吞吐建模成相关服务带宽与硬件处理速率中的最小值，其中包括远端 cache 或 storage 带宽、CPU 的 decode 或 augmentation 吞吐、GPU ingestion 速率，以及网络与 PCIe 传输开销；分布式训练中的梯度通信开销也被纳入模型。然后，系统依据缓存划分 `xE`、`xD`、`xA` 和数据膨胀系数 `M`，计算三种缓存层里分别能放多少样本，并把四种访问情况按比例合成为整体 DSI 吞吐预测。作者用 `1%` 粒度的 brute-force 搜索所有切分组合，并指出这个过程通常不到 `1` 秒，而且往往每个数据集只需做一次。

ODS 负责把“共享缓存”真正转化成运行时收益。对每个训练任务，它维护一个 seen bit vector，记录当前 epoch 中哪些样本已经被消费过；对每个数据集，它维护每个样本的状态和引用计数，表示该样本目前处于 augmented、decoded、encoded 还是 storage。一个 batch 请求到来时，ODS 先找出 miss，再用请求任务尚未见过的缓存命中样本去替换这些 miss，然后增加对应样本的引用计数并返回修改后的 batch。当某个缓存样本的引用计数达到阈值时，后台线程会将其驱逐，并从存储中随机补入新样本。若把阈值设置为并发任务数，就能保证 augmented 数据不会跨 epoch 复用，同时每个任务在单个 epoch 内仍然只会看到每个样本一次。

实现层面并不花哨，但很实用。Seneca 在 PyTorch `v1.12.0` 上大约修改了 `4200` 行代码，并使用 Redis 作为缓存后端；作者强调它更像一个 drop-in dataloader replacement，而不是另起一套训练框架。

## 实验评估

论文先验证了 MDP 模型本身，平台包括单机和双机的 in-house 服务器、AWS `p3.8xlarge`，以及 Azure `NC96ads_v4`。在 `24` 组 modeled-versus-measured 组合里，Pearson 相关系数都不低于 `0.90`，这很关键，因为后续所有缓存切分决策都依赖这个模型。完整评估则覆盖了 `3.4` 百万到 `633.4` 百万参数的七个模型、`142 GB` 到 `1.4 TB` 的三个数据集，以及五种硬件配置。

最有说服力的端到端结果，是它在不改变准确率趋势的前提下缩短训练时间。在 Azure 上训练 ImageNet-1K `250` 个 epoch 时，Seneca 与 PyTorch、DALI 保持相同的收敛趋势，最终准确率误差不超过 `2.83%`，但训练时间相对 PyTorch 分别减少 `48.51%`（ResNet-18）、`38.09%`（ResNet-50）、`49.16%`（VGG-19）和 `47.83%`（DenseNet-169）。在 AWS 上用调度器模拟 `12` 个作业到达、且最多两个并发作业的场景时，Seneca 将总 makespan 降到 PyTorch 的 `45.23%`，原因是它把预处理与抓取工作共享掉了，而不是让每个任务各做一遍。

并发与扩展性结果也支持论文的中心论点。两台 Azure 节点下，Seneca 达到单节点 `1.89×` 的吞吐扩展，同时仍比 MINIO 快 `42.39%`。在单台 Azure 服务器上把并发任务数提升到四个时，Seneca 相比 Quiver 快 `1.81×`。表 8 解释了原因：Seneca 能把 GPU 利用率推到 `98%`，而 PyTorch、DALI、MINIO 和 Quiver 仍受 I/O 与 CPU 预处理限制。ODS 对缓存命中率也有实质帮助，只缓存 ImageNet-1K 的 `20%` 时命中率就达到 `54%`，缓存 `40%` 时达到 `66%`。因此 Seneca 的优势并不局限于某一个狭窄场景，而是横跨小数据集与大数据集、单机与分布式、冷缓存与热缓存。

## 创新性与影响

相对于 _Graur et al. (ATC '24)_ 和 _Graur et al. (ATC '22)_，Seneca 的重点不在于把变换放到哪里执行，或把预处理包装成服务，而在于把缓存明确建模成一个“三种数据形式之间的资源分配问题”，再把这个决策与采样器联动。相对于 _Khan et al. (FAST '23)_ 和 _Kumar and Sivathanu (FAST '20)_，Seneca 是面向“共享同一数据集的并发任务”设计的：它保留了 Quiver 那种“用缓存命中替换 miss 可以提升命中率”的直觉，但通过 epoch 语义避免了 oversampling；它也绕开了 SHADE 那种依赖 job-specific importance 的设定。对研究 dataloader、远端缓存和多租户训练基础设施的人来说，这篇论文提供的是一种新机制，也是一种更清晰的 framing：预处理瓶颈不能只靠加缓存解决，而要被建模、分配并调度。

## 局限性

Seneca 的收益依赖一些合理但并非总能满足的前提。MDP 需要事先 profile CPU 吞吐、cache 带宽、storage 带宽以及样本膨胀比例等系统参数；论文没有展示当这些值在长时间运行过程中漂移，或者多个数据集竞争同一缓存时，所选切分是否仍然稳健。ODS 则最适合多个任务共享同一数据集、且预处理流水线相近的情况。若工作负载高度异构，或者某个训练任务本来就几乎没有预处理开销，那么 substitution 的机会会明显减少。

实验覆盖面也比论文宣称的适用范围更窄。端到端结果主要集中在图像模型上，尽管作者声称方法也适用于音频、推荐和其他预处理开销高的任务。缓存后端使用 Redis，因此论文没有进一步讨论更慢、或者更易受故障影响的缓存服务会不会改变结论。最后，论文证明了 ODS 不会明显伤害训练精度，但没有给出更深入的理论说明，来论证这种“放宽后的伪随机顺序”在什么条件下与原始采样分布等价。

## 相关工作

- _Graur et al. (ATC '24)_ — Pecan 优化的是 transformation ordering 与 placement；Seneca 则显式地在 encoded、decoded 和 augmented 三种形式之间切分缓存，并修改采样来利用这种切分。
- _Lee et al. (ATC '21)_ — Revamper 复用的是 partially augmented samples，而 Seneca 同时管理三层缓存，并用按 epoch 的引用阈值避免 augmented 数据跨 epoch 复用。
- _Khan et al. (FAST '23)_ — SHADE 通过 importance sampling 提升 cacheability，但 Seneca 面向的是共享缓存下的并发训练，而不是单个任务的重要性排序。
- _Kumar and Sivathanu (FAST '20)_ — Quiver 同样会用缓存命中替换 miss，但 Seneca 把 substitution 与模型驱动的缓存切分绑定起来，并避免了 Quiver 的 `10×` oversampling 开销。

## 我的笔记

<!-- 留空；由人工补充 -->
