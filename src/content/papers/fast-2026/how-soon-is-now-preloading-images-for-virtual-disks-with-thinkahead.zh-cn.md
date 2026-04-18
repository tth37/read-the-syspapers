---
title: "How Soon is Now? Preloading Images for Virtual Disks with ThinkAhead"
oneline: "ThinkAhead 从同一镜像的历史启动轨迹和实时带宽中学习预取顺序，在 EBS 中显著减少虚拟盘 lazy loading 造成的慢 I/O。"
authors:
  - "Xinqi Chen"
  - "Yu Zhang"
  - "Erci Xu"
  - "Changhong Wang"
  - "Jifei Yi"
  - "Qiuping Wang"
  - "Shizhuo Sun"
  - "Zhongyu Wang"
  - "Haonan Wu"
  - "Junping Wu"
  - "Hailin Peng"
  - "Rong Liu"
  - "Yinhu Wang"
  - "Jiaji Zhu"
  - "Jiesheng Wu"
  - "Guangtao Xue"
  - "Patrick P. C. Lee"
affiliations:
  - "Shanghai Jiao Tong University, China"
  - "Alibaba Group, China"
  - "Shanghai Key Laboratory of Trusted Data Circulation, Governance and Web3, China"
  - "The Chinese University of Hong Kong, China"
conference: fast-2026
category: cloud-and-distributed-storage
code_url: "https://github.com/Master-Chen-Xin-Qi/FAST26_AE"
tags:
  - storage
  - virtualization
  - caching
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ThinkAhead 会在 guest 真正访问之前预先拉取虚拟盘快照块。它从生产环境中的历史启动轨迹里学习每个镜像的访问模式，再结合当前带宽把块按访问密度和时间重排；如果历史不足，则退回到基于元数据相似性的 zero-shot 预测。在 Alibaba EBS 中，它把命中率相对 lazy loading 最高提升 `7.27x`，并把 P99 等待延迟最高降低 `98.7%`。

## 问题背景

云上的 EBS 会把 VM 镜像存放在远端对象存储里，再在需要时把它们物化成块设备卷。完全预加载太慢：论文给出的例子是，一个 `40 GiB` 镜像在 `20 MB/s` 带宽下大约需要 `34 分钟` 才能下载完，因此生产系统通常采用 lazy loading，让 VM 先启动起来，再按需拉取尚未落地的块。问题是，第一次命中未加载块时仍要等待 OSS 拉取，于是原本被“隐藏”的冷启动成本被转移成启动阶段一串长尾 I/O stall。

Alibaba 的生产数据说明这不是边缘问题。在一年的慢 I/O 归因里，lazy loading 占 EBS 软件栈全部慢 I/O 的 `39.35%`，其 P99 延迟最高达到 `7 s`。VD 创建后的前六分钟是最危险的阶段，因为超过 `95%` 的慢 I/O 都发生在这一窗口里。现有缓解方案与这个场景并不匹配。跨区域缓存和点对点分发会被镜像热度、集群落点和时间波动破坏效果；而 FlacIO 这类新镜像抽象需要修改 I/O 路径和镜像格式，不适合直接塞进一个大规模商用 EBS。

## 核心洞察

论文最核心的判断是：启动阶段的访问模式足够稳定，确实可以预取到“对的块”，但前提是不是机械地回放一条历史轨迹，而是同时考虑块的价值和时效性。同一镜像创建出的不同 VD 在启动时有很强的相似性，而最初几分钟真正会被访问到的 LBA 只占整盘很小一部分。只要能把少量高价值块尽早拉到本地，绝大多数 lazy-loading stall 就能被消掉。

更关键的是，“精确访问顺序”并不是最好的目标。在带宽受限时，那些访问更早且被反复访问的块，应该优先于“只是第一次出现得很早”的块。ThinkAhead 因此把预取建模成一个同时考虑访问次数、平均访问时间、最早访问时间和当前带宽的优化问题，而不是单纯做 trace replay。

## 设计

ThinkAhead 有三个部分。第一部分是数据预处理，它只保留每次 VD 创建前六分钟的轨迹，并清洗这些 per-VD trace。对每个镜像，系统先看“访问过多少个唯一块”的分布，截掉上下各 `2.5%` 的异常值，再围绕局部峰值把轨迹分成若干类别；在每个类别内部，再用 Pearson correlation 去聚类，从而得到一个能容忍重排和丢失请求的 centroid trace，作为该类启动模式的代表。

第二部分是 score-based block selection，它把 centroid 转成真正的预取顺序。每个块都有一个分数，分数由归一化访问次数、平均访问时间和最早访问时间共同决定。由于 `5 MB/s` 和 `80 MB/s` 下最优顺序显然不同，论文用 genetic algorithm 按带宽分桶离线训练这些权重。运行时，ThinkAhead 根据当前带宽选桶，生成预取序列；如果新到达的请求看起来更像另一组 centroid，它还能在线切换。控制面最终把块放入三层优先队列：已经 miss 的块优先，其次是预测即将访问的块，最后才是剩余块。

第三部分是 zero-shot prediction，用来处理几乎没有历史轨迹的镜像。ThinkAhead 按层级选择“借用”的轨迹：先找同一 image family，再找同一 user，最后再按 ISO 版本、性能级别等元数据去找最接近的样本；如果样本还是不够，就逐步放松筛选条件。这个设计明显是在精度和可部署性之间折中：训练要在离线跑数小时，但在线推理只需毫秒级，而且训练出来的参数可以跨集群复用。

## 实验评估

实验覆盖面足以支撑论文的中心论点。高保真模拟器回放了大约 `160,000` 个 VD、约 `2,500` 个镜像的轨迹，并按照 `80/20` 划分训练和测试，同时覆盖 public image 和 user-defined image，带宽范围从几 MB/s 到 `80 MB/s`。相对 lazy loading，ThinkAhead 在 public image 上把命中率最高提升 `7.27x`，在 user-defined image 上最高提升 `2.64x`。在低带宽场景里，它把 P99 等待延迟最高降低 `79.8%`；在 zero-shot 场景下，P99 等待延迟最高降低 `98.7%`，同时与带有明显 oracle 色彩的 History-based 基线相比只差不到 `1%`。

论文也没有只和 lazy loading 这种弱基线比较，而是加入了 Leap、DADI+、若干 count/time 启发式，以及一个直接回放测试轨迹精确顺序的 History-based 策略。ThinkAhead 通常优于这些启发式方法，因为它会按带宽自适应，而不是死守顺序。更有意思的是，它在命中率和中位延迟上甚至能超过 History-based，因为单纯回放顺序会忽略访问密度，在带宽紧张时反而把队列排坏。在线下生产集群的端到端实验里，ThinkAhead 将 Snapshot Worker 等待延迟在 P50、P99 和最大值上分别改善 `3.20x`、`1.35x` 和 `1.26x`，把冷启动延迟降低 `1.46x`，并把慢 I/O 数量减少 `5.35x`。

## 创新性与影响

相对于 _Li et al. (USENIX ATC '20)_，ThinkAhead 不是简单把 block trace 重放到镜像服务里，而是在生产级 EBS 场景里补上了 trace cleaning、带宽自适应打分和 sparse-history 镜像的 zero-shot 路径。相对于 _Liu et al. (FAST '25)_，它不要求改镜像抽象和 I/O 路径；对于一个已经在线运行的商用块存储系统来说，这本身就是很重要的系统贡献。相对于 _Cao et al. (USENIX ATC '24)_，它的新意也不在于提供一个通用 prefetch hook，而在于围绕 VD 启动行为定制出一套可学习的预取策略。

这篇工作的影响更偏工程实践。只要云存储团队已经在采集 VD 启动轨迹，就可以在不引入 GPU 或专用硬件的前提下尝试部署它。论文同时贡献了一份少见的生产规模数据分析，说明 lazy loading 在 EBS 里到底为什么会失效。因此它更像是“强测量研究支撑下的新机制”，而不是一个抽象理论模型。

## 局限性

最明显的限制是它仍然依赖历史。论文在 zero-shot 镜像上已经显著优于其他基线，但整套方法仍然假设 image family、user 和元数据足够预测未来启动行为。如果镜像被大幅改造，或者工作负载的访问模式根本不像 OS boot，ThinkAhead 的准确率就会下降，并逐渐退化回接近 lazy loading 的行为。

第二个限制是运行范围。训练是最贵的部分，离线一次要两个多小时，而论文没有完整说明镜像演化后需要多频繁地重训。生产实验的覆盖面也明显比 trace-driven simulation 更窄：它证明了端到端收益，但没有深入分析多租户同时拉取镜像时的干扰、公平性，或者带宽分桶在突发拥塞下选错的影响。最后，由于论文默认“预取到的块最终都会被使用”，它优化的是命中率而不是带宽浪费；这个假设对镜像启动合理，但不一定能直接推广到一般预取问题。

## 相关工作

- _Li et al. (USENIX ATC '20)_ — DADI 会根据历史轨迹预加载 overlay-based block image，而 ThinkAhead 面向生产 EBS 中的远端 snapshot 加载，并显式处理带宽变化和历史稀疏问题。
- _Liu et al. (FAST '25)_ — FlacIO 通过新的 runtime image abstraction 重做了容器镜像服务；ThinkAhead 则保留标准 VD 镜像，只优化块到达本地的顺序。
- _Cao et al. (USENIX ATC '24)_ — FetchBPF 提供可定制的内核预取机制；ThinkAhead 贡献的是面向 EBS 镜像启动的学习式策略和 trace-processing 流水线。
- _Chang et al. (USENIX ATC '25)_ — Poby 依赖 SmartNIC 来加速容器镜像分发，而 ThinkAhead 在块级别处理 VM 和 system-disk 镜像，不要求特殊网络硬件。

## 我的笔记

<!-- 留空；由人工补充 -->
