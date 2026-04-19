---
title: "Multiplexing Dynamic Deep Learning Workloads with SLO-awareness in GPU Clusters"
oneline: "Mudi把推理延迟写成随GPU配额变化的分段线性曲线，再按训练模型结构预测干扰，在动态GPU集群里把训练塞进推理空隙而尽量不破坏SLO。"
authors:
  - "Wenyan Chen"
  - "Chengzhi Lu"
  - "Huanle Xu"
  - "Kejiang Ye"
  - "Chengzhong Xu"
affiliations:
  - "University of Macau"
  - "Shenzhen Institute of Advanced Technology, CAS"
  - "Univ. of CAS"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696074"
tags:
  - gpu
  - ml-systems
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mudi 试图把同一批 GPU 同时服务给在线推理和离线训练，但不靠拍脑袋做混部，而是先把每个 inference service 的延迟刻画成随 GPU 配额和 batch size 变化的分段线性函数，再从训练模型的网络结构预测它会把这条曲线推歪多少。基于这层显式建模，系统把集群级放置和设备级调参串成一个控制闭环。论文在 12 张 A100 的真实集群和 1000-GPU 模拟器上报告，Mudi 能把 GPU 利用率提高 42%，训练效率最高提升 2.27x，同时把推理 SLO 违约率压到明显低于已有方案的水平。

## 问题背景

这篇论文针对的是混合型 DL 集群里一个长期存在的结构性浪费。在线推理因为要守住几十到几百毫秒的 SLO，经常被整卡保留；训练任务虽然吞吐导向、理论上更能吃满 GPU，但实际也常常因为资源碎片、过度申请和排队策略而跑不满。作者给出的 Alibaba trace 很直观：推理服务平均资源利用率只有 37%，平均 SM 利用率甚至低于 37%；训练任务这边，大约 30% 的 GPU device duration 利用率低于 10%，队列等待还能拖到 1000 分钟以上。

从资源角度看，把任务塞到同一块 GPU 上当然有吸引力，但真正难的是干扰。论文先做了一个很重要的经验判断：推理和推理互相混部时，干扰很重。GPT2 与 ResNet50 和其他推理服务共置时，端到端干扰平均能到 3.19x 和 2.40x，因为 tokenization、preprocessing、PCIe 传输和推理内核都会互相争抢。反过来，推理和训练混部的平均干扰只有 1.67x 与 1.21x，说明「推理 + 训练」比「推理 + 推理」更值得做，但前提是系统能提前看见这些干扰并及时修正配置。

已有工作大多只解决一半问题。集群调度器会做 task co-location，设备内控制器会再调 batch、SM 配额或 kernel 发射顺序，可这两层其实强耦合。GPU% 和 batching 一改，推理延迟曲线会变，训练拿到的剩余 GPU 也会变；如果分开优化，结果很容易是集群层选错 colocate，或设备层被迫用激进配置去补救。再加上 inference QPS 波动很快、训练作业又经常是没见过的新模型，靠静态 profile 根本不够。

## 核心洞察

Mudi 最重要的洞察是，真正该建模的不是一个笼统的 interference score，而是 inference latency 随 GPU 配额变化的形状。对固定 batching size 来说，这条曲线通常是分段线性的：在 cutoff 点之前，GPU 配额稍一减少，延迟就明显上升；超过 cutoff 之后，再加资源收益就很小。更关键的是，训练任务共置以后，这种形状并不会消失，只是两段斜率和 cutoff 会发生可预测的偏移。

这件事一旦成立，集群优化和设备优化就被一条公共语言连接起来了。系统先根据训练模型的 layer 结构去预测斜率与 cutoff，再据此判断新任务放到哪块 GPU 最不伤害现有推理服务。落到具体设备之后，它再在小得多的搜索空间里找最合适的 batch size 和最小可行 GPU% 来守住 SLO。论文想证明的，其实不是某个 scheduler heuristic 更聪明，而是显式延迟模型比黑盒经验规则更适合这个场景。

## 设计

Mudi 的第一层是 Offline Profiler。它对每个 inference service 在 batching size 为 16 到 512、GPU% 为 10% 到 90% 的条件下做 profiling，并让它分别与代表性的训练任务共置，记录 P99 latency。之后系统用两段式 piecewise-linear function 去拟合这些点，得到两段斜率和一个 cutoff。作者没有追求复杂模型，反而强调低样本拟合：只用 6 个采样点时，分段线性拟合就已经优于 polynomial 和 MLP，因为它既省 profile 成本，又足够表达控制需要的信息。

第二层是 Interference Modeler。它把训练模型的结构展开成特征向量，例如 convolution、linear、embedding、encoder、decoder、batch norm、pooling 等层的数量，再用轻量模型分别预测两段斜率和 cutoff 参数。这样做的价值在于，系统不需要先在真实集群里把某个新训练任务跑过一遍，只要拿到它的网络结构，就能推断这类模型大概率会把共置推理服务的延迟曲线扭成什么样。

第三层是在线控制。Online Multiplexer 收到新训练任务后，先提取网络结构，再预测它和每个 inference service 共置时的延迟曲线。集群级 Device Selector 选的是平均斜率最小的设备，因为斜率小既意味着干扰低，也意味着 inference service 对 GPU 配额变化不那么敏感，能腾出更多资源给训练。到了设备内，Tuner 用 Gaussian Process + LCB 做 Bayesian optimization，在线找 inference 的最优 batching size；接着再求解满足 `W_i / b_i * P_i(b_i, Δ_i, Ψ_j) <= SLO_i` 的最小 GPU% 给推理，剩余资源交给训练。若必须修改 MPS 的 GPU 配额，Mudi 会先拉起 shadow inference instance，等新实例 ready 之后再切换，避免直接重启造成的空窗。最后，Memory Manager 基于 CUDA Unified Memory 把训练内存换出到 host，用来吸收 batch size 增大时的显存压力，避免把推理顶出 OOM。

## 实验评估

实验包含两套环境：一套是真实的 12-A100 集群，执行 300 个训练任务；另一套是扩展到 1000 GPU 的模拟器，执行 5000 个训练任务。推理工作负载覆盖 ResNet50、Inception、GPT2、BERT、RoBERTa、YOLOS；训练负载则包含 CNN、推荐模型、LSTM、GNN、BERT、YOLOv5 和 ResNet18。对比对象是 GSLICE、gpulets 与 MuxFlow，其中前两者被补上了训练侧调优逻辑，以减少比较偏差。

最核心的结果是，Mudi 不是单纯换来更高的资源利用率，而是在更高利用率下仍能守住推理。它把平均 SLO violation rate 压到真实集群的 0.5% 和模拟器的 1.2%。按模型细看，相对 baseline 的降幅最高可达 ResNet50 的 5.5x、Inception 的 2.2x、GPT2 的 4.2x、BERT 的 2.3x、RoBERTa 的 3.8x，以及 YOLOS 的 6x。训练侧也没被牺牲：CT 最多降低 2.27x，waiting time 最多降低 1.63x，makespan 最多降低 2.25x。

机制层面的数据也支撑这个结论。论文报告 Mudi 的平均 SM 利用率可达 60%，内存利用率达 35%，分别比 baseline 高 42% 和 19%。在满足 SLO 的前提下，各 inference service 的最大可支撑吞吐还能再提高 67%-103%。调参方面，GP-LCB 大多在 25 次迭代内收敛，集群级放置决策的额外开销在真实集群中低于 18 ms。不过，大规模证据仍有保留：1000-GPU 的结果来自基于 profile 拟合出的 simulator，而不是长时间 live deployment，所以可扩展性趋势可信，但不算完全封口。

## 创新性与影响

Mudi 的创新不在某个单点算法，而在它把 cluster-wide placement、device-level batching 和 GPU partition tuning 全都绑到同一个延迟模型上。像 GSLICE、gpulet 这类工作更偏设备内控制；MuxFlow 虽然已经开始做集群级 GPU sharing，但 Mudi 往前多走了一步，把 inference SLO 建模、未知训练任务预测和在线调参揉成同一套闭环。它解决的不是单机上如何挤出更多吞吐，而是混合 DL 集群里如何让高优先级推理和低优先级训练真正共享同一池 GPU。

这会对两类系统有价值。一类是企业内部混合训练/推理平台，它们最关心的是推理别出事、训练尽量捡漏；另一类是后续 GPU cluster scheduler 研究，特别是那些需要同时处理在线业务和离线作业的工作。论文顺手给出的另一个结论也很有启发：从资源争用结构看，很多时候 inference 和 training 混部反而比 inference 之间互相混部更合理，因为 CPU 侧与 PCIe 侧的冲突明显更轻。

## 局限性

这套方法的适用边界其实很清楚。Mudi 面向的是有严格 latency SLO 的在线推理，再加上能容忍延迟的训练任务；如果任务本身已经把显存占满，或者像长上下文 LLM serving 那样带着巨大的 KV cache，论文明确承认自己处理不了。它依赖的 architecture-feature predictor 也有前提，即网络结构能被少数常见 layer 计数描述；如果工作负载主要由少见 operator 组成，预测质量可能会掉。

实验方面，真实部署只有 12 张 A100，大规模结论更多依赖模拟。与此同时，一些 baseline 本来并不是为 inference-training 混部设计的，因此虽然作者已经做了公平化改造，但对比仍然不可能完全无争议。工程落地也有成本：MPS 的 GPU% 修改需要替换进程，memory swapping 会拉长训练时间，而论文最后也承认，最稳妥的配置仍然是每张卡放一个 inference 加一个 training；继续往上叠训练任务，收益会开始递减。

## 相关工作

- _Dhakal et al. (SoCC '20)_ - GSLICE 关注的是 inference 服务之间的动态 GPU partition，而 Mudi 进一步把 cluster-level 放置和训练混部一起纳入控制。
- _Choi et al. (ATC '22)_ - gpulet 为多 GPU 服务器上的异构推理模型提供细粒度时空共享，但没有解决动态训练任务进入集群后的联合 co-location 优化。
- _Xiao et al. (OSDI '20)_ - AntMan 通过优先级和 kernel 级控制来调度 GPU 集群中的 DL 作业，而 Mudi 把问题收束到 inference SLO 约束下的空间共享与训练填缝。
- _Zhao et al. (arXiv '23)_ - MuxFlow 同样研究大规模 DL 集群中的 GPU sharing，但 Mudi 用显式 latency curve 和基于网络结构的预测去应对未知训练任务与 SLO 敏感的推理服务。

## 我的笔记

<!-- 留空；由人工补充 -->
