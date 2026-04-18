---
title: "EMT: An OS Framework for New Memory Translation Architectures"
oneline: "EMT 把 Linux 的地址翻译抽象成 MMU driver 接口，让 ECPT、FPT 等新方案以近乎零开销接入，并暴露纯硬件评估看不到的 OS 瓶颈。"
authors:
  - "Siyuan Chai"
  - "Jiyuan Zhang"
  - "Jongyul Kim"
  - "Alan Wang"
  - "Fan Chung"
  - "Jovan Stojkovic"
  - "Weiwei Jia"
  - "Dimitrios Skarlatos"
  - "Josep Torrellas"
  - "Tianyin Xu"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "University of Rhode Island"
  - "Carnegie Mellon University"
conference: osdi-2025
code_url: "https://github.com/xlab-uiuc/emt"
tags:
  - kernel
  - memory
  - hardware
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

EMT 用一组围绕 translation object、translation database 和 translation service 的 MMU driver 接口，替换了 Linux 里写死的 page-table 假设。这样一来，同一个内核就能支持 radix、ECPT 和 FPT，而且接口本身几乎没有性能损失；更重要的是，它让研究者第一次能从真实 OS 视角看到新型地址翻译硬件带来的正确性和性能问题。

## 问题背景

内存地址翻译已经重新成为系统瓶颈：内存容量持续增大，TLB 可覆盖的范围却没有同步增长，而机器学习、图分析和生物信息学等新工作负载又往往局部性很差。对 x86-64 来说，一次 TLB miss 本身就要触发多级 radix tree walk；在虚拟化环境里做 nested translation 时，四级页表最坏可达 24 次串行内存访问。于是，硬件研究开始大量提出更快的 MMU 结构，例如 hashed、flattened 和 hybrid page table。

问题在于，commodity OS 并没有跟上这些硬件创新。论文指出，Linux 的架构无关内存管理代码里到处都隐含着 radix tree 假设：相邻条目可以靠指针递增获得，PMD 不是 huge page 就是下一级目录，某个中间节点为空就意味着整段地址范围都没有映射。结果是，研究者通常只能在模拟器里评估新翻译架构，并默认 OS 开销在不同硬件上保持不变。EMT 的出发点恰恰是这个默认前提不成立，因为翻译架构会直接改变 page fault、范围扫描、锁、swap 和 huge page 管理的成本。

## 核心洞察

论文的核心判断是，OS 应该抽象“地址翻译提供了什么功能”，而不是抽象“硬件把翻译信息存成什么形状”。Linux 真正需要的，不是知道映射存在于 radix tree、hash table 还是 flattened structure 中，而是有办法查询和更新一条虚拟到物理映射及其元数据，把一个地址空间作为这些映射的集合来管理，并在上下文切换时切换 MMU 状态。

因此，EMT 把接口拆成一个很小的架构中立核心，再加上一组面向优化的可定制钩子。核心接口足够强，可以让新的 MMU 方案接入 Linux 而无需重写通用内存管理代码；可定制部分又保留了 Linux 赖以保持高性能的低层快路径。这正是论文最重要的贡献：既获得可扩展性，又不把 Linux 逼进一个抽象干净但性能贫弱的高层接口里。

## 设计

EMT 围绕三个原语组织。translation object 表示一条映射及其元数据，例如物理地址、页大小、权限、present 位、dirty 状态、swap 编码，或者 protection key 这类架构特定属性。translation database 表示一个地址空间中保存这些对象的结构；它可以是 radix tree、若干张 ECPT hash table，或者别的硬件定义结构。translation service 则负责创建、销毁和切换 translation database，承担上下文切换时的 MMU 状态管理。

整个 API 分成 15 个 basic functions 和 35 个 customizable functions。每个 MMU driver 都必须实现基本操作，例如查找 translation object、更新对象、切换地址空间。可定制函数则都有一个架构中立的默认实现，但当某种翻译架构存在更好的快路径时，可以覆盖掉默认版本。论文里最典型的例子是范围迭代：默认实现反复调用 `tdb_find_tobj`，而 x86 radix driver 可以利用空间局部性直接递增指针。范围锁、huge page eligibility、swap 编码和地址范围是否为空等操作也都能按同样方式定制。

Linux 移植规模不小，但边界清晰。基于 Linux 5.15 的 EMT-Linux 重写了 `mm/` 目录中的 196 个内核函数，把翻译相关逻辑迁移进 MMU driver，同时保留 split page-table lock、huge page、swapping、DAX 和 MPK 等现有特性与优化。x86-64 radix driver 充当基线实现。FPT driver 复用了大量代码，只用了 664 行就接入成功，而且完全不需要改架构无关模块。ECPT 则更复杂：作者不仅写了 7.4 KLOC 的 MMU driver，还基于 QEMU 搭了一套模拟 MMU 的开发和评测工具链，因为真实硬件尚不存在。

## 实验评估

第一组结果说明 EMT 本身很便宜。带有 Radix、ECPT 和 FPT driver 的 EMT-Linux 通过了全部 1,208 个适用的 Linux Test Project 测试，覆盖 376 个系统调用。与运行在同一台双路 Xeon 服务器上的 vanilla Linux 相比，EMT-Linux 在 41 个 LEBench 微基准上的平均归一化性能达到 99.9%，最坏情况也只是 `epoll big` 慢 4.2%；在论文使用的宏基准上，额外开销低于 0.1%，而 Redis、Memcached、PostgreSQL 的吞吐和平均延迟与 vanilla Linux 的差异都只有大约 0.1% 量级。

更重要的结果来自 EMT 对 ECPT 的 OS 视角分析。硬件仿真显示，ECPT 相比 x86-64 radix 平均把 page-table walk latency 降低 23.1%，把 IPC 提高 7.0%。但当真实 Linux 内核参与进来后，这些硬件收益会被额外内核工作部分抵消：在 4 KB 页配置下，ECPT 使 page-fault-handling 指令数平均增加 1.74x；启用 THP 后更达到 2.59x。根源在于，树结构里很便宜的 sparse range check，在独立 hash entry 结构里会变得昂贵。最终，总周期数在全部工作负载上的平均改善只有 2.3%，不过 GUPS 和 Memcached 仍分别提升了 11.5% 和 12.9%。

EMT 也让这些问题可以被真正优化。作者为 ECPT 写了一个利用 entry cluster 局部性的定制 iterator，在启用 THP 的 GraphBIG BFS 上把总内核工作量降低 49.0%，把 page-fault-handling 工作量降低 52.5%。论文借此说明，单看硬件指标是不够的：page-table walk 更快、IPC 更高，并不自动意味着应用整体更快，因为翻译架构还会改变内核控制路径的形状。

## 创新性与影响

相对于 _Rashid et al. (ASPLOS '87)_，EMT 不是传统意义上那种只提供窄映射接口的 `pmap` 分层；它刻意保留了 Linux 进行低层优化所需的操作空间。相对于 _Skarlatos et al. (ASPLOS '20)_ 和 _Park et al. (ASPLOS '22)_，EMT 也不是又一种新的地址翻译架构，而是让 ECPT、FPT 这类硬件提案能够真正跑在 commodity Linux 上的缺失 OS 基座。相对于 _Tabatabai et al. (USENIX ATC '24)_，后者强调的是 memory-management policy 的可扩展性，而 EMT 直接面向翻译架构本身。

这让 EMT 同时对硬件研究者和系统研究者都有价值。它提供了一个开放平台，用真实 Linux 去实现和比较新 MMU；而 ECPT 的案例则说明这样做的必要性，因为一旦把 OS 放进闭环，马上就会出现纯架构模拟看不到的问题，例如 kernel page table 的自引用悖论、kernel translation state 的原子切换、稀疏地址范围管理，以及锁粒度与可扩展性的权衡。

## 局限性

EMT 的范围仍然小于“全部内存管理”。它关注的是 CPU 的虚拟到物理地址翻译，而不是 IOMMU、物理页操作，或直接让软件使用物理地址的设计。虚拟化支持还在路线图中，论文对通用性的论证也主要建立在 x86 radix、FPT 和 ECPT 这三类方案之上。

ECPT 的实现经历还说明，EMT 并不会自动消除所有困难。kernel page table 管理最终需要额外硬件支持，才能在不同 kernel ECPT 状态之间做原子切换；当前实现里的锁也仍是 coarse-grained，作者还在探索更好的多核锁设计。实验做得很扎实，但其中一部分仍依赖模拟执行和 trace-driven 的硬件仿真，而不是真实出片的 MMU。

## 相关工作

- _Rashid et al. (ASPLOS '87)_ - Mach 的 `pmap` 把机器无关内存管理与硬件映射分离开来，而 EMT 认为 Linux 还需要更低层的钩子来保留关键优化。
- _Skarlatos et al. (ASPLOS '20)_ - ECPT 提出了 elastic cuckoo page table；EMT 则提供了把这一思路真正实现并评估为 Linux OS 栈的基础设施。
- _Park et al. (ASPLOS '22)_ - FPT 通过 flattening 减少 radix tree 的 walk 深度，而 EMT 展示了这类设计可以藏在 MMU driver 背后，而不是散落成一次跨内核重写。
- _Tabatabai et al. (USENIX ATC '24)_ - FBMM 通过 filesystem 风格接口提升 memory-management policy 的可扩展性，而 EMT 专门解决硬件地址翻译架构的可扩展性。

## 我的笔记

<!-- 留空；由人工补充 -->
