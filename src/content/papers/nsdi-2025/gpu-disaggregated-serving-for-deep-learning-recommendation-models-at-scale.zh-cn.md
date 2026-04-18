---
title: "GPU-Disaggregated Serving for Deep Learning Recommendation Models at Scale"
oneline: "Prism 把 DLRM 切成 CPU 和 GPU 两个子图，在 RDMA 连接的 CN/HN 资源池上分离执行，把训练节点里闲置的 GPU 变成弹性推荐服务容量。"
authors:
  - "Lingyun Yang"
  - "Yongchen Wang"
  - "Yinghao Yu"
  - "Qizhen Weng"
  - "Jianbo Dong"
  - "Kan Liu"
  - "Chi Zhang"
  - "Yanyi Zi"
  - "Hao Li"
  - "Zechao Zhang"
  - "Nan Wang"
  - "Yu Dong"
  - "Menglei Zheng"
  - "Lanlan Xi"
  - "Xiaowei Lu"
  - "Liang Ye"
  - "Guodong Yang"
  - "Binzhang Fu"
  - "Tao Lan"
  - "Liping Zhang"
  - "Lin Qu"
  - "Wei Wang"
affiliations:
  - "Hong Kong University of Science and Technology"
  - "Alibaba Group"
conference: nsdi-2025
tags:
  - ml-systems
  - gpu
  - disaggregation
  - rdma
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`Prism` 是一个面向生产环境的 DLRM serving 系统，它把推荐模型切成 CPU-heavy 和 GPU-heavy 两个子图，分别运行在通过 RDMA 互联的 CPU nodes (`CNs`) 与 GPU nodes (`HNs`) 上。真正重要的不只是“远端 GPU 也能跑推理”，而是它能把训练服务器里原本会被闲置的 GPU 真正变成可用容量，同时不把延迟打爆：在生产部署中，Prism 把 CPU fragmentation 降低了 53%，把 GPU fragmentation 降低了 27%，并在大促高峰时节省了超过 90% 的 GPU。

## 问题背景

论文的出发点，是数据中心的硬件形状与 deep learning recommendation models 的真实资源画像并不匹配。DLRM 并不是一个纯粹 GPU-bound 的工作负载。它的 sparse embedding lookup 需要很大的内存容量和大量 CPU cores，而真正明显适合 GPU 的主要是后面的 dense MLP 或 transformer 类层。在 Alibaba 的生产集群里，一个典型 DLRM 实例会申请 48 个 CPU 和 1 个 GPU，而一台训练服务器常见配置是 96 个 CPU 和 8 个 GPU。这样一来，两份 DLRM 实例就可能吃满整机 CPU，却让 6 个 GPU 处于空闲且无法再被其他任务使用的状态。

这种失配在弹性负载下会更严重。推荐流量存在明显的日周期波动，峰谷比超过 6x；在季节性购物活动期间，负载还会比平日高峰再高约 1.3x。为最坏情况建设一支独立推理集群成本过高，所以运营方自然希望在流量尖峰时临时向训练集群借容量。但在 monolithic servers 上，这个策略依然很低效：训练节点的 CPU-to-GPU ratio 很低，而论文里的生产轨迹显示，超过 90% 的 DLRM 都需要大于 20 的 CPU-to-GPU ratio。也就是说，额外的 GPU 明明存在，却因为服务器整体资源配比不对而无法被有效利用。

因此，论文要解决的问题不只是“把某个模型跑快一点”，而是如何让 CPU 和 GPU 的供给解耦、各自独立扩缩容，并且在突发流量下仍然满足几十毫秒级的在线推理 SLO。困难之处在于，一旦做 disaggregation，请求关键路径上就会多出网络传输与调度复杂度。

## 核心洞察

这篇论文最重要的洞察是：DLRM 在算子层面有非常清晰的资源分界，因此最合适的 disaggregation 单位不是 CUDA API，也不是底层硬件，而是 computation graph 本身。Embedding 相关算子主导 CPU 时间，而 matrix multiplication 与 attention 主导 GPU 时间。更关键的是，在线 DLRM 在部署后虽然参数会持续更新，但计算图结构本身基本稳定，因此 Prism 可以一次性把图切好，然后长期稳定地独立扩展两侧资源池。

这比 API-level GPU remoting 或 hardware-level GPU pooling 更现实。API remoting 把所有 CUDA 调用一视同仁，几乎不给 DLRM 结构化优化留下空间；硬件级 disaggregation 则需要昂贵的基础设施改造，而且往往只能限制在机架内。Prism 选择 graph-level disaggregation：把 CPU- 和 memory-intensive 的算子留在 `CNs`，把 GPU-efficient 的后缀子图卸载到 `HNs`，再依靠高速 RDMA、拓扑感知放置与流量控制，把新增延迟压回 SLO 范围内。

## 设计

Prism 的一个务实选择，是把自己插入现有生产优化流水线的末端，而不是替换原有框架。模型开发者仍然照常使用系统里的各种优化选项；等这些 pass 都完成后，Prism 再对最终图做重写，以支持 disaggregated serving。它的 partitioner 从 GPU-efficient 的种子算子开始，向上游和下游做 DFS 风格的着色扩展，尽可能把适合 GPU 的工作收入同一个子图，同时在遇到 embedding lookup 这类 CPU-intensive 算子时停止。最终得到的结果，是一个接收原始请求的 `CN` 子图，以及一个接收中间 tensor 的 `HN` 子图。

为了降低跨节点通信成本，partitioner 还做了两类关键优化。第一，它尽量把 constant subgraph 保留在 `HN` 一侧，这样常量表达式只需要计算一次并缓存，而不必反复跨网络传输。第二，如果多个待传输 tensor 都源自同一个祖先 tensor，Prism 会比较代价，在更划算时只传祖先 tensor。运行时把远端部分封装为统一的 `FusedGraphOp`，配合共享内存池与 GPUDirect RDMA，使得待发送数据在生成时就直接落进 RPC 子系统的 buffer 里。对小 tensor 它使用 RDMA send/recv，对大 tensor 则使用 RDMA write。论文报告这些传输优化可带来 19-181% 的性能提升，并指出在生产里有 80% 的服务每次请求向 `HN` 发送的数据量低于 10 MiB。

第二个核心部件是 topology-aware resource manager。Prism 会把同一服务的实例约束在同一个 pod 内，因为跨 pod 的 RDMA 会带来超过 50% 的性能损失；在 pod 内，它又优先把实例放到同一个 access switch 下；在节点内部，则根据 GPU-to-RNIC 或 CPU-to-RNIC 的路径长短给资源分配打分，优先选择位于同一 PCIe switch 下的 GPU 与 RNIC。论文测得，较差的 GPU-RNIC 拓扑会让 GPUDirect RDMA 吞吐下降 21-36%，所以这个细节并不只是实现技巧，而是性能前提。

第三个部件是 SLO-aware communication scheduler。系统显式处理 many `CNs` fan-in 到少量 `HNs` 时形成的 incast。Prism 用一个 window-based admission 机制限制同时发送量，通过 RNIC 和交换机返回的 congestion notification packets 自适应调整窗口大小，并把被延迟的请求按 earliest deadline first 排序，而不是简单 FCFS。它的目标非常直接：尽可能让更多请求在各自 deadline 之前启动传输，从而满足端到端 SLO。

## 实验评估

这篇论文的评测非常偏向真实生产环境。作者使用了五个来自 Alibaba 线上系统的推荐模型，embedding tables 规模从 100 GiB 到 700 GiB 不等。默认的 `HN` 配置为 128 个 CPU cores、8 张 80 GiB 的 A100，以及 4 张 200 Gbps RNIC；`CN` 则有 128 个 CPU cores 和 1 张 200 Gbps RNIC。对比基线包括现有优化过的 monolithic serving 系统，以及一个 local disaggregation 的消融版本，即图虽然被切开，但仍然放在同一台物理机上。

在顺序执行单个请求的悲观场景下，remote disaggregation 确实有额外代价，平均延迟会上升 10-38%。但在持续高负载下，Prism 才真正体现价值：它经常能同时降低延迟并提高 goodput，相比 monolithic baseline 更好地规避 GPU 队列里的 head-of-line blocking。原因在于 `FusedGraphOp` 避免了多个请求的 GPU kernels 互相交错，同时也把 host-to-device 传输变成了 device-to-device 的 RDMA 传输。论文特别指出一个较难的 `Model-XL`：它每个请求要传超过 9 MiB，但 GPU 计算时间不到 1 ms；即便如此，Prism 的性能损失也最多只有 6%。

资源效率上的收益更有说服力。对相同 goodput 而言，总 CPU 消耗与 baseline 接近，但 GPU 节点上的 CPU 使用量下降了 15-84x，而这正是过去让 GPU 被“搁浅”的资源维度。在单台多 GPU 节点上，Prism 能把总吞吐提高 5-9x，因为它可以在一台服务器上部署远多于 baseline 的 serving 实例。开启 MIG 后，`Model-XS` 甚至可以在一台服务器上扩展到 24 个 `HN` 实例，达到 baseline 的 9x 吞吐。

真正支撑论文结论的，是集群级结果。在一个分配率约 90% 的生产 GPU 集群里，Prism 将 fragmented CPU resources 降低了 53%（18k cores），将 fragmented GPUs 降低了 27%（60 GPUs）。在季节性大促期间，三项线上服务合计只需要借用 6 台 A100 节点；而在旧的 monolithic 部署方式下，为满足同样需求最多要借 70 台 A100 节点，这就是论文声称 GPU 节省超过 90% 的来源。考虑到这个领域里此前并没有可直接对比的生产级 GPU-disaggregated DLRM 系统，这样的 baseline 选择是合理的，不过也意味着论文更擅长展示“上线前后”的运营收益，而不是与广泛外部系统做横向比较。

## 创新性与影响

这篇论文的新意并不只是“把 DLRM 放到 RDMA 网络上跑”。它把 graph-level model partitioning、topology-aware placement 与 SLO-aware network scheduling 组合成了一条完整的生产路径，使原本不适合 DLRM 的异构训练集群也能被借来服务推荐推理。这一点让它同时区别于通用的 GPU remoting 系统，以及那些仍然默认 monolithic server 的 recommender serving 工作。

它首先会影响大型推荐系统的基础设施团队，但更广泛地说，datacenter systems 与 ML systems 社区也会引用它。原因在于它展示了一个很强的工程结论：当 operator split、流量形状和放置策略都具有强结构性时，一个针对应用量身定制的 disaggregation 设计，确实可以优于更通用、更优雅的抽象层。

## 局限性

Prism 的设计明显建立在 DLRM 特有的结构上，也就是 embedding-heavy 的 CPU 工作与 dense GPU 工作之间有稳定边界。论文认为这种图结构在部署期间基本不变，但它并没有展示：如果模型的 cut 不那么明显，或者中间 activation 大很多，这套 heuristic partitioner 还能否保持效果。论文里较为理想的通信条件也很关键：80% 的服务每次请求只向 `HN` 发送不到 10 MiB 数据，返回路径也很小。若跨切分边界的数据更重，收益可能会明显变差。

部署假设同样比较严格。Prism 把同一服务的实例限制在一个 pod 内，因为跨 pod 放置会带来超过 50% 的性能损失，这说明系统依赖局部拓扑上的剩余空间。论文还报告了一个尚未根治的生产问题：在混部场景里，容器 overlay networking 下的 TCP 流量会干扰 RDMA，严重时需要把 offline tasks 驱逐出去。这是一个真实的运维约束，而不是已经被彻底解决的问题。

最后，评测虽然在内部生产证据上很强，但在外部可复现性上相对有限。大部分实验基于优化过的内部 TensorFlow 栈，graph partitioner 是启发式而非最优性可证明的算法，而且论文无法与独立的 disaggregated inference 系统做正面对比，因为在这个细分领域里几乎没有现成系统可比。

## 相关工作

- _Ke et al. (HPCA '22)_ - `Hercules` 关注在 monolithic heterogeneous servers 上为 DLRM inference 做资源配置，而 `Prism` 进一步把 CPU 与 GPU 执行拆到不同节点池上。
- _Li et al. (EuroSys '23)_ - `Lyra` 研究的是共享集群里训练与推理的弹性混部，`Prism` 则专门解决借来的训练节点为什么对 CPU-heavy DLRM 不够好用的问题。
- _Duato et al. (HPCS '10)_ - `rCUDA` 通过远程化 CUDA API 暴露远端 GPU，而 `Prism` 直接切分 DLRM 计算图，并联合优化通信、放置与 SLO-aware 调度。
- _Shan et al. (OSDI '18)_ - `LegoOS` 提供通用的硬件 disaggregation 操作系统抽象；`Prism` 则是一个面向推荐推理场景、范围更窄但经过生产验证的应用级系统。

## 我的笔记

<!-- empty; left for the human reader -->
