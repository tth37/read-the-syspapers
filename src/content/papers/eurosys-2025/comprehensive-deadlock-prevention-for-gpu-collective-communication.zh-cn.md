---
title: "Comprehensive Deadlock Prevention for GPU Collective Communication"
oneline: "DFCCL 把 GPU collective 的死锁处理下沉到可抢占的 daemon kernel，用自适应 on-GPU 调度替代跨 GPU 的全局调用顺序约束。"
authors:
  - "Lichen Pan"
  - "Juncheng Liu"
  - "Yongquan Fu"
  - "Jinhui Yuan"
  - "Rongkai Zhang"
  - "Pengze Li"
  - "Zhen Xiao"
affiliations:
  - "School of Computer Science, Peking University"
  - "OneFlow Research"
  - "National Key Laboratory of Parallel and Distributed Computing, College of Computer Science and Technology, National University of Defense Technology"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717466"
code_url: "https://github.com/Oneflow-Inc/dfccl"
tags:
  - gpu
  - ml-systems
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DFCCL 把 collective primitive 的等待循环视为天然的抢占点。每张 GPU 上常驻的 daemon kernel 会中断长时间无进展的 primitive、保存状态、再重排执行，所以环形依赖不再把 collective 卡死。按论文结果，这套机制大多数时候能贴近 NCCL，在一些训练任务上还更快。

## 问题背景

分布式 DNN 训练把 data parallelism、tensor parallelism、pipeline parallelism 都压在 collective communication 上，但 NCCL 一类实现天然容易死锁：collective 会占着 GPU 资源 busy-wait，资源本身又互斥，而现实里的 GPU 几乎没有可用的官方抢占能力。只要不同 GPU 以不同顺序发起 collective，环形等待就可能形成。

论文强调这不是偶发现象。站在通信库底层看，至少有三类基本死锁：单队列死锁、资源耗尽死锁，以及由 GPU synchronization 放大的死锁。第三类尤其麻烦，因为显式或隐式同步会让后续 collective 暂时用不到本来空闲的资源。作者的模拟显示，当乱序概率和 synchronization 概率都只有 0.004% 时，死锁比例仍可达到 6.94%。

现有方案只是尽量让应用别踩雷。Horovod、BytePS、KungFu、OneFlow，以及 Megatron 一类手工编排，本质上都靠额外的 CPU 逻辑去强制所有 GPU 以一致顺序进入 collective。场景一复杂、group 一重叠，或者运行时冒出不可完全控制的 synchronization，这种办法就会变得又脆又贵。

## 核心洞察

这篇论文最关键的判断是：就算硬件没有官方的 collective preemption，常见 GPU collective 仍然可以被安全打断。all-reduce、all-gather、reduce-scatter、reduce、broadcast 归根到底都由 send、recv、reduce、copy 这些 primitive 组成，而 primitive 本来就靠检查 connector 是否就绪来决定能不能继续执行。

于是，通信库可以把长时间等不到条件满足解释成一次安全让出，而不是无休止自旋。更关键的是，某个 GPU 已经写进 connector 的数据在它被换下之后依旧可见，所以 DFCCL 不需要新的中心协调者。每张 GPU 只要独立保存动态上下文、稍后恢复，就能把 collective 变成可暂停、可继续的工作单元。

## 设计

DFCCL 把库拆成两层：CPU 侧负责提交与回调，GPU 侧每卡常驻一个 daemon kernel。应用先注册 collective，再通过 `dfcclRun*` 异步发起；每张 GPU 都维护 submission queue、completion queue、task queue，以及 collective 上下文缓冲区。daemon kernel 不断取请求、选一个 collective、再执行它的 primitive sequence。

真正防死锁的是两阶段阻塞执行。对每个 primitive，daemon kernel 先在一个 spin threshold 内忙等 send 或 recv 条件；条件满足就继续；到阈值还没有进展，就保存动态上下文，例如当前 chunk ID 和被打断的 primitive ID，再切到别的 collective。静态元数据不变，所以恢复时不必把整个 collective 重来。

调度则靠 stickiness，也就是 task queue 位置和 spin threshold 的组合。排在最前面的 collective 拿到最大的初始阈值，后面的依次减小；一旦某个 primitive 成功执行，后续 primitive 的阈值还会继续提高。这样不同 GPU 会逐步收敛到同时跑同一个 collective，形成去中心化的动态 gang-scheduling。若遇到 synchronization 相关死锁，daemon kernel 还可以在空闲或长期无进展时主动退出，让 `cudaDeviceSynchronize()` 一类操作先完成，再按需重启。

## 实验评估

论文最扎实的证据来自防死锁实验。在 8 张 RTX 3090 的服务器上，8 个 GPU 以各自不同的随机顺序发起同一组 8 个 all-reduce，DFCCL 连续跑 200 轮都没有死锁，平均每个 block 大约发生 18,000 次 preemption。再把显式 GPU synchronization 插到这些乱序 all-reduce 之间，DFCCL 仍然能跑完 200 轮，此时每张 GPU 上的 daemon kernel 平均会主动退出约 360 次。对应的 NCCL 测试则是 100% 死锁。

代价也被论文量化了。若系统里维护 1,000 个 collective，DFCCL 每个 block 需要 13 KB shared memory 与 4 MB global memory，外加 11 KB global memory 存放计数器和共享元数据。completion queue 的优化把写入 CQE 的时间从约 6.9 us 压到 2.0 us；上下文加载约 0.45 us，保存约 0.05 us。

性能方面，DFCCL 基本贴近 NCCL。8 张 RTX 3090 上，4 KB all-gather 的端到端时延是 49.4 us，对比 NCCL 的 45.1 us，主要输在 I/O 开销；但到了 4 MB，DFCCL 的端到端时延变成 851.8 us，略好于 NCCL 的 855.2 us，而核心执行时间更低，分别是 828.0 us 与 847.9 us。训练任务里，ResNet50 数据并行相对 OneFlow 静态排序的 NCCL 基本维持在约 ±1.2% 内，同时比 KungFu 和 Horovod 高 20.4%-22.3%；ViT 大多数配置落在与 NCCL 的 ±3% 之内，最好一组快 8.6%；GPT-2 3D-hybrid parallelism 下与手工编排的 NCCL 相差也控制在 ±4%。

## 创新性与影响

DFCCL 的新意不在于又做了一个 collective scheduler。过去的工作不是默认应用已经避开了环形依赖，就是只研究单个 GPU kernel 的抢占延迟。DFCCL 把保留状态的 collective preemption、自适应的去中心化调度，以及常驻 daemon kernel 组合起来，让死锁处理真正下沉到通信库内部。

如果这条路线能推广开，框架作者就不必为每种 DP、TP、PP 组合都手工维护 collective 的全局顺序。它减少的不是一条带宽路径，而是整套分布式训练控制逻辑的脆弱性。

## 局限性

DFCCL 不是没有成本。对小 buffer collective 来说，队列管理和 I/O 处理会带来额外的几微秒时延，这也是 4 KB all-gather 不如 NCCL 的直接原因。系统还依赖 profiling 得到的初始 spin threshold 和主动退出周期；论文自己的案例分析已经表明，朴素的固定阈值会让 task queue 堆积、context switch 暴涨。

另外，论文的实现与评估范围还偏窄。原型面向 NVIDIA GPU、常见 collective 集合，以及基于 Simple protocol 与 Ring algorithm 生成的 primitive sequence；最大训练规模也只到 32 张 GPU、4 台机器。论文对正确性的论证主要依赖上下文保存与 connector 所有权分析，没有给出形式化的公平性或无饥饿证明。

## 相关工作

- _Bao et al. (INFOCOM '20)_ - PACE 会根据 DNN 依赖图去抢占式调度切分后的 all-reduce，而 DFCCL 进一步把抢占下沉到通信库层，目标是消解任意环形 collective 依赖。
- _Han et al. (OSDI '22)_ - REEF 处理的是 DNN inference kernel 的微秒级 GPU 抢占，并不负责保存和恢复多 GPU collective 的执行状态。
- _Yuan et al. (arXiv '21)_ - OneFlow 依靠编译器生成 task graph，再静态排序 collective；DFCCL 则想摆脱对全局一致调用顺序的依赖。
- _Barham et al. (arXiv '22)_ - Pathways 展示了更不规则的多 group 训练形态，而这恰好是手工 collective 编排最容易失效、DFCCL 最有意义的场景。

## 我的笔记

<!-- 留空；由人工补充 -->
