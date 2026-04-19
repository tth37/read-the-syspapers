---
title: "A House United Within Itself: SLO-Awareness for On-Premises Containerized ML Inference Clusters via Faro"
oneline: "Faro把每个模型的延迟SLO蒸馏成可优化的效用函数，再配合概率负载预测与快速多租户扩缩容，在固定规模的Ray/Kubernetes推理集群里显著减少违约。"
authors:
  - "Beomyeol Jeon"
  - "Chen Wang"
  - "Diana Arroyo"
  - "Alaa Youssef"
  - "Indranil Gupta"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "IBM Research"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696071"
code_url: "https://dprg.cs.uiuc.edu/traces/go.php?id=40"
tags:
  - ml-systems
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Faro 针对的是多数 ML autoscaler 没真正解决的场景：多个 inference job 共用一个固定规模的 on-prem 集群，而且每个 job 都有延迟 SLO，负载还会突发波动。它先把每个 SLO 变成平滑的 utility，再用概率分布而不是单点值去预测未来负载，最后在几分钟级别内求解一次集群级资源重分配。论文在 Ray Serve over Kubernetes 上报告，在 right-sized 集群里 Faro 可把 SLO violation 降低 2.3x-12.3x，即便在 heavily oversubscribed 的情况下也还能降低 1.1x-1.5x。

## 问题背景

论文抓住的是企业内部很常见、但论文系统里经常被弱化的部署形态：模型推理不是直接跑在公有云弹性资源池里，而是跑在容器化的 on-prem 集群上。这样做有可移植性、隔离性和内部治理上的好处，但代价是资源预算往往是固定的。一旦多个团队、多个模型被并到同一套集群里，问题就从「单个服务要不要扩容」变成「有限 CPU 和内存应该优先给谁」。

现有方案在这里各有短板。Ray Serve 和 Kubernetes HPA 更擅长看 CPU utilization、queue length 这类底层信号，而不是直接面向开发者声明的 latency SLO。Barista、MArk、Cocktail、INFaaS 主要围绕单个 job 或云上成本优化展开，默认资源不足时还可以继续买。Swayam 支持 ML SLO，但不是为固定共享集群设计的。Cilantro 虽然也是 utility-based 的多租户系统，可作者给出的对比很刺眼：在 32-replica、720 ms SLO 的配置下，Cilantro 平均 SLO violation rate 为 83.4%，而 Faro 只有 6.9%。

更根本的矛盾在时序上。推理服务的 SLO 是亚秒级，但新 replica 的冷启动却是几十秒到几分钟；如果控制器花太久才算出一个「很准确」的分配方案，等它执行时流量高峰可能已经过去，或者违约已经发生。因此，这篇论文把问题重新定义成：如何在不牺牲太多解质量的前提下，把集群级资源决策做得足够快。

## 核心洞察

Faro 的核心判断是，面向 SLO 的多租户 autoscaling 不该执着于求解「精确目标」，而应该主动优化一个经过放松的代理目标。论文里反复强调的 `sloppification` 不是修辞，而是设计原则。精确的 step utility、高保真的排队模型、以及单点式 workload prediction，都会把优化问题弄成大片 plateau 或者对短时波动过于迟钝，结果是求解器算得慢，还容易给出在运行时机上已经失效的答案。

所以 Faro 的策略是，把真正重要的排序关系保留下来，把数值上难解的尖角磨平。它用平滑 utility 近似 SLO 满足情况，用概率负载窗口代替一个均值预测，再把不稳定队列从「直接记作无穷大延迟」改成可微分的惩罚。这样得到的控制器在数值意义上没有那么「精确」，但在系统意义上反而更正确，因为它能在还有时间补救之前把资源挪动起来。

## 设计

Faro 的第一步，是把每个 job 的开发者接口压缩成一个 latency SLO，也就是目标延迟 `s_i` 与相应 percentile。系统先构造原始的 step utility，再把它放松成 `U(l_i, s_i) = min((s_i / l_i)^alpha, 1)`。当系统需要丢请求来防止更大的违约或 OOM 时，Faro 还会把 utility 乘上一个借鉴 AWS SLA 的 availability penalty，形成 effective utility。到了集群级，管理员可以在总 utility、公平性，或两者混合的目标之间做选择，例如 Faro-FairSum 与 Faro-PenaltyFairSum。

第二步是容量估计。Faro 一方面保留了悲观的 upper-bound estimator，另一方面利用 `M/D/c` queueing 去更贴近推理请求的到达和服务特征。论文举了一个很说明问题的例子：若单请求处理时间 `p = 150 ms`、到达率 `lambda = 40 req/s`、SLO `s = 600 ms`，悲观上界会要求 10 个 replica，而 `M/D/c` 在 99.99th percentile 下只需要 8 个。为了避免队列进入不稳定区后又形成新的 plateau，Faro 进一步引入 `rho_max = 0.95`，把不稳定队列转写成带惩罚的稳定队列估计。

第三步是 workload prediction。Faro 的基线预测器是 N-HiTS，但作者认为常规的 RMSE 或 MAE 训练只会给出一个偏平滑的未来均值，对尖峰极不敏感。于是系统在 N-HiTS 上叠加 Gaussian 输出模型，生成 100 条预测样本，再对整个预测窗口做决策。论文报告 Faro 的 predictor RMSE 为 116.24，优于其实现的 LSTM 与 DeepAR 的 123.95 和 122.38，同时推理延迟也低 2x-3x。

最后才是 autoscaler 本体。Stage 1 用预测得到的 7 分钟负载窗口，加上冷启动开销，建立单个 job 的扩缩容目标；作者实测冷启动最高达到 70 秒。Stage 2 用 COBYLA 在总 vCPU 与内存约束下求解多租户优化问题，并通过 `G = 10` 的 hierarchical grouping 让求解在 job 数增大时仍能扩展。Stage 3 再对已经达到预测 utility=1 的 job 做 shrinking，直到继续缩减会改变 cluster utility 为止，把多余副本回收出来。控制频率上，Faro 把 5 分钟一次的长期预测式控制，与 10 秒一次、只做 additive scale-up 的短期 reactive 控制拼在一起。实现上，它作为独立的 Kubernetes pod 运行在 Ray Serve v2.0.0 之上，每个 job 独占一个 Ray subcluster，Router 负责上报指标并在队列长度达到 50 时执行 tail drop。

## 实验评估

部署实验跑在 IBM Cloud VPC 上，底层是两台 `cx2-32x64` VM；推理任务使用 PyTorch 上的 ResNet34，每个 worker pod 对应一个 Ray Serve replica。工作负载来自 9 条 Azure Functions trace 加 1 条 Twitter trace，统一缩放到 1-1600 requests/min，并用前 10 天训练 predictor、在第 11 天评估。对比基线是 FairShare、Oneshot、AIAD，以及合并实现的 MArk/Cocktail/Barista。

最关键的结果是，Faro 不只是某个特定负载点上偶尔赢，而是在资源充足与资源不足两种区间都更稳。在 36-replica 的 right-sized 集群里，它把 cluster SLO violation rate 降低 2.3x-12.3x，把 lost cluster utility 降低 1.7x-9x。集群缩到 32 replicas、进入 slightly oversubscribed 状态后，Faro 仍能把 SLO violation 降低 2.8x-8.4x，把 lost utility 降低 2.5x-6.1x。哪怕只剩 16 replicas、进入 heavily oversubscribed 区间，它也还能分别取得 1.1x-1.5x 与 1.2x-1.5x 的优势。

更重要的是，这些结果和机制本身是对得上的。时间线实验显示，在负载波动和短时 spike 下，Faro 能更久地维持最大 cluster utility，并在 spike 后更快恢复，这对应的正是 hybrid autoscaler 的设计。50% ResNet18 加 50% ResNet34 的 mixed workload 下，Faro 仍可把 SLO violation rate 降低 4x-23x，把 lost cluster utility 降低 2.3x-13.1x。ablation 也很说明问题：单是 relaxation 就能把 lost cluster utility 降低 2.1x-3.7x，hybrid autoscaler 最多再贡献 1.42x，probabilistic prediction 最多贡献 1.36x。也就是说，论文真正有效的不是某一个局部技巧，而是整个放松后的控制闭环。

## 创新性与影响

Faro 的新意不在于又造了一个 serving engine，也不只是换了个 autoscaling 指标。它真正完成的是一个固定规模、多租户 inference 集群的统一控制表述：把面向人的 SLO 转成 utility，把这些 utility 放松成求解器能快速处理的形式，再把 workload prediction、queueing estimation 和集群级优化捏成一个集中式控制器。相比把每个 job 各自扩缩容、最后靠运气共享资源的做法，这篇论文给出了更完整也更工程化的答案。

它的影响面会落在两边。对系统研究者来说，论文很明确地说明了，SLO-aware inference control 不能只看单个 job，而应被建模为集群级的 utility optimization。对内部 ML 平台工程师来说，Faro 的好处是它能包裹在现有 Ray Serve 和 Kubernetes stack 外面工作，而不是要求团队把 serving 基座全部重写。后续做多租户 model serving、预算受限推理平台，或 SLO 驱动资源控制的论文，很可能都会把它当作一个早期而完整的系统参照。

## 局限性

论文也清楚写出了 Faro 的边界。它只负责 replica count 的 autoscaling，不处理 placement、底层 scheduling 或 admission control；真正的 pod 放置仍然交给 Kubernetes，严重过载时则通过 Router 侧的 drop 来保底。如果问题的核心在于 CPU/GPU 混部、异构实例选择，Faro 现在并没有答案。

实验范围同样比论文的总体愿景更窄。真实部署主要是 homogeneous CPU 上的 ResNet inference，最大的 100-job 结果来自 matched simulator，而不是 live deployment。作者明确把 heterogeneity 视为后续工作。除此之外，Faro 依赖的排队模型与 utility 形式也明显偏向 inference workload，本质假设包括近似 Poisson 到达、低方差服务时间，以及以 latency SLO 为中心的目标函数。论文认为这些思想也许能扩展到 microservices 或 batch jobs，但文中并没有给出直接证据。

还有一个需要运营者自己承担的取舍：在 heavily oversubscribed 集群中，偏 fairness 的变体会输给 Faro-Sum 与 Faro-PenaltySum，因为在资源本来就不够时，均匀分配往往会牺牲总 utility。这不是论文的漏洞，而是目标函数真的会改变结果，因此集群管理员必须先想清楚自己究竟追求总效益还是跨 job 的公平性。

## 相关工作

- _Gujarati et al. (Middleware '17)_ - Swayam 面向单个 ML inference job 做主动扩缩容，而 Faro 要解决的是多个 job 在固定集群预算下的联合分配。
- _Gunasekaran et al. (NSDI '22)_ - Cocktail 针对单个 model serving 任务做主动优化，而且只 scale up；Faro 则补上了多租户场景里的 downscale 与跨 job 资源回收。
- _Zhang et al. (USENIX ATC '19)_ - MArk 的核心是给单个 inference service 选择更划算的云资源，而 Faro 处理的是 on-prem、总资源固定时不同 job 之间怎么重新分配副本。
- _Bhardwaj et al. (OSDI '23)_ - Cilantro 也用 utility 描述集群目标，但 Faro 认为它在 sub-second ML inference SLO 下收敛太慢，因此必须换成更激进的 relaxed objective 与更快的 prediction loop。

## 我的笔记

<!-- 留空；由人工补充 -->
