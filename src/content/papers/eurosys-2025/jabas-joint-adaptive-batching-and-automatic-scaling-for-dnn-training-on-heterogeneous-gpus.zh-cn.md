---
title: "JABAS: Joint Adaptive Batching and Automatic Scaling for DNN Training on Heterogeneous GPUs"
oneline: "JABAS不让快GPU私自放大local batch，而是让它们跑更多等批大小的虚拟worker，再把迭代级batch调整和按epoch扩缩容绑成一个闭环。"
authors:
  - "Gyeongchan Yun"
  - "Junesoo Kang"
  - "Hyunjoon Jeong"
  - "Sanghyeon Eom"
  - "Minsung Jang"
  - "Young-ri Choi"
affiliations:
  - "UNIST"
  - "Samsung SDS"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696078"
code_url: "https://github.com/unist-ssl/JABAS"
tags:
  - ml-systems
  - gpu
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

JABAS抓住了异构GPU上自适应batching最容易被忽略的失效点：如果为了追上快卡，直接给不同GPU不同的local batch size，就会破坏mini-batch i.i.d.假设，最后把收敛语义弄坏。它提出IIDP，让更强的GPU通过更多virtual stream workers和gradient accumulation去承担更多工作，但每个worker的local batch size保持一致；随后再把迭代级batch调整和按epoch的GPU扩缩容接到同一套配置求解器上。论文在三套异构集群、七个模型上报告，相比已有自适应训练方法，训练时间平均缩短33.3%，训练成本平均降低54.2%，同时没有精度损失。

## 问题背景

自适应batching本来是为了解决一个老问题：global batch size变大可以减少同步开销，但太早把batch开大又会伤害泛化，所以系统通常希望训练前期小batch起步，后期再逐渐放大。论文指出，只改batch而不改资源仍然不够。训练早期往往是通信瓶颈，卡加多了反而不划算；训练后期global batch size上去以后，资源不跟着扩容，又会把吞吐白白丢掉。作者用GNMT举例很说明问题：前两个epoch里，4张GPU比16张GPU快10.13%；但到了后段，16张GPU又比4张快51%，总训练时间缩短70%，只是成本也变成2.34倍。也就是说，batch size和资源规模必须一起调。

异构GPU把这个问题再往前推了一层。生产集群本来就常年混着多代GPU，最直觉的做法是让快卡吃更大的local batch size、慢卡吃更小的，再按权重聚合梯度。但论文认为这一步正好踩中收敛雷区：不同local batch size会改变各worker看到的gradient noise分布，等于把i.i.d.前提打破。作者的实验也确实看到，WDP或WDP+SimiGrad会让训练质量最多下降7.5%，有些模型甚至直接发散。真正困难的地方因此不是单纯提高硬件利用率，而是在异构环境里既吃满快卡，又不偷偷改写优化语义。

## 核心洞察

JABAS最关键的判断是，异构性应该通过改变每张GPU承载多少个等批大小worker来吸收，而不是通过改变worker自己的local batch size来吸收。只要每个worker处理的样本数仍然相同，那么全局梯度聚合的语义就和普通Data Parallelism一致；快GPU只是通过多跑几个worker，或者多做几步gradient accumulation，来贡献更多有效吞吐。

这个不变量一旦立住，batch调整和资源扩缩容就能合并成同一个配置问题。给定目标global batch size和一个候选GPU分配，系统只要搜索一个公共local batch size，再给每类GPU挑出合适的VSW数量和GA步数，就能找出最高吞吐配置。论文真正想传达的不是某个scheduler heuristic，而是一种建模方式：先保住收敛语义，再把硬件利用率优化建立在这个前提上。

## 设计

JABAS的底座是IIDP。它在每张GPU上开一个多线程进程，用CUDA streams同时运行多个virtual stream workers。每张卡有一个main VSW和若干普通VSW：普通VSW负责算本地梯度，main VSW先把同卡梯度做local aggregation，再参与跨GPU的All-reduce，最后只由main VSW执行一次optimizer并把新权重单向拷贝给同卡其他VSW。这样做的目的是避免每个worker都各自维护一份完整优化器开销。论文还实现了两种one-way weight synchronization方式：SWS按顺序做更新和拷贝；OWS把shard级的weight update和copy与后续All-reduce重叠起来，除非gradient buffer太大、重叠反而会互相干扰。

第二个核心部件是配置求解器。JABAS先为每个模型和GPU类型profile最大local batch size、最大VSW数量，以及计算、通信、optimizer的时间模型，然后用dynamic programming在给定global batch size下搜索最优配置。求解结果包含一个公共local batch size，以及每张GPU对应的`(n_vsw, n_GA)`组合。因为JABAS沿用了SimiGrad的gradient similarity逻辑，它还要求分到作业上的GPU能拆成两个对称组，让两组decoupled workers的聚合梯度可以互相比对。

控制面分成两个时间尺度。第一层是细粒度adaptive batching：每`p=100`次迭代，系统计算两组worker的gradient similarity，在上下界内按`alpha=0.1`增减global batch size，同时更新learning rate，并让IIDP在线重配VSW线程和GA步数，不必重启GPU进程。第二层是粗粒度auto-scaling：到epoch末尾，系统用Gaussian Process Regression和exponential smoothing的ensemble去预测下一个epoch的global batch size轨迹，再枚举候选GPU allocation，反复调用配置求解器估算每种分配的epoch时间，只有确定值得换资源时才checkpoint并重启作业。

## 实验评估

实验覆盖三套异构集群和七个模型。Cluster A混合了V100、P100、TITAN RTX和RTX 3090；cluster B混合了RTX 2060、Quadro P4000、TITAN V和TITAN RTX；cluster C则用RTX A6000配合不同power cap来模拟异构算力，并跑BERT-large、GPT3-XL、LLaMA2-7B这类大模型。主要对比对象是SimiGrad、Pollux和Pollux-AS。至于WDP类方案，论文先证明它在异构GPU上会把收敛搞坏，因此没有把它们放进主结果表里做正面对比。

主结论很直接：JABAS同时赢了时间和成本，而且没有拿精度做交换。按论文汇总，和当时最强自适应训练基线相比，训练时间平均缩短33.3%，训练成本平均降低54.2%。若单看SimiGrad，JABAS在cluster A、B、C上分别再把平均训练时间压低24.7%、31.3%、43.8%。如果和每个工作负载里第二便宜的方法相比，成本又分别少31.4%、90%和41.1%。对通信占主导的GNMT尤其明显：在cluster B上，JABAS经常主动绕开最弱的GPU，最终把成本优势拉到最高5.1x。

机制层面的证据也基本撑住了论文的中心论点。动态VSW重配置加上其他控制逻辑，对所有模型带来的总开销都低于10%；IIDP迭代时间预测的平均误差是5.9%；global batch size轨迹预测的平均误差是15.8%。这些数据说明JABAS不只是一个离线理想化策略，而是能在线跑起来的控制闭环。当然，外推边界也要看清楚：cluster C的异构性来自power cap，不是真实混插不同GPU；成本则是按AWS p3.8xlarge价格模型折算，不是直接的生产账单。

## 创新性与影响

和最接近的工作相比，JABAS的新意在于把几个原本割裂的问题压成同一个系统闭环。SimiGrad能做细粒度batch调整，但没有异构GPU扩缩容；Pollux会同时改batch和资源规模，但它默认worker是同质的，而且goodput目标会高估吞吐收益、低估统计效率塌陷带来的代价；VirtualFlow和EasyScale虽然也在做worker与GPU解耦，却没有把这种runtime机制和保收敛的adaptive batching、按epoch扩缩容真正接起来。

所以这篇论文既有runtime层面的贡献，也有控制策略层面的贡献。IIDP本身就是一个明确的新机制：相同local batch size的worker、同卡局部聚合、单向权重同步，让异构GPU更像一个负载平衡得多的DP系统。而在这之上，共享一套配置求解器去同时服务batch调整和resource scaling，是这篇论文最容易被后续工作继承的部分。以后做异构ML训练集群、又不想把训练质量和资源效率拆开看的系统，大概率都会引用这套问题拆法。

## 局限性

JABAS依赖一个比较规整的部署前提。论文默认每个节点内部是同构GPU、每节点GPU数量是偶数，而且资源分配要能拆成成对的相同GPU，这样adaptive batching阶段才能把worker分成两个对称组比较gradient similarity。系统也需要针对具体模型和GPU类型做profiling，拿到最大local batch size、最大VSW数以及时间模型参数，所以迁移到新硬件或新算子组合不是零成本。

它的扩缩容机制也刻意做得偏粗。GPU reallocation只在epoch边界发生，因为一旦换资源，作业就要checkpoint并在新分配上重启。这对长训练任务是合理的，但对epoch内部的突发干扰、租户争用或快速资源抖动没有覆盖。作者还承认，配置求解器的复杂度会随着每组decoupled workers数量增长而上升，在更大规模上可能还要引入额外优化。

最后，实验外延没有标题看起来那么宽。论文的确覆盖了CV、翻译和LLM，但LLM结果依赖power-limited A6000来模拟异构环境，没有展示真实混合GPU集群；它也没有讨论多租户背景流量、故障恢复或混合厂商加速器。核心思想仍然成立，只是离生产落地还差几类干扰因素没有补上。

## 相关工作

- _Qiao et al. (OSDI '21)_ - Pollux通过goodput联合调整batch size和集群资源，而JABAS面向异构GPU，并强调先守住i.i.d. mini-batch语义，再谈吞吐优化。
- _Qin et al. (NeurIPS '21)_ - SimiGrad用gradient similarity做细粒度global batch调整，JABAS则把这套信号接进了支持异构GPU和自动扩缩容的运行时。
- _Or et al. (MLSys '22)_ - VirtualFlow用virtual nodes把worker和硬件解耦，而JABAS坚持相同local batch size，并把重点放在异构条件下的收敛保持。
- _Li et al. (SC '23)_ - EasyScale研究GPU上的弹性训练，但JABAS进一步加入adaptive batching、按epoch的GPU重分配，以及面向吞吐优化的配置求解器。

## 我的笔记

<!-- 留空；由人工补充 -->
