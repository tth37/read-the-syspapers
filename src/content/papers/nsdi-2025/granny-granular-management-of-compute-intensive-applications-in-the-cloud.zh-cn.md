---
title: "GRANNY: Granular Management of Compute-Intensive Applications in the Cloud"
oneline: "GRANNY 把 OpenMP/MPI 应用运行成可快照的 WebAssembly Granule，并只在 barrier 处扩线程或迁进程，以回收闲置 vCPU 并减少碎片化。"
authors:
  - "Carlos Segarra"
  - "Simon Shillaker"
  - "Guo Li"
  - "Eleftheria Mappoura"
  - "Rodrigo Bruno"
  - "Lluís Vilanova"
  - "Peter Pietzuch"
affiliations:
  - "Imperial College London"
  - "INESC-ID, Instituto Superior Técnico, University of Lisbon"
conference: nsdi-2025
code_url: "https://github.com/faasm/faasm/"
tags:
  - datacenter
  - scheduling
  - isolation
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

GRANNY 是一个云端运行时，它把未经修改的 OpenMP 和 MPI 程序运行成细粒度的 WebAssembly 执行单元 `Granule`。因为每个 Granule 都可以被快照，而且系统只会在语义安全的 barrier 控制点上管理它，调度器就能以 vCPU 粒度给 OpenMP 作业加线程，或把 MPI rank 迁移到别的 VM。这样一来，多线程作业的利用率更高，分布式作业的碎片化更低。

## 问题背景

论文抓住的是云调度器与并行应用之间的一个结构性错位。OpenMP 和 MPI 作业通常在启动时声明并行度，而主流云调度器基本会把这次资源分配冻结到作业结束。对多线程作业来说，这意味着 VM 里后来释放出来的 CPU core 会继续闲着，即使队列里还有等待运行的任务。对多进程作业来说，情况更麻烦：如果按 VM 粒度分配，可以保住 locality，却会浪费 VM 内剩余的 vCPU；如果按 vCPU 粒度分配，利用率会上升，但同一个 MPI 作业可能被散落到很多 VM 上，跨 VM 通信随之变多。

作者强调，这不只是 bin packing 算法不够聪明。哪怕调度器本身做得很好，只要底层 OpenMP/MPI 运行时不能安全、低开销地在执行中重配资源，调度器仍然束手无策。动态加线程可能破坏 shared memory 一致性；使用现有 checkpoint/migration 工具迁移进程，又会被内核状态和网络状态拖累，既重又难以频繁执行。论文中的实验把后果展示得很直接：Azure Batch 和 Slurm 在 OpenMP 负载下会留下大块闲置 CPU，而对 MPI 作业做细粒度调度则会制造碎片化，拉长作业完成时间。

## 核心洞察

GRANNY 的核心命题是：云调度器需要一个比 process 或 VM 更小、但状态又足够自包含的执行单元，并且系统必须知道在什么语义点上可以安全地操作它。这个单元就是 Granule：它本质上是一条执行线程，但既可以带 thread 语义运行 OpenMP，也可以带 process 语义运行 MPI。

WebAssembly 让这件事变得可行，因为它给每个 Granule 提供了 memory-safe 的 sandbox 和紧凑的 linear memory 状态；同时，GRANNY 的运行时后端会拦截 OpenMP、MPI 和 POSIX 调用，把关键元数据保存在 guest 代码之外。洞察的另一半同样关键：GRANNY 只会在 barrier control point 上做扩缩容或迁移，此时 shared memory 更新和 in-flight message 都处于一致状态。只要这两个条件成立，同一个 Granule 抽象就能同时支持纵向扩展和横向迁移，而且应用不需要改源码，只需重新编译到 WebAssembly。

## 设计

每台 VM 上运行一个 GRANNY runtime，集群范围内有一个集中式 scheduler。在单台 VM 内，多个 Granule 作为同一 host process 中的并列执行体运行。系统暴露三个后端。MPI backend 实现 `MPI_*` 调用，使用每个 Granule 的 mailbox 存放消息，并在跨 VM 时借助 TCP 发送。OpenMP backend 实现 LLVM runtime 展开后的 `__kmpc_*` 和 `omp*` 接口。POSIX backend 则实现应用需要的那部分 WASI/文件系统调用，并维护 WebAssembly 文件描述符到宿主机文件描述符的映射，保证快照恢复后语义仍然正确。

表示层最关键的细节在于内存布局。带 process 语义的 Granule 各自拥有独立的 linear memory；带 thread 语义的 Granule 共享同一块 linear memory，但各自持有独立栈。当 OpenMP 区域 fork 时，GRANNY 会在父 Granule 的 heap 中给子 Granule 分配栈、加上 guard page，并把子 Granule 的入口设置到正确的 WebAssembly function-table 位置。对 MPI 而言，发送与接收都由 backend 捕获，经由 mailbox 投递；只有目标 Granule 不在本 VM 上时，消息才会真正走 TCP。

快照由两部分组成：Granule 的 linear memory，以及运行时侧的状态，例如 stack pointer、function table、message queue 和 file-descriptor table。GRANNY 把 control point 分成 regular 与 barrier 两类。regular control point 足以处理普通 I/O 和消息操作；真正的管理动作只发生在 barrier 上，例如 `MPI_Barrier` 或 OpenMP barrier，此时运行时可以假设没有未完成消息，也没有尚未同步的 shared-memory 更新。于是，纵向扩展就变成“在同一份共享内存上再生成一个 thread-style Granule”；横向迁移则是在 MPI 作业进入 barrier 后，由 root rank 向 scheduler 查询迁移计划，源 VM 生成目标 Granule 的快照，目标 VM 重建 mailbox 与 descriptor 状态，再让所有 Granule 用更新后的路由一起恢复执行。在这些机制之上，论文实现了三类策略：改善 MPI locality 的 compaction policy、提升 OpenMP 利用率的 elastic policy，以及为 spot VM 驱逐做准备的预迁移策略。

## 实验评估

原型规模足以说明这不是一个纸上系统：它由 24,000 行 C++20 构成，建立在 Faasm 和 WAMR 之上，部署在最多 32 台 Azure `Standard_D8_v5` VM 上。论文使用重新编译到 WebAssembly 的、未经源码修改的 MPI 和 OpenMP 应用，并用若干微基准单独测量关键机制的代价。

对 MPI 负载来说，compaction policy 给出了最清晰的端到端收益。在一个包含 100 个作业的 LAMMPS trace 上，GRANNY 最多把 makespan 降低 20%，并且在只故意保留 5% 闲置 vCPU 的情况下，把碎片化压到比 Slurm 低约 25%。Azure Batch 也能维持较好的 locality，但代价是大约 30% 的 vCPU 一直闲置。这个 locality 改善会直接反映到 job completion time 上：中位数和尾部 JCT 都最多改善 20%。

对 OpenMP 负载而言，elastic policy 带来了论文最醒目的数字。GRANNY 最多把 makespan 降低 60%，把 aggregate idle CPU-seconds 压低 30%，并让中位数和尾部 JCT 最多改善 50%。原因并不神秘，而是非常有说服力：在队列里仍有待执行作业时，Azure Batch 和 Slurm 仍分别留下约 60% 与 40% 的 vCPU 空闲，而 GRANNY 会在 barrier 到来时追加 Granule，把空闲容量维持在更接近 20% 的水平。spot-VM 策略也不是附带的小功能：在 25% 的驱逐率下，原生基线会出现 50%-100% 的 slowdown，最差接近 2 倍；GRANNY 则把 slowdown 控制在 25% 以内，因此 spot instance 仍然保有成本优势。

微基准进一步说明这些机制没有把运行时本身做得太重。MPI backend 相对 OpenMPI 通常落在 10% 以内，大多数 OpenMP kernel 与 `libomp` 表现接近，一个 4 MB 的迁移大约需要 30 ms，其中真正创建快照只占约 3 ms，而从 1 线程扩到 6 线程时，elastic scale-up 最多能带来 60% speedup。整体而言，这组评估支持论文的中心论点，不过它仍是一个受控的 32-VM 实验，而不是生产环境证据。

## 创新性与影响

GRANNY 的新意不只是“做了一个更好的 scheduler”。更深一层的贡献是，它给云调度器提供了一个真正贴近 MPI/OpenMP 并行度本体的运行时抽象：一个映射到单个 vCPU、能在用户态被快照、并且只在 barrier 处安全操控的 thread/process 风格 Granule。与 CloudScale 这类弹性工作相比，GRANNY 的控制点深入到了并行运行时内部，而不只是停留在更粗的资源管理层。与 Nu 相比，它保留了现有 OpenMP 与 MPI 的编程模型，而不是要求开发者围绕新的消息传递抽象重写应用。

因此，这篇论文会同时对几类社区有吸引力：云 batch scheduler、HPC-on-cloud runtime、WebAssembly 系统，以及研究透明迁移和 spot-instance 韧性的工作。它既提出了新机制，也证明了这个机制确实能解锁一组有实际价值的调度策略。

## 局限性

这套设计要求把应用及其依赖重新编译到 WebAssembly，这本身就是一个明确的部署门槛，即便它不要求改源码。当前系统只支持 CPU，因此 GPU 密集型负载不在覆盖范围内。GRANNY 的协作式控制模型还依赖应用足够频繁地到达 barrier control point；如果 barrier 很稀疏，扩线程或迁移的机会就会明显减少。

论文也坦承了 WebAssembly 的代价。多数 kernel 与原生接近，但浮点密集的 `dgemm` 仍会慢约 80%，而大于 4 GB 的 sandbox 也还有更高的额外开销。最后，评估是在 32 台 VM、每条 trace 只包含一种应用家族的条件下完成的，因此它对更异构、更加生产化负载的收益仍然属于有根据的推断，而非已被直接证明的事实。

## 相关工作

- _Ruan et al. (NSDI '23)_ - Nu 也通过迁移追求 resource fungibility，但它要求应用围绕 Proclet 与 message passing 重写；GRANNY 则保留现有 OpenMP/MPI 语义来运行已有代码。
- _Shen et al. (SoCC '11)_ - CloudScale 自动化了多租户云中的弹性扩缩容，而 GRANNY 关注的是运行中并行作业内部更细的 thread/process 粒度控制。
- _Planeta et al. (USENIX ATC '21)_ - MigrOS 为容器化 RDMA 应用提供 live migration，但依赖更重的协议支持；GRANNY 则利用自包含的 WebAssembly 快照和 barrier 感知的运行时语义。
- _Wang et al. (SC '08)_ - 面向 MPI 系统的 process-level live migration 迁的是整个进程，checkpoint 代价更高；GRANNY 则在语义安全的 barrier 上迁移按 vCPU 切分的 Granule。

## 我的笔记

<!-- empty; left for the human reader -->
