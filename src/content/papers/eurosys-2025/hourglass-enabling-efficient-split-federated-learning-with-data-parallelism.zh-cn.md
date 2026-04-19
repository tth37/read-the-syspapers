---
title: "Hourglass: Enabling Efficient Split Federated Learning with Data Parallelism"
oneline: "Hourglass 不再为每个客户端保留一份 server-side partition，而是按 GPU 数量共享模型，并把差异更大的中间特征送到同一 GPU 上训练。"
authors:
  - "Qiang He"
  - "Kaibin Wang"
  - "Zeqian Dong"
  - "Liang Yuan"
  - "Feifei Chen"
  - "Hai Jin"
  - "Yun Yang"
affiliations:
  - "Huazhong University of Science and Technology, Wuhan, China"
  - "Swinburne University of Technology, Melbourne, Australia"
  - "University of Adelaide, Adelaide, Australia"
  - "Deakin University, Melbourne, Australia"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717467"
tags:
  - ml-systems
  - gpu
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Hourglass 的出发点很直接：split FL 不该在 fed server 上为每个客户端各养一份 server-side model partition。它改成按 GPU 数量保留共享分区，再把差异更大的 intermediate features 放到同一条训练路径里。论文报告，相比 SplitFed，它最多能把收敛速度提升 35.2x，并把精度提高 9.28%。

## 问题背景

split federated learning 的原始动机，是把大模型训练里最重的那一段从边缘设备挪到服务器。客户端只训练前半段，把 intermediate features 传给 fed server，再由服务器训练后半段。问题在于，SplitFed 一类方案虽然替客户端减了负，却把复杂度完整转嫁给了服务器端。

作者把这个代价拆成两部分。第一是计算开销。如果客户端数量远大于 GPU 数量，服务器就得反复把不同客户端的 server-side partition 在 CPU 内存和 GPU 内存之间来回切换。论文在 300 个客户端上的测量显示，这件事会吃掉 13.1%-79.9% 的总训练时间，平均占比 43.15%。第二是存储开销。传统 split FL 需要为每个客户端保留一份 server-side partition，作者估算 DINOv2 在 10K 客户端时要占用 40 TB 以上存储。量化或压缩可以缩小模型，但会伤精度，也没有改掉每客户端一份模型这个根本结构。

## 核心洞察

Hourglass 的关键判断是：server-side state 的规模应该跟 GPU 数量绑定，而不是跟客户端数量绑定。服务器有 1 张 GPU，就保留 1 份共享的 server-side partition；有 `M` 张 GPU，就保留 `M` 份共享分区，并只在这 `M` 份之间做聚合。这样就把 split FL 的服务器成本从按客户端扩张，改成按加速器扩张。

它对异构性的利用也很反直觉。很多 FL 工作想先把相似客户端放到一起，Hourglass 的实验结果却说明，把相似 features 连续送进同一份共享分区，反而容易让更新长期朝同一方向偏移。把差异更大的 features 串在一起，能让共享分区吸收更广的变化，因此 DFF 比 FCFS 和 similarity-first 都更有效。

## 设计

整体流程仍然是 split FL 熟悉的五步：客户端先在 client-side partition 上做 forward，把 intermediate features 发到 fed server；服务器侧的 scheduler 为这些 features 选 GPU；trainer 在 server-side partition 上做 forward 和 backward；算出的 gradients 再回传给对应客户端；最后 aggregator 用 FedAvg 更新下一轮的 server-side partitions，而且这一步和客户端 backward 可以并行。

单 GPU 配置是论文的第一层核心。Hourglass 在 GPU 上只保留 1 份共享的 server-side partition，所有客户端的 features 都穿过这同一份模型。这样不仅消灭了 model switching，也改变了知识融合方式：传统 split FL 是先各自更新、最后聚合，Hourglass 则让所有客户端立刻更新同一份共享分区。论文测得，在达到相同精度时，这种单模型方案在 VGG-16 上只需要原来 4.31% 的训练时间，在 ResNet-50 上只需要 11.93%，同时把存储开销最多降 96.67%，把计算开销最多降 88.07%。

多 GPU 场景下，Hourglass 为每张 GPU 保留 1 份共享 partition。若等所有客户端 features 到齐后再跑 `k`-means，不但会被 straggler 拖住，还会引入 8.1%-24.1% 的聚类时间开销，所以论文改用 Euclidean-distance 的 locality-sensitive hashing。features 到达后立刻被映射到 bucket，再分给空闲 GPU；若 GPU 异构，则优先用更强的设备。论文还给出了强凸、一般凸和非凸目标下的收敛分析。

## 实验评估

实验覆盖五个模型和四个数据集：VGG-16、ResNet-50、ViT 跑 CIFAR-10 与 CINIC-10，CharCNN 和 LSTM 跑 AG News，VGG-16 还跑 Speech Commands。服务器端有 10 张 RTX 3080 和 5 张 RTX 2060，客户端则是 CPU 机器。

主结果先看收敛速度。在 10-GPU 配置下，Hourglass-DFF 相比 FL 有 8.9x-78.8x 的加速，相比 SplitFed 有 2.7x-35.2x 的加速。精度也会提升。单 GPU 时，VGG-16 在 CIFAR-10 上，Hourglass-DFF 能到 86.82%，而 SplitFed 只有 80.6%；多 GPU 时，作者报告的最大精度增益来自 ResNet-50/CINIC-10，相比 SplitFed 高 9.28%。

这些结果不是单纯多加几张卡就能得到的。DFF 在单 GPU 和多 GPU 里都稳定胜过 FCFS 与 SFF。GPU 数量也不是越多越好：对 300 个客户端，最佳点出现在 10 张 GPU；再继续增加 GPU，会让知识被摊薄，收敛反而变慢。对异构 GPU，LSH 加上优先强 GPU 的放置，相比随机分配还能再把训练时间减少 22.1%-56.8%。

## 创新性与影响

这篇论文真正新的地方，不是提出了新的 FL 优化器，而是把 split FL 重新表述成一个 GPU 共享与调度问题。相对 SplitFed，它把每客户端一份 server-side partition 改成每 GPU 一份共享分区；相对 IFCA、Auxo 这类 clustered FL，它把异构性处理从客户端分组，搬到了在线 intermediate-feature placement 上。DFF 和 LSH 组合起来，构成了论文最有价值的系统贡献。

## 局限性

Hourglass 仍然建立在相当强的同构假设上。所有客户端默认共享同一套模型结构和同一个切分位置，论文也明确把 model heterogeneity 留到未来工作里。它的收益区间也不是无限放大：GPU 太多或客户端继续增多时，额外并行性会被知识融合变弱抵消掉。

另外，理论和系统现实之间还有距离。文中的收敛证明依赖凸性相关假设，这对 CNN、ViT 只能算有限度的支撑；实验也主要聚焦计算侧，而不是真实广域网络部署。

## 相关工作

- _Thapa et al. (AAAI '22)_ - SplitFed 是 Hourglass 最直接的参照物：前者为每个客户端保留一份 server-side partition，再做跨客户端聚合；后者把状态压缩成每 GPU 一份共享分区，重点解决模型切换和资源复用。
- _Ghosh et al. (NeurIPS '20)_ - IFCA 在 federated learning 中按客户端做聚类，但它处理的是客户端或模型层面的分组，不是 split learning 里 intermediate features 到 GPU 的在线放置问题。
- _Liu et al. (SoCC '23)_ - Auxo 也利用客户端异构性来做更高效的 FL，不过它依赖客户端聚类；Hourglass 则把对象换成到达中的 features，并用 LSH 取代全局聚类等待。
- _Liao et al. (ICDE '24)_ - MergeSFL 从 feature merging 和 batch-size regulation 角度优化 split FL，而 Hourglass 的重点是 fed server 端的计算开销、存储开销和 GPU 调度。

## 我的笔记

<!-- 留空；由人工补充 -->
