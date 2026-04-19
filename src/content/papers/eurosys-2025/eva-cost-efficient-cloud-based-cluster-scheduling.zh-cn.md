---
title: "Eva: Cost-Efficient Cloud-Based Cluster Scheduling"
oneline: "Eva 用吞吐感知的 reservation price 判断哪些任务值得共置到同一实例上，再决定何时值得为更便宜的集群配置付出迁移代价。"
authors:
  - "Tzu-Tao Chang"
  - "Shivaram Venkataraman"
affiliations:
  - "University of Wisconsin-Madison"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3717483"
project_url: "https://pages.cs.wisc.edu/~tau_chang/eva"
tags:
  - scheduling
  - datacenter
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Eva 把云上 batch 调度拆成一个统一的成本问题来做：任务要不要共置、该租哪种实例、现在要不要大规模重配，都用同一套账来算。它先用 throughput-normalized reservation price 判断某个 packing 是否真的比单任务独占更便宜，再在 Full Reconfiguration 和 Partial Reconfiguration 之间权衡迁移开销与未来节省。论文在 AWS 实机和 Alibaba trace 仿真里都拿到了 15%-42% 的总成本下降，代价是 JCT 有一定上升。

## 问题背景

固定规模集群里的 scheduler，通常主要管两件事：谁先跑、任务放哪台机器上。云上的 batch cluster 不是这样。这里 scheduler 还决定集群里到底该存在哪些实例类型、总共该租多少台机器，所以优化目标也从单纯压低排队时间和 JCT，变成了在不明显伤害 throughput 的前提下，把总 provisioning cost 降下来。给每个任务单独开一台实例当然最稳，但肯定贵；把任务往一起塞虽然听上去节省，却不保证真能省钱。

论文认为旧方案主要卡在三处。第一，batch 作业在 GPU、CPU、RAM 上的需求差异很大，而且相关性很弱，因此确实存在不错的互补 packing；但前提是 scheduler 要同时选对实例类型。第二，就算 co-locate 的任务已经被分到不同 GPU 和 CPU 上，它们还是会争 LLC、disk I/O、network bandwidth 这些底层资源。作者测到，两两共置时 throughput 降幅可以从 0% 一路到 36%，这意味着资源看起来塞得更满，不代表总成本一定更低，因为 runtime 变长以后，实例在线时间也会变长。第三，最优集群形状会随着作业提交和完成不断变化，可重配本身并不便宜：AWS 上 instance acquisition 需要 6-83 秒，instance setup 需要 140-251 秒，checkpointing 需要 2-30 秒，task relaunch 需要 1-160 秒。完全不迁移会长期浪费钱，迁得太勤又会把钱烧在 idle time 上。

作者面向的场景也说得很明确：一个企业内部有多支 ML 团队，共享同一个云上 batch cluster，跑的多是长时间任务。于是 scheduler 真正要回答的问题不是资源利用率漂不漂亮，而是共享和迁移到底值不值得，最好还能接近 dedicated cluster 的 throughput。

## 核心洞察

Eva 的核心洞察，是先给 placement 和 provisioning 找到同一种可比较的价值尺度，而且这个尺度一开始就要把性能损失算进去。论文从经济学里借来 reservation price 这个概念：对一个任务来说，它的 reservation price 就是能单独承载它的最便宜 standalone instance 的小时价格。若一组任务的 reservation price 总和高于某个实例的小时价格，把它们放到这台实例上才算经济上说得通。进一步地，如果共置会让 throughput 下降，那 reservation price 也该按 throughput 打折。比如某任务因为 interference 只剩 80% throughput，那它的价值也只该按 standalone reservation price 的 80% 来算。

这样一来，packing 就不再只是看利用率，而是变成一个更硬的判定规则：贵实例优先考虑，但只有当一组任务的 throughput-normalized reservation price 真能覆盖实例成本时，Eva 才会接受这个 packing。第二个洞察发生在时间维度上。Full Reconfiguration 的配置即便更便宜，也只有在它能持续足够久、把迁移成本赚回来时才有意义。因此 Eva 不会盲目全量重排，而是同时算一个保守的 Partial Reconfiguration，再估计当前配置大概能活多久，然后比较两边谁更划算。

## 设计

Eva 的系统结构把控制面和执行面分开。用户提交的是容器化 job，并为每个 task 提供资源向量；如果没有 standalone throughput，Profiler 可以帮忙估计。系统按周期调度，论文讨论里默认是每 5 分钟一轮。每轮结束时，Scheduler 给出新的 cluster configuration，Provisioner 负责起停实例，Executor 负责启动和迁移任务，ThroughputMonitor 则持续记录 co-location 对进度造成的影响。

最基础的算法是 Full Reconfiguration。Eva 先按 hourly cost 从高到低遍历 instance type，再不断尝试打开当前类型的新实例。对每台候选实例，它都会贪心地加入那个能让任务集合 reservation price 最大化的未分配任务；如果放不下更多任务，或者再加一个任务反而会让 throughput-normalized value 下降，就停止。最后只有当这一组任务的总价值不低于实例真实小时价格时，这个实例才会被保留下来。论文用一个 200 个任务、21 种 instance type 的 micro-benchmark 说明，这个 heuristic 已经能做到 ILP 成本的 1.01x，运行时间只有 378 ms，而 ILP 在 30 分钟内都算不完。

interference awareness 直接嵌在这条路径里。Eva 不要求事先把所有 co-location 组合都 profile 完，而是维护一张 co-location throughput table。若某个任务集合以前出现过，就直接用实测 throughput；若没见过，就把每个任务的 throughput 估成若干 pairwise co-location throughput 的乘积，对从未见过的 pair 则先给一个偏保守的默认值 0.95。这个近似当然不完美，但胜在能在线运行，也足以把那些资源上装得下、性能上却不值钱的 packing 过滤掉。对 multi-task 的 data-parallel job，Eva 还多做了一层处理：一个 task 成了 straggler，整份 job 都会被拖慢，所以 ThroughputMonitor 会谨慎归因，不把 slowdown 一股脑记到所有共置组合头上。

migration awareness 是 Eva 的第二根支柱。Full Reconfiguration 不顾当前放置状态，可能引入大量 task migration；Partial Reconfiguration 只处理新到达的任务，以及那些已经不再 cost-efficient 的实例上的任务，其余部分尽量保持不动。Eva 每轮都会同时跑这两套算法。然后它分别计算两种候选配置的即时 provisioning savings 和 migration cost，再根据事件统计去估计新配置的寿命：job arrival 和 completion 被建模成 Poisson process，而某个事件会不会触发下一次 full reconfiguration 的概率，最终给出一个预计持续时间 `D_hat = -1 / (lambda ln(1-p))`。Eva 选择的是那个在这段预计时间里，更有机会把迁移成本赚回来的配置。换句话说，只有当全量重排的收益能活得比开销更久时，它才会真正动手。

## 实验评估

实现方面，Eva 和 simulator 一共大约 5,700 行 Python，跑在 AWS EC2 上，任务通过 Docker 执行，共享存储放在 S3 上，控制面通信用 gRPC。评测覆盖 21 种 AWS instance type，来自 P3、C7i、R7i 三个 family；工作负载则包括 ResNet18、ViT、GPT2、GraphSAGE、GCN、A3C、Diamond、OpenFOAM 等 10 个应用。这个 workload 组合很关键，因为论文要证明的正是多资源异构场景下的联合调度价值。

最有说服力的结果来自 Alibaba production trace，一共 6,274 个 job。若采用原始 Alibaba job duration，Eva 的总成本降到 No-Packing 的 60%，而 Stratus、Synergy、Owl 分别是 72%、77%、78%。与此同时，Eva 平均每台实例承载 2.05 个任务，normalized job throughput 维持在 0.91。代价也摆在那儿：Eva 的 JCT 是 10.55 小时，而 No-Packing 是 9.18 小时。换成更长的 Gavel-style duration model，趋势不变，Eva 进一步做到 No-Packing 成本的 58%。

实机 AWS 结果说明这个机制不只是 simulator 里好看。120-job 的 trace 上，Eva 把总成本从 $536.07 降到 $452.40，同时把平均 GPU/CPU/RAM allocation 从 67/77/28% 提升到 76/85/41%。32-job 的 trace 上，Eva 的总成本是 $123.03，而 Stratus、Synergy、Owl 分别是 $145.76、$145.80、$143.75。simulator 和真机也比较一致：对 Eva 来说，simulated cost 和实际 cost 的偏差只有 0.6%。

几组 ablation 也把论文的两条主张钉得很牢。若 Eva 完全忽略 interference、只用原始 reservation price，随着 co-location 变重，throughput 会明显掉下去，总成本反而上升，因为 job 会跑得更久。换成 throughput-normalized reservation price 之后，Eva 的 throughput 能接近 Owl，但仍保留 packing 带来的成本收益。再看迁移策略：若关掉 full-versus-partial 的 ensemble，永远做 Full Reconfiguration，migration delay 一大，总成本就会跟着上升；反过来，若只做 Partial Reconfiguration，在 multi-GPU job 比例高的时候，总成本最多会高出 8%。论文还报告，不考虑 multi-task-job interdependence 会把成本最多推高 13%，而 Full Reconfiguration 在 8,000 个任务时运行时间会上升到 22.06 秒。这些数字把设计收益和副作用都讲清楚了。

## 创新性与影响

Eva 的新意不在于它会 packing，也不在于它知道 interference 存在，这些点前人都碰过。真正新的是，它把 instance selection、task placement、interference 和 reconfiguration timing 放进同一个成本框架里。reservation price 让 Eva 能回答某个 packing 是否值得付费，而 Full Reconfiguration 和 Partial Reconfiguration 的组合同样把这套逻辑延伸到了时间维度。相较只看 utilization 或只想少迁移的方案，这篇论文对云上 batch scheduling 的表述更完整。

因此它的影响面也比较明确。对做 cloud batch scheduler 的研究者来说，Eva 给出了一条很像样的建模路径：共享集群要想真省钱，就得显式给 throughput 损失和 migration 开销定价。对企业内部 ML 平台的工程团队来说，这篇论文也提供了一个可操作的理由去做 shared cluster，而不是继续让每个任务独占实例。后续不管是做 spot-aware、multi-cloud，还是更重 accelerator 的调度系统，都很容易把 Eva 当作比较基线。

## 局限性

Eva 本质上还是 heuristic。论文里的 micro-benchmark 说明 Full Reconfiguration 很接近最优，但它的运行时间仍然大致随任务数二次增长，在 8,000 个任务时已经到 22.06 秒。与此同时，throughput table 对未知组合用 pairwise 乘积和默认值 0.95 来近似，这显然是工程上可接受的折中，不是严格的性能模型；如果 interference 结构更复杂，packing 判断就可能被带偏。

它的部署假设也比题目看上去更窄。评测只覆盖单个 AWS region、on-demand instance，以及长时间 batch job。spot market、跨云采购、以及更强的低时延约束，都被论文明确放在正交方向上。另外，系统默认企业内部共享不存在安全顾虑，因此更严格的 tenant isolation 并不在设计目标内。

最后，multi-task 扩展主要覆盖了一种依赖模式：data-parallel job 被单个 straggler 拖慢。对 ML training 这已经很重要，但它并不是任意 DAG job 或 pipeline-parallel training 的通用抽象。若集群里主流 workload 变成这些结构，Eva 目前的 throughput 归因和记账方式就不够用了。

## 相关工作

- _Chung et al. (SoCC '18)_ - Stratus 在 public-cloud container scheduling 里主要通过尽量少迁移来控成本，而 Eva 认为长时间 batch job 在收益能摊平开销时，应该更积极地做重配。
- _Mohan et al. (OSDI '22)_ - Synergy 关注固定规模多租户集群里的 DNN job packing 来减少 fragmentation，Eva 则把 instance provisioning 本身也纳入了按需付费云环境里的优化目标。
- _Tian et al. (SoCC '22)_ - Owl 依赖预先 profile 的 interference 信息来做 resource-efficient 的 FaaS 调度，而 Eva 在线学习 co-location throughput，并把它直接接进 cluster-wide cost objective。
- _Yang et al. (NSDI '23)_ - SkyPilot 关心的是该从哪个 cloud、哪个实例市场租机器，Eva 则把 procurement 视为正交问题，重点放在单个 cloud-based cluster 内部的 packing 与重配置。

## 我的笔记

<!-- empty; left for the human reader -->
