---
title: "Unlocking True Elasticity for the Cloud-Native Era with Dandelion"
oneline: "Dandelion 把云应用改写为纯计算函数与通信函数 DAG，让隔离沙箱能够按请求在数百微秒内冷启动，并显著降低 serverless 的内存预留成本。"
authors:
  - "Tom Kuchler"
  - "Pinghe Li"
  - "Yazhuo Zhang"
  - "Lazar Cvetković"
  - "Boris Goranov"
  - "Tobias Stocker"
  - "Leon Thomm"
  - "Simone Kalbermatter"
  - "Tim Notter"
  - "Andrea Lattuada"
  - "Ana Klimovic"
affiliations:
  - "ETH Zurich"
  - "MPI-SWS"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764803"
code_url: "https://github.com/eth-easl/dandelion"
tags:
  - serverless
  - datacenter
  - isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Dandelion 认为 serverless 之所以还不够弹性，不是 autoscaling 不够激进，而是每个函数仍被包装进带 guest OS 和网络状态的 POSIX 风格沙箱里，导致按请求冷启动太贵。它把应用改写成 pure compute function 与 trusted communication function 的 DAG，让计算沙箱能在数百微秒内冷启动，并真正按请求创建，而不是靠预热大量空闲实例来掩盖冷启动。

## 问题背景

论文指出了当代 FaaS 的一个根本矛盾：平台宣称自己“按需伸缩”，但为了避免冷启动落到短请求关键路径上，又不得不长期保留大量空闲 sandbox。作者用 Azure Functions trace 配合 Knative 复现时发现，为了让 97% 的请求走 warm start，系统平均要承诺大约 16 倍于“当前真正执行请求的 VM”所需的内存。由于 DRAM 是主要 server 成本，这种弹性本质上是在烧内存换体验。

作者认为这不是实现细节，而是接口层面的结构性问题。今天的平台仍把函数执行建模为“给每个用户函数一个 POSIX-like sandbox”。哪怕用了 Firecracker snapshot，关键路径上仍要恢复 guest 状态、加载镜像并重新建立 guest-host 网络连接，论文测得仅这些工作就超过 8ms。于是平台只能在高 tail latency 和大 warm pool 之间做取舍。

## 核心洞察

这篇论文最重要的命题是：很多云原生应用本来就天然分成两部分，一部分是对显式输入做本地计算，另一部分是通过 HTTP 等高层接口调用对象存储、数据库或 AI 服务。如果平台把这种切分显式化，用户代码其实不需要直接接触 syscall、socket 或 guest kernel。

Dandelion 因而把外部 I/O 全部移到 trusted communication function 中，而把不可信用户代码限制为 pure compute function，只接收声明好的输入并产生声明好的输出。这样一来，计算沙箱就不再需要 guest OS、虚拟网卡或每函数一个 async runtime，平台可以用更轻量的隔离方式按请求冷启动计算任务，同时把 I/O 密集型工作单独复用和调度。

## 设计

Dandelion 的程序表示是一个 composition DAG，节点可以是 compute function、communication function，或嵌套 composition。边除了描述数据依赖，还显式记录传递语义：`all`、`each`、`key`。这让 fan-out、聚合和并行边界在运行时一开始就是可见的，而不是藏在黑盒函数内部。

compute function 的运行接口被大幅收紧，但仍保持可用性。Dandelion 提供 `dlibc` / `dlibc++`，把输入和输出映射成用户态内存文件系统，因此函数仍能使用熟悉的文件与内存操作，只是不再真正进入内核。像 `socket`、`mmap`、线程创建这类 syscall 会直接失败。原型当前支持 C、C++，也支持通过编译后的 CPython 运行 Python 函数。

执行系统严格对应这个模型。dispatcher 跟踪 DAG 依赖、准备隔离的 memory context，并把任务晚绑定到 compute engine 或 communication engine。compute engine 对 pure compute 采用 run-to-completion；communication engine 属于受信层，用 cooperative green threads 处理高并发 I/O。control plane 每 30ms 观察队列增长速率，并用 PI controller 在 compute cores 和 communication cores 之间调配 CPU。原型还实现了四种 compute backend：无 guest kernel 的最小化 KVM VM、借助 `ptrace` 阻断 syscall 的 Linux 进程、CHERI，以及把 Wasm 编译到 safe Rust/native code 的 rWasm。阶段间数据传递目前仍以 copy 为主。

## 实验评估

微基准首先验证了“按请求冷启动是否真的够便宜”。在 Morello CHERI 平台上，CHERI backend 的平均 sandbox 创建延迟是 89us；在标准 Linux 5.15 配置上，KVM backend 是 218us，远低于 Firecracker snapshot 或 gVisor 的毫秒级启动。16 核服务器上的 128x128 整数矩阵乘实验里，Dandelion KVM 可达到约 4800 RPS，而在 97% 请求保持 hot 的设定下，Firecracker 大约在 3000 RPS 左右就开始饱和。

更关键的是端到端结果。面对突发混合负载，Dandelion 不依赖 warm pool，也能靠快速冷启动和动态 core rebalancing 保持稳定延迟。Azure Functions trace 上，Dandelion 平均只承诺 109MB 内存，而 Firecracker 加 Knative autoscaling 需要 2619MB，内存承诺下降 96%；与此同时，端到端 p99 延迟还降低了 46%。应用层实验也说明这不是只对 toy benchmark 有效：在约 700MB S3 输入的 Star Schema Benchmark 查询上，相对 AWS Athena，Dandelion 延迟低 40%、成本低 67%。不过 Athena 对比不是同硬件、同实现的严格 apples-to-apples benchmark，更适合看作潜力展示。

## 创新性与影响

Dandelion 的新意不只是“又一个更快的 sandbox”，而是同时重写了应用接口与执行系统。很多已有工作会加速 VM、改进 workflow orchestration，或者优化函数放置；Dandelion 则反过来问：serverless 之所以始终不够弹性，会不会是因为平台一直在模拟一个不适合云原生应用的接口？把外部通信显式化、把 syscall 从 compute function 中彻底拿走后，启动开销和攻击面同时缩小，这是论文最强的论点。

因此，这篇论文的意义也不只在于 cold start 更快。它为带不可信 UDF 的弹性查询处理、突发型数据流水线，以及在自定义逻辑与远程服务之间频繁切换的 agentic workflow，提供了一种统一的底层设计方向。

## 局限性

Dandelion 的适用范围很明确：只有当应用能较干净地拆成“纯计算”和“外部通信”两部分时，它才真正占优。论文明确把需要频繁大状态同步的场景排除在外，例如 OLTP、在线游戏、AI training，以及依赖细粒度多线程与共享内存的算法。已有应用迁移到 Dandelion 也常常需要围绕每个 I/O 边界手工拆函数，自动化分解目前仍是 future work。

系统层面也有现实约束。当前 communication function 主要围绕 HTTP，协议面不广；阶段间数据传递仍依赖 copy；不同 isolation backend 的部署门槛和安全假设并不相同，例如 CHERI 依赖专门硬件，rWasm 依赖更强的编译链可信性。论文的安全分析也主要基于 attack surface 与 TCB 推理，而 DoS 与 side channel 被显式排除在外。

## 相关工作

- _Agache et al. (NSDI '20)_ - Firecracker 仍以 POSIX-like MicroVM 作为 FaaS 的基本执行单元，而 Dandelion 把 guest OS 和网络栈从 compute sandbox 中拿掉，使“每个请求都冷启动”变得可行。
- _Yu et al. (NSDI '23)_ - Pheromone 也让 serverless orchestration 看见数据依赖，但 Dandelion 更进一步，把外部 I/O 抽成 trusted communication function，并围绕这种切分重做执行时。
- _Ruan et al. (NSDI '23)_ - Nu 追求 logical process 带来的微秒级资源弹性，而 Dandelion 更关注在多租户环境下安全执行不可信代码时的隔离边界。
- _Szekely et al. (SOSP '24)_ - SigmaOS 提供面向云的接口来统一 serverless 与 microservices，但仍允许用户代码调用不少 host syscall；Dandelion 则把 compute function 的 syscall 彻底封死，进一步压缩攻击面。

## 我的笔记

<!-- 留空；由人工补充 -->
