---
title: "PAPAYA Federated Analytics Stack: Engineering Privacy, Scalability and Practicality"
oneline: "PAPAYA 把 SQL 式预处理放到设备端，把 TEE 缩到 Secure Sum、阈值过滤和 DP 加噪，从而把联邦分析扩展到近 1 亿部手机。"
authors:
  - "Harish Srinivas"
  - "Graham Cormode"
  - "Mehrdad Honarkhah"
  - "Samuel Lurye"
  - "Jonathan Hehir"
  - "Lunwen He"
  - "George Hong"
  - "Ahmed Magdy"
  - "Dzmitry Huba"
  - "Kaikai Wang"
  - "Shen Guo"
  - "Shoubhik Bhattacharya"
affiliations:
  - "Meta"
conference: nsdi-2025
category: security-and-privacy
tags:
  - security
  - confidential-computing
  - observability
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PAPAYA 把联邦分析拆成三段：设备端做 SQL 风格的筛选与分组，SGX TEE 里的可信聚合器只负责 secure sum、阈值过滤和可选的差分隐私加噪，外围再包一层不可信编排器。靠这种分工，Meta 可以在近 1 亿部 Android 手机上运行保护隐私的监控查询，在 16 小时内覆盖约 85% 设备、4 天后超过 96%，同时让 central DP 的精度接近无隐私噪声的基线。

## 问题背景

这篇论文解决的是一个很现实的张力：大型移动平台必须持续做产品监控、实验分析、使用统计和模型质量评估，但把原始用户数据直接上传到中心化仓库，在法规、用户预期和工程风险上都越来越不可接受。已有 federated analytics 系统证明了方向可行，但作者认为它们通常会在三个维度里至少输掉一个：过度依赖 local privacy 机制导致结果太噪，查询表达能力太弱，或者根本扩不到数百万乃至数十亿台异构设备。

这里的工作负载也和 federated learning 明显不同。FA 需要的是小消息、很少的轮数，以及更广泛的查询形态；FL 则是围绕模型更新做很多轮交互，每轮只拉一小批客户端。因此，一个移动端分析系统不能假设客户端会同步参与、稳定在线，或者愿意为每个查询跑一套很重的协议。最直接的替代方案，比如为每个指标量身定做安全协议，或者依赖多轮交互式搜索，都太慢、太怕掉线，也太难让普通分析师真正使用。论文的目标不是证明某个密码学原语，而是做出一个能在生产环境里回答日常监控问题、又不突破隐私和设备资源边界的系统。

## 核心洞察

PAPAYA 的核心判断是：只有把绝大多数查询语义留在设备端、把绝大多数可信后端逻辑压缩成一个可复用原语，联邦分析才会真正实用。设备端运行 SQL 风格的本地变换，把原始日志压成紧凑的键值摘要，例如 mini histogram。只要报文在上传前已经完成了分组和压缩，后端就不必理解每一种分析需求；它只需要聚合加密后的 bucket 值，在需要时加入隐私噪声，过滤掉支持度太低的 bucket，并释放匿名化后的结果。

这同时改善了隐私和工程复杂度。隐私上，设备可以通过 remote attestation 验证将要接收自己数据的 TEE 二进制，并且 TEE 里的代码面被故意做得很小、容易审计。可扩展性上，围绕 Secure Sum and Thresholding 设计的一次性算法避免了长时间交互协议，对晚到和直接掉线的客户端都更宽容。作者进一步强调，counts、sums、means、heavy hitters、heatmaps，甚至 quantiles，都可以用“设备端先做变换，后端围绕 histogram 聚合再加后处理”的思路来表达。

## 设计

系统分成三个区域。不可信编排器 UO 负责注册查询、分配查询、发布结果和转发客户端通信；客户端 runtime 负责本地存储、调度、守护规则与执行；可信安全聚合器 TSA 则是每个查询对应的 enclave 实例。分析师编写 federated query 时，要给出两部分内容：一部分是在设备端执行的类 SQL 查询，用来从本地状态提取 dimensions 和 metrics；另一部分是服务器端聚合规范，指定 COUNT、SUM、MEAN、quantile 等 primitive，以及隐私参数和结果输出位置。

客户端执行又分成 selection 和 execution 两个阶段。selection 阶段里，设备从 UO 拉取活跃查询，检查自己是否有相关数据，验证查询里的隐私参数是否满足本地 hardcoded guardrails，并可用本地随机性做 subsampling。execution 阶段里，客户端把多个查询打包，针对本地 store 跑 SQL，随后对目标 TSA 做 remote attestation、建立加密信道，只上传已经压缩后的报告。论文特别指出，设备侧主要开销不是 SQL 计算，而是进程启动和与服务器通信，因此 batching 是能否实用的关键。

TEE 内部把跨设备聚合统一成 Secure Sum and Thresholding。每个查询从一个空 histogram 开始。客户端发送加密后的键值对，enclave 解密后立刻把它们折叠进当前 histogram，再丢弃单设备明文。等到积累了足够时间和足够多设备之后，enclave 会同时对 bucket 的 count 和 sum 加入隐私噪声，删除 noisy support 低于阈值的 bucket，并把匿名化 histogram 交给 UO。根据随机性放置的位置不同，同一套结构可以支持 central DP、local DP 或 distributed sample-and-threshold。

真正让系统可部署的是这些操作层细节。PAPAYA 会随机化设备同步和上报时间，以便把指向 TEE 的 QPS 拉平；会把设备上的多个查询合批执行，摊薄固定开销；会在服务器侧按查询分片；还会周期性快照中间聚合状态，以便某个 aggregator-TSA 对失败后，由新的实例接手恢复。附录 A 说明了同样的 histogram 抽象如何扩展到 quantile：不是做很多轮二分搜索，而是一次性收集固定层级的 histogram 树，随后离线恢复近似分位数。

## 实验评估

这篇论文的评估是生产部署观察，而不是实验室原型 benchmark。查询运行在近 1 亿部 Android 手机上，客户端后台任务单次超时为 10 秒、每天最多执行两次。作者重点研究的是典型监控查询：请求 round-trip time 的直方图，以及请求计数的直方图。数据异质性非常明显。多数设备只贡献一个采样值，但也有一些设备会贡献几十个，极少数超过 100 个；网络 RTT 的众数大约在 50 ms，但长尾会延伸到 500 ms 以上。

第一个核心结果是收集速度。在相隔 6 小时启动的三次相同 RTT 查询中，覆盖曲线几乎一致，说明一天中的启动时刻并不是主导因素。覆盖率在前 16 小时里大致线性增长到约 85%，24 小时达到约 90%，96 小时后超过 96%。尾部主要来自设备本身的间歇活跃，而不是系统吞吐瓶颈。覆盖速度和网络质量也只有弱相关：低 RTT 设备会稍早一些上报，但差距不大。

第二个结果是精度。对于 RTT 和事件计数直方图，federated 结果与中心化 ground truth 之间的 total variation distance 会在数小时内降到很小，并在运行后期变得几乎可以忽略。到大约 12 小时时，约一半客户端已经 check in，此时得到的 histogram 就已经很接近最终答案。附录 A 对 quantile 也给出了类似结论：48 小时后，daily RTT 的最大 CDF 误差为 0.32%，hourly RTT 为 0.49%。

第三个结果是隐私机制的精度代价，这也是论文最能支撑其 TEE 中心化设计的部分。在 `epsilon = 1`、`delta = 10^-8` 的设置下，central DP 和 distributed sample-and-threshold 与 no-DP 基线非常接近，而 local DP 的噪声大约高一个数量级。以 RTT 直方图为例，LDP 在整个过程中都明显高于其他机制，而 central DP 的曲线几乎和未加噪版本重合。hourly 事件计数更难，因为信号量只有 daily 的约 1/34，所以 sample-and-threshold 在那里会丢失更多信息。即便如此，论文仍然有力地说明：如果你接受经过 attestation 的 enclave 信任模型，那么联邦分析可以比纯 local DP 方案保留得多得多的效用。

## 创新性与影响

PAPAYA 的任何单个组成件都不是第一次出现。Secure aggregation、SGX attestation、本地变换、差分隐私都早已有之。真正的新意在于，论文把这些组件工程化为一个有清晰信任边界的生产 federated analytics 栈：分析师写的查询逻辑留在设备端，最小化的 TEE 只做可复用的聚合工作，其余控制平面全部按不可信对待。论文也很清楚地解释了为什么 FA 不能被简单看成 FL 的一个附属模式。

因此，这篇论文的价值不只属于 Meta。对构建隐私保护 telemetry 的工程团队，它提供了一个证明：一次性、设备大规模参与的 FA 是可以落地的。对 TEE、安全聚合和隐私系统研究者，它则给出了一份部署蓝图，说明哪些可信计算基必须保持极小，哪些隐私模型在真实系统里最实用，以及剩余的运维痛点到底在哪里。

## 局限性

这个信任模型依然强烈依赖 SGX 一类 TEE。论文明确承认需要考虑已知的 SGX 攻击并加上缓解措施，所以它的隐私故事并不是“只靠密码学”。如果读者不接受 enclave 信任，那么 central DP 那组最好看的精度结果就不再那么有说服力，系统也只能退回到效用更差的 local 或 distributed 模型。

论文还主动缩小了若干作用域。恶意客户端试图 poison 输出基本不在本文处理范围内，作者只依赖每份报告的贡献界和额外的二进制完整性控制来限制影响。隐私预算管理也主要是按查询做的实用主义方案，作者更强调避免对同一批数据反复发问，而不是给出一套完整的纵向用户级预算框架。最后，这个系统最擅长的仍是 aggregation 类分析。论文展示了 counts、sums、means、histograms 和 quantiles，但更复杂的分析要么需要自定义代码，要么需要扩展 primitive 集。

## 相关工作

- _Bonawitz et al. (CCS '17)_ - Practical secure aggregation 通过客户端之间的多方协议隐藏中间值，而 PAPAYA 使用可远程证明的 TEE，避免客户端之间协调，并更直接地支持阈值过滤。
- _Corrigan-Gibbs and Boneh (NSDI '17)_ - Prio 在多服务器之间对 secret-shared 客户端报告做聚合；PAPAYA 则把 histogram primitive 放进单个 TEE 支撑的聚合器里，并把重点放在移动端生产部署上。
- _Roth et al. (OSDI '20)_ - Orchard 在没有 trusted core 的前提下提供大规模差分隐私分析；PAPAYA 则接受 enclave trust，以换取更简单的后端和对 central-DP 风格查询更高的效用。
- _Huba et al. (MLSys '22)_ - 面向 federated learning 的 PAPAYA 共享了隐私目标和 TEE 风格，但本文强调 federated analytics 需要一套单独系统，去优化一次性、小消息、分析师可编写的查询，而不是反复的模型训练轮次。

## 我的笔记

<!-- 留空；由人工补充 -->
