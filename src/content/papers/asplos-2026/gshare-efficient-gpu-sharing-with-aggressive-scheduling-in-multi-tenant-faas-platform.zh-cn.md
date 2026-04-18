---
title: "gShare: Efficient GPU Sharing with Aggressive Scheduling in Multi-tenant FaaS platform"
oneline: "gShare 把 GPU 从 FaaS 的 keep-alive 实例中解耦，用细粒度 vGPU 重映射和松弛感知调度压低 GPU 成本，同时稳住延迟目标。"
authors:
  - "Yanan Yang"
  - "Zhengxiong Jiang"
  - "Meiqi Zhu"
  - "Hongqiang Xu"
  - "Yujun Wang"
  - "Liang Li"
  - "Jiansong Zhang"
  - "Jie Wu"
affiliations:
  - "China Telecom Cloud Computing Research Institute, Beijing, China"
  - "China Telecom Cloud Technology Co. Ltd., Chengdu, China"
  - "China Telecom Cloud Technology Co. Ltd., Guangzhou, China"
  - "Temple University, Philadelphia, United States"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790168"
tags:
  - serverless
  - gpu
  - virtualization
  - scheduling
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

gShare 把 FaaS 平台里的 GPU 视为可回收、可细粒度切分的 vGPU slice，而不是永久绑在 warm function 上的资源。它把内核级 vGPU 重映射、基于 checkpoint 的模型保存/恢复，以及按 deadline slack 做延迟决策的调度器组合起来。论文表明，这样可以在保持超过 `95%` 延迟目标达成率的同时，把 GPU 用量相对 keep-alive 基线降低 `43%-63%`。

## 问题背景

这篇论文抓住的是现有 FaaS 抽象与 GPU 推理之间的结构性错配。生产级 serverless 平台已经能把 CPU 和内存做得很细粒度，而且空闲 CPU 函数实例也比较容易回收；但 GPU function 往往只能按很粗的单位配置，并且一旦实例被保活，GPU 就会一直跟着实例走。作者统计 TensorFlow Hub 与 Hugging Face 上下载量最高的 3,000 个模型后发现，`66.4%` 的模型小于 `1GB`，`78.1%` 小于 `4GB`，因此按 `1GB` 粒度配置 GPU 时，显存超配浪费最高可达 `85%`。

warm-instance 策略又把成本问题进一步放大。因为 GPU cold start 比 CPU 更慢，云厂商通常会把空闲 GPU function 保活以避免重复初始化，但空闲 GPU 的成本远高于空闲 CPU。论文测得，针对 GPU function 的 keep-alive 策略会带来大约 `10x` 的更高空转成本。已有 serverless GPU 共享方案试图通过 host memory 与 GPU 之间的模型 swapping 来回收这部分浪费，但它们依赖 proxy 风格控制面，并且主要按 popularity 一类启发式做交换，而不是按请求 deadline 来做。真正的问题因此是：在多租户、VM 隔离的 FaaS 平台里，怎样足够激进地共享 GPU 来节省成本，同时又不把资源复用变成额外排队和 SLO 违约？

## 核心洞察

论文最重要的主张是：只要把 GPU 的所有权从函数实例的存活状态中解耦，serverless GPU 的成本效率就会明显提升。如果一个函数能保留自己的内存镜像，同时把 GPU slice 交还给平台，那么平台就能在租户之间回收和再分配 GPU，而不必为每个 warm instance 长期支付整块 GPU 的保活成本。共享决策也不该由 popularity 驱动，而应由 deadline slack 驱动：那些 swap time 加 execution time 已经逼近延迟上限的请求保留私有缓存 slice，其余请求则采用 lazy scheduling，在 slack 快耗尽时才真正决定复用还是新分配。

## 设计

gShare 由三个关键部件组成。第一部分是面向 microVM 型 FaaS worker 的细粒度 vGPU 层。平台把 GPU 切成最小 `128MB` 显存的 slice，并按比例限制计算资源；它没有在 guest 内拦截用户态 CUDA 调用，而是把 GPU 虚拟化做在内核态，依赖 `vfio-mdev`、direct I/O 和每个 vGPU 的独立 channel 来维持兼容性与隔离。

第二部分是把函数内存管理与 GPU 绑定关系拆开。gShare 的 "pseudo offloading" hot-plug 设计会在回收 GPU 时保留 vGPU 连接元数据，只释放底层硬件资源，因此 hot-plug 时延可以从大约 `0.7s` 压到不到 `1ms`。模型状态通过 CUDA checkpoint/restore 保存到共享 host-memory pool；在快路径下，系统常常可以依靠缓存快照和 device memory overwrite，避免传统方案里成对出现的完整 swap-out 与 swap-in。

第三部分是把资源共享和 SLO 约束一起考虑的请求调度器。论文先把理想问题形式化为一个 mixed-integer nonlinear program，在 deadline 约束下最小化活跃 GPU slice 数量；真正实现时则采用在线启发式算法 Dual-Queue Lazy Scheduling。若某个请求的预测 swap time 加 execution time 已经接近延迟上限，它会被放进 `cacheQueue`；其余请求进入按 deadline slack `theta - I - D_hat` 排序的 `shareQueue`。调度器会等到 slack 归零时才真正 dispatch，然后复用最合适的共享 slice；如果找不到，再新分配一个。

## 实验评估

实验部署在一个 20 台服务器的集群上，配有 64 张 NVIDIA A100 GPU（每张 `40GB`），并划分出从 `128MB` 到 `40GB` 的九类 vGPU slice pool。工作负载来自三个真实生产集群的一周 trace，默认延迟目标设为各函数 `p90` 执行时间的 `1.5x`。对比基线包括 Keepalive、FaasCache、FaaSwap、NoCache，以及一个在请求到达时立即分配资源的 FIFO 版本。

最核心的结果是，gShare 在三组 trace 上分别把 GPU 用量降低了 `63%`、`47%` 和 `43%`，同时函数性能仅比 Keepalive 略差，并且整体上仍能满足超过 `95%` 的延迟目标。相对于论文视为当前最好 serverless GPU sharing 方案的 FaaSwap，摘要与引言给出的结论是：gShare 可进一步降低 `24%-58%` 的云成本，并取得 `1.8x-2.7x` 更好的综合成本/性能表现。gShare 对 bad requests 的 `p95` 延迟只增加大约 `15%`，而 `p50` 基本不受影响，这说明 lazy scheduling 主要改变的是尾部，而不是常态路径。

更细的拆分强化了这个判断。Table 2 显示，在 gShare 中，swap 和调度等待对那些最终满足目标的请求影响都低于 `1%`；而在几乎所有方法里，真正导致违约的主要原因仍然是模型 swap 时间本身。工程层面的结果也比较扎实：满配额 vGPU 与物理 GPU 几乎没有可见性能差距，不同 vGPU 配额下的模型吞吐近似线性缩放，而且在线调度算法能达到离线最优解大约 `75%` 的成本效率，同时决策速度比 MINLP 求解器快 `10x-100x`。论文最后把这些收益折算为经济价值，估算在 AWS 定价下每个典型集群每年可节省约 `$330,000`，在 Aliyun 定价下最高约 `$400,000`。

## 创新性与影响

相较于 _Yu et al. (ATC '25)_ 归档的 Torpor/FaaSwap 路线，gShare 最关键的一步是拿掉 proxy-centric 的共享路径，转而采用内核级 vGPU 重映射与基于 slack 的调度。相较于 _Yang et al. (ASPLOS '22)_ 这类证明 serverless inference 可以做到低延迟的工作，gShare 更关注的是在 VM 隔离约束下，怎样把 GPU-backed serverless inference 做得“够密、够省”。因此它既是一篇机制论文，也是一个很直接的云成本结果。

## 局限性

这篇论文的调度模型默认请求已经对应到预启动的函数实例，因此它并没有真正解决 GPU sharing 与高 cold-start 比例场景的耦合问题。当前实现也强烈依赖 NVIDIA GPU 和大量内核工程；重写 `57` 个 `ioctl` 接口、维护大约 `60,000` 行控制路径代码，本身就是明显的部署门槛，而 AMD 支持在论文中也明确还在进行中。

算法层面同样存在边界。gShare 的 vGPU 时间片在单个 kernel 内不可抢占，因此长 kernel 仍可能造成资源利用不足和排队干扰。它的调度器也是 server-local 的，没有真正覆盖 cluster-level 的负载均衡与 admission control；对 FaaSwap 的比较也基于作者自行重实现，而不是公开 artifact。

## 相关工作

- _Yu et al. (ATC '25)_ — Torpor/FaaSwap 同样通过模型 swapping 共享 serverless GPU，但 gShare 用直接 vGPU 重映射和 deadline-slack 调度替代了它的 proxy 型控制面。
- _Yang et al. (ASPLOS '22)_ — INFless 证明了 serverless inference 可以做到低延迟，而 gShare 关注的是在 microVM 隔离下做可回收的 GPU 分配与跨租户共享。
- _Crankshaw et al. (NSDI '17)_ — Clipper 研究的是 serverful 场景中的低延迟模型服务与调度，不涉及 gShare 这种 VM 级 GPU 虚拟化和 keep-alive 成本模型。
- _Agache et al. (NSDI '20)_ — Firecracker 提供了 VM 隔离型 serverless 的 microVM 底座，但并不处理 accelerator virtualization 或 GPU sharing。

## 我的笔记

<!-- empty; left for the human reader -->
