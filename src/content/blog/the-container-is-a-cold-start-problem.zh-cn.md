---
title: "The Container is a Cold-Start Problem"
oneline: "2025 年的容器其实已经不再是隔离抽象——它是一个冷启动问题；近期系统论文给出的答案惊人地一致：别再从零启动，改从快照里恢复。"
topic: containers
tags:
  - serverless
  - isolation
  - datacenter
  - caching
  - virtualization
total_words: 4200
reading_time_minutes: 10
written_by: "Claude Opus 4.7 (Claude Code)"
publish_date: 2026-04-19
draft: false
---

## 核心论点

容器这个抽象早已离开了隔离研究的前线。namespaces 和 cgroups 的争论多年前就已尘埃落定，Linux 内核的攻击面也磨得足够平整，工业界终于能心安理得地让互不信任的租户共用一台物理机；每家主流云的 serverless 则把 runc 式原语垫在一层 MicroVM 之下。今天还贴着容器标签的论文其实只在讨论同一件事——它启动得太慢——而它们给出的答案又出奇地一致：别再从零启动，把已经初始化好的状态做成快照，现用现复活。

## 背景与铺垫

翻开任何一本讲容器的书，介绍的都是一套隔离机制：process、mount、network、pid、user、ipc 六类 namespaces 决定容器能看见什么，cgroups 决定它能用掉多少资源，seccomp-bpf 决定它能向内核发什么系统调用。整个 2010 年代的容器研究就围着这些机制转，真正的核心问题只有一个——Linux 这样的单体内核能不能在没有 hypervisor 的前提下安全地多租户？坦率地说，大多数场景下答案是肯定的；而在那些保证必须更硬的角落里，MicroVM 又会悄悄爬回来垫在容器底下。AWS Firecracker 和 Kata Containers 就是这一轮的赢家。

但一旦容器真正扛起生产级的 FaaS 流量——[AWS Lambda](https://aws.amazon.com/blogs/compute/under-the-hood-how-aws-lambda-snapstart-optimizes-function-startup-latency/)、Azure Functions、蚂蚁集团的 serverless 基座——运维侧真正在意的就不再是攻击面，而是从请求抵达到用户代码跑出第一个字节之间那几毫秒甚至几秒。这就是冷启动；而它已经悄悄成了容器研究里唯一还值得拿去投顶会的前沿。

## 论据

### 研究的重心已经转移

看 2025 年跟容器沾边的论文到底把精力花在哪里，一目了然。清华与蚂蚁集团合作的 [AFaaS (Fork in the Road)](../papers/osdi-2025/fork-in-the-road-reflections-and-optimizations-for-cold-start-latency-in-production.md) 登上 OSDI '25，本质上是一份对蚂蚁线上 FaaS 的复盘：超过一半的函数冷启动概率在 0.75 以上，35% 的函数每次都冷启动，而真正有效的执行时间常常只有 50–100 ms。在这种分布里，一秒的冷启动就不是尾延迟噪声，而是主要成本本身。AFaaS 最终把 24× 并发下的生产冷启动压到了 6.97–14.55 ms。论文把自己标成 「reflections and optimizations」，这种体裁标签本身就是一个信号：领域已经懒得再问容器能不能更安全，而在死磕为什么最后这几秒就是下不去。

同样的故事在 ETH Zurich 的 [Dandelion](../papers/sosp-2025/unlocking-true-elasticity-for-the-cloud-native-era-with-dandelion.md) 里换了口音再讲一遍：它在 CHERI 上把 compute sandbox 的创建时间做到了 ~100 μs，普通 KVM 上也只需 ~220 μs——逐请求冷启动从此成为可行选项，而 Knative 为了藏住冷启动预留的 warm pool（在 Azure Functions 的 trace 上意味着 16× 于实际使用的内存常驻）则被直接砍掉 96%。[MettEagle](../papers/osdi-2025/metteagle-costs-and-benefits-of-implementing-containers-on-microkernels.md) 同期发在 OSDI '25，改在 L4Re 上搭建容器式的 compartment，空 compartment 冷启动 ~1 ms，而 runC 需要 ~70 ms。就算这篇论文在标题上还打着隔离牌，它在亮出实验结果时也先把启动时间摆到了前面。这就是当下的默认姿态：不管论文作者自以为在做安全还是做性能，冷启动都是那条主动脉。

### 解法几乎只有一个：别启动，从快照里恢复

更醒目的是，这批论文回答问题的方式高度一致。几乎没人再去打磨「启动本身」让它变快，它们都在试图绕开启动——把一个已经初始化完毕的实例的状态序列化下来，再到另一台机器上反序列化回去。

AWS 生产上的答案 [Lambda SnapStart](https://aws.amazon.com/blogs/compute/starting-up-faster-with-aws-lambda-snapstart/) 就是这条路：给初始化完的 Firecracker MicroVM 拍一张内存加磁盘的快照，切成 chunk 送进多层缓存，恢复时按 working set 惰性补页。正如 [Marc Brooker 写过的](https://brooker.co.za/blog/2022/11/29/snapstart.html) 那样，难点不是快照格式本身，而是如何在行星级舰队上把数据摆到合适的位置，让一次 demand page fault 不至于退化成一次慢速 S3 读。[Modal 的 gVisor 方案](https://modal.com/blog/mem-snapshots) 走的是同一条路，用 FUSE 支撑的 page file 把 `import torch` 的启动从 ~5 s 压到 ~1 s。Kubernetes 那边，kubelet 驱动的 CRIU 已经在 [v1.30 进到 beta](https://kubernetes.io/blog/2022/12/05/forensic-container-checkpointing-alpha/)，GPU 检查点也借 [CRIUgpu（CRIU 4.0）](https://www.devzero.io/blog/gpu-container-checkpoint-restore) 落地。平台厂商集体完成了同一次定义切换：容器就是可以被序列化的机器状态。

论文端也朝同一个方向收敛。ASPLOS '26 的 [WorksetEnclave](../papers/asplos-2026/worksetenclave-towards-optimizing-cold-starts-in-confidential-serverless-with-workset-based-enclave-restore.md) 把这套思路搬到 SGX 上，那边做快照更棘手，毕竟 enclave 的内存是加密并封印的。它让加密发生在 enclave 内部，离线采集执行过程中真正命中的页——论文把这堆页叫做「workset」——在线恢复时先只还原 workset，其余页等实际命中缺页时再带完整性校验补回。启动从秒级一路掉到 400–600 ms 以内，enclave 里 74%–95% 的页从未被复原过，因为热路径根本不会读到它们。这就是 SnapStart 按 chunk 按需加载的同一套算法，换了一种存储介质而已。

[AFaaS](../papers/osdi-2025/fork-in-the-road-reflections-and-optimizations-for-cold-start-latency-in-production.md) 把快照从「一张镜像」推成一棵树：level-0 是 OS seed，level-1 是语言运行时 seed，level-2 是用户代码 seed，由最贴近的祖先通过 copy-on-write 派生出新实例。这本身就是一套快照层级。OSDI '25 的 [BlitzScale](../papers/osdi-2025/blitzscale-fast-and-live-large-model-autoscaling-with-o-1-host-caching.md) 把同一条反射弧拉到 LLM 权重：整个集群只要有一份 host cache，就通过 RDMA 多播给新实例，部分加载的实例允许先拿已到手的那几层出 token。作者管它叫「参数广播」，但从机制上看就是张量粒度的 snapshot-restore——收益也照例是以 TTFT 衡量的冷启动胜出。

文件系统方向的论文则从另一侧把故事讲完。FAST '26 的 [CoFS](../papers/fast-2026/cofs-a-filesystem-for-fast-container-startup.md) 发现：容器启动时间里 76% 花在镜像拉取上，但拉下来的字节里只有 6.4% 会真正被读到；它离线为镜像树造一份最小完美哈希索引直接嵌进镜像本身，把元数据查询和已缓存的读都做到内核里。这就是对「镜像查表」这一环做快照。同一个会议的 [ThinkAhead](../papers/fast-2026/how-soon-is-now-preloading-images-for-virtual-disks-with-thinkahead.md) 学习每个镜像的 boot trace，在首次访问之前把 virtual disk 的块提前拉进来——这就是 SnapStart 的 chunk 预测逻辑搬到 EBS 上的版本。工业侧早就走在这条路上：[eStargz](https://github.com/containerd/stargz-snapshotter) 与 [zstd:chunked](https://github.com/containers/storage/pull/775) 把 lazy pull 标准化，镜像没下完也能跑；[AWS 的 SOCI](https://engineering.grab.com/docker-lazy-loading) 则以一份独立的 OCI 兼容索引让已有镜像不必重建就能享受相同待遇。这堆机制全都在对某一片切出来的状态——文件系统树、工作集、页表、权重张量——做快照，再配上一套惰性流式注入策略。

### 连网络论文也在做缓存

容器网络看起来最容易被圈成冷启动的飞地，但这套叙事已经悄悄渗透了进去。NSDI '25 的 [OnCache](../papers/nsdi-2025/oncache-a-cache-based-low-overhead-container-overlay-network.md) 观察到，Kubernetes overlay 的开销分散在 veth、conntrack、filter、routing、VXLAN 封装一整条链上，但某条流一旦建立起来，跨层叠加出的总结果就是稳定的。它干脆把这个合成结果记到 eBPF map 里，让快路径直接绕过 overlay。论文自己的说法是 caching 优化；从结构上看，那就是对网络快路径拍了一张快照，再按包恢复。ASPLOS '26 的 [SG-IOV](../papers/asplos-2026/sg-iov-socket-granular-i-o-virtualization-for-smartnic-based-container-networks.md) 把类似的动作下放到 SmartNIC 边界：socket 上方和下方的功能一并卸到网卡上，于是「容器网络」不再是为每条流临时拼起来的 packet pipeline，而是一组预先配置好的流式通道——预配置，就是快照。

把这些放在一起，一个听起来有点扫兴但切实成立的归纳就冒了出来：近期所有与容器相关的系统文献其实是同一篇论文的不同封面。它们都在说，运行一个容器里真正昂贵的那部分工作是*不必重复做*的工作；所谓的前沿，就是找出哪一片——镜像元数据、页表、enclave 页、权重张量、流表项、网络快路径——是那一片可以被序列化一次、粘贴多次的切片。

## 反方证据

对这套叙事最硬的反驳来自 [Dandelion](../papers/sosp-2025/unlocking-true-elasticity-for-the-cloud-native-era-with-dandelion.md)。它的主张是：快照只是在治标。冷启动之所以贵，是因为每个函数都要开一个 POSIX 风格的 sandbox，自带 guest OS 和完整网络栈；真正的修法是换编程模型，让你要启动的那个东西根本不再拥有这些组件。把 compute 函数定义成纯计算，通信统一交给一小撮 trusted function，sandbox 就能掉到 300 μs 以下——*不需要*快照机制，逐请求冷启动直接成为默认。换句话说，Dandelion 的立场是：snapshot-restore 整条路线攻击的是错误的抽象层，应当被替换而不是优化。如果哪天足够多的 workload 真的被重写成 Dandelion 这种分解结构，「冷启动等于快照」这套说法就会变成一段历史注脚。这是个真正意义上的对立框架，不是稻草人。

SOSP '25 的 [Quilt](../papers/sosp-2025/quilt-resource-aware-merging-of-serverless-workflows.md) 做了一个邻近但不同的动作：它不给 sandbox 做快照，而是把互相调用的函数编译合并成一个二进制，让那条本来要用快照去优化的 sandbox 边界压根就不存在了。工作流的中位延迟因此下降 45–70%，吞吐涨 2–13×，主要靠消掉跨函数 RPC——而那正是冷启动代价本来要分摊的开销。容器被变便宜的方式，是被变少。[MettEagle](../papers/osdi-2025/metteagle-costs-and-benefits-of-implementing-containers-on-microkernels.md) 提供第三种反驳路线：也许冷启动的账应当记在 Linux 的硬化机制头上，换个内核比把快照做得更精巧更划算。NSDI '25 的 [Leopard](../papers/nsdi-2025/making-serverless-pay-for-use-a-reality-with-leopard.md) 则提醒：serverless 的很大一块低效来自计费契约，而非沙箱机制本身。

诚实版本的论点应当承认两个 caveat。一，隔离研究没有死，它只是往栈下挪了一层，钻进 confidential computing（TEE、attested enclave、confidential VM）。那条线依然重要，但它是把容器当作打包单位来用，而不是在研究容器本身。二，snapshot 中心的叙事在*有状态*负载面前明显虚弱——OLTP、游戏会话、长连接——那些场景里的「容器状态」不是一段干净的执行前缀，没法物化下来重放。这套论点最有力的地方，仍然是短生命、无状态、高频调用那一类 workload。

## 这意味着什么

如果前面的论点立得住，它会对 2026 年如何思考容器系统产生几条实质影响。

*对平台建设者*，镜像比运行时更值得投入。安全-隔离这一层已经被做成通用件，真正拉开「快平台」与「慢平台」距离的，是你在整支舰队上序列化、分发、demand-page 一段状态的能力。AWS 先把 [SnapStart](https://aws.amazon.com/blogs/compute/starting-up-faster-with-aws-lambda-snapstart/) 背后那套多层缓存做出来，然后才去动本十年真正意义上的隔离改进——如果这个论点成立，那就是正确的优先级排序。

*对研究者*，真正有戏的原语是 snapshot，不是 namespace。近期机制层的大量工作——working-set 追踪、内容寻址共享、MPHF 元数据索引、参数多播分发、memoized overlay 路径——其实都在回答同一个问题：如何给运行中系统里的某一片状态做快照？还没被做好快照的那些切片仍然有巨大的空间：GPU kernel 状态（CRIUgpu 才刚刚起步）、数据库缓冲池、JIT 缓存、连接池状态。

*对用户*，推论更有意思：逐请求 sandbox 现在真的可行了。冷启动以秒计的年代它只是幻想；降到数百微秒这一档，它变成一个工程选择而已。当开一个 sandbox 的代价不高于一次函数调用，warm pool 那种「藏住冷启动」的 ergonomic 论证——也就是云厂商不能提供真正弹性的最后一根支柱——就会崩塌，而把不受信任的代码各自关进独立沙箱的安全论证反而会变得非常现实。

「容器」这个标签会继续存在——OCI 镜像、仓库、Kubernetes 的生态实在太大，改名不现实。但贴在这张标签下真正被研究的那件事已经悄悄换了：每一篇让容器更快的新论文，其实都是披着容器外衣的 snapshot 论文；剩下那几篇不是的，则在主张 snapshot 根本就是个错误答案。
