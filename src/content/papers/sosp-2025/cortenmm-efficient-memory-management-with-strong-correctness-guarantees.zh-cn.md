---
title: "CortenMM: Efficient Memory Management with Strong Correctness Guarantees"
oneline: "CortenMM 去掉 VMA 层，用范围事务直接编程 page table，并验证并发锁定核心，让内存管理在保留 Linux 式语义时仍能扩展。"
authors:
  - "Junyang Zhang"
  - "Xiangcan Xu"
  - "Yonghao Zou"
  - "Zhe Tang"
  - "Xinyi Wan"
  - "Kang Hu"
  - "Siyuan Wang"
  - "Wenbo Xu"
  - "Di Wang"
  - "Hao Chen"
  - "Lin Huang"
  - "Shoumeng Yan"
  - "Yuval Tamir"
  - "Yingwei Luo"
  - "Xiaolin Wang"
  - "Huashan Yu"
  - "Zhenlin Wang"
  - "Hongliang Tian"
  - "Diyu Zhou"
affiliations:
  - "Peking University"
  - "Zhongguancun Laboratory"
  - "Ant Group"
  - "CertiK"
  - "UCLA"
  - "Michigan Tech"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764836"
code_url: "https://github.com/TELOS-syslab/CortenMM-Artifact"
tags:
  - memory
  - kernel
  - verification
  - pl-systems
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CortenMM 的判断很直接：现代内核不再需要独立于 page table 的 VMA 式软件抽象层。它把内存管理收缩成以 page table 为中心的一层抽象，再配合范围事务接口和 Verus 验证过的并发 MMU 核心，同时拿到更好的多核扩展性和更强的正确性保证。

## 问题背景

论文首先指出，今天的内存管理同时面临两个老问题：太慢，而且太容易出并发 bug。Linux 这类系统在一个进程地址空间上同时维护两套表示：一套是软件层的数据结构，例如 VMA tree；另一套是硬件 MMU 真实使用的 page table 和 TLB 状态。这个分层历史上确实有价值，既便于移植，也便于表达 demand paging 之类的高级语义，但代价是每个实际操作都要在并发环境里维护两套形状完全不同的数据结构一致。结果就是性能和正确性一起受损：哪怕 Linux 已有 per-VMA locking 等改造，多核场景仍会在额外元数据上争用；与此同时，复杂锁协议也持续制造安全漏洞。已有研究系统虽然能缓解部分瓶颈，但往往要么缺少常见语义，要么付出较高内存开销，要么仍然保留难以推理的并发控制。CortenMM 要解决的是更难的组合题：保留 Linux 风格语义、在多核上高性能扩展、并给出强于测试的并发正确性保证。

## 核心洞察

论文最重要的观点是：对主流 ISA 来说，软件层地址空间抽象已经主要是在继承历史复杂度。x86、ARM 和 RISC-V 都采用高度相似的多级 radix-tree page table，而现有内核其实早已主要靠语言级抽象去抹平这些 ISA 的细微差异，而不是靠再建一棵独立的 VMA 树。如果 swapping、copy-on-write 这类高级语义需要额外状态，这些状态也可以贴着 page table 存，而不必维护另一套独立同步的数据结构。只剩下一层抽象之后，并发控制也能被重写成范围事务：线程先锁住一个虚拟地址区间，拿到 cursor，再在该区间里原子执行 `query`、`map`、`mark`、`unmap`。重叠范围串行，互不重叠的范围并行。

## 设计

CortenMM 为每个 page-table page 维护一个按物理页号索引的 page descriptor。descriptor 里包含该页的锁，以及一个按需分配的 per-PTE metadata array。这个数组保存 MMU 自身无法表达但内存语义又必须保留的信息，例如某个虚拟页当前是 invalid、预留给匿名页后续 fault、已经 mapped、是 file-backed，还是已经 swapped out，以及相应的权限位和 swap 位置。也正因为这些状态直接贴在 page table 边上，系统可以支持 Linux 风格语义而无需重建 VMA 层。

对 MMU 的所有操作都通过事务接口完成。`AddrSpace::lock(range)` 会找到覆盖该范围的 covering page-table page，并返回一个 `RCursor`；调用者随后可以组合执行 `query`、`map`、`mark`、`unmap`，这些操作对该范围原子生效。论文给出两个锁协议。`CortenMMrw` 从根向下遍历，沿路持 reader lock，到 covering page-table page 后升级为 writer lock。`CortenMMadv` 更激进：先在 RCU read-side critical section 里无锁遍历，再锁住 covering page，并用 DFS 把其后代 page-table page 一并锁住。若并发 `unmap` 删除了 page-table page，系统先把它从父节点摘下、标成 stale，再等 RCU grace period 之后释放，避免 use-after-free。基于这一接口，`mmap`、`munmap`、`mprotect`、page fault、on-demand paging、copy-on-write、reverse mapping、file-backed mapping、swapping 和 huge page 都能直接实现。整套实现共 8,028 行 Rust，其中只有 122 行 `unsafe`；被验证的事务核心为 829 行。

## 实验评估

实验平台是双路 AMD EPYC 9965，共 384 核、1 TB DRAM，对比对象是 Linux 6.13.8、RadixVM 和 NrOS。单线程结果已经说明问题：`CortenMMadv` 在五个微基准里赢了四个，`mmap-PF` 提升 46.8%，page fault 提升 53.6%，`unmap-virt` 提升 76.9%，`unmap` 提升 7.8%；只有纯 `mmap` 慢了 3.1%，因为它会更早分配 page-table page。真正的亮点在多核扩展性。低争用微基准下，`CortenMMadv` 在 384 核时比 Linux 快 33 倍到 2270 倍，其中 page fault 为 33 倍，`unmap-virt` 达到 2270 倍；高争用场景下虽然同一 last-level page-table page 会成为瓶颈，它仍然能比 Linux 快 3 倍到 1489 倍。

真实应用里，只要内存管理真是瓶颈，收益也很明显：JVM thread creation 在 384 核时延迟下降 32%，Metis 提升 26 倍，dedup 在 64 线程上比 Linux 高 2.69 倍，psearchy 在 64 线程上大约快 2 倍。相反，对大多数不怎么压内存管理的 PARSEC workload，CortenMM 基本没有额外收益，但也没有明显回退。验证和工程成本也被量化了：事务接口 proof-to-code ratio 为 5.2:1，作者大约投入 8 person-months，Verus 在不到 20 秒内即可完成验证。内存开销与 Linux 接近；即便按最坏情况让每个 page-table page 都完整分配 metadata array，总体开销也仍低于 2%。整体上，实验支持论文中心论点，不过最大倍数很多来自刻意放大 MM 快路径差异的微基准。

## 创新性与影响

和之前追求可扩展内存管理的工作相比，CortenMM 的创新点不在于更快的树、更精巧的 range lock，或者更激进的 page-table replication。它真正的新动作是直接删掉软件层抽象，然后围绕一个可验证的事务式 MMU 接口重建整个内存管理系统。这不是简单的实现细节优化，而是对“地址空间该如何建模”的重新定义。它的影响对象首先会是内核和 hypervisor 设计者，尤其是那些既想保留 Linux 兼容语义，又不想继承 Linux 地址空间复杂度的人。更广义地看，这篇论文还提出了一条方法论：如果某个子系统的证明和扩展性负担主要来自两套内部表示之间的同步，那么删掉其中一套表示，可能会同时改善性能和可验证性。

## 局限性

CortenMM 明确建立在主流多级 radix-tree MMU 之上。论文直接承认，这个思路并不能平滑迁移到段式、哈希式等完全不同的 MMU 组织；系统目前也没有 NUMA placement policy。它的验证边界也比标题给人的第一印象更窄。真正被形式化验证的是并发 MMU 操作核心：两个锁协议、`RCursor` 的基本操作，以及 page table 的 well-formedness。证明假设 sequential memory model，并信任 Verus、SMT solver、硬件、其余 OS 代码，以及锁、RCU、allocator 等支撑组件的实现。被证明的代码是单独移植到 Verus 工件中的，而不是直接和最终内核二进制链接。性能方面也并非处处占优：像 `fork` 这类必须枚举整个地址空间的操作会比 Linux 慢 17.7%，而 `CortenMMadv` 在高争用下也会在约 64 线程后受限于同一个 last-level page-table page。

## 相关工作

- _Clements et al. (ASPLOS '12)_ — Scalable Address Spaces Using RCU Balanced Trees 继续保留软件层地址空间树，并通过更好的并发控制去扩展它；CortenMM 的结论则是，这一层本身就应该被删掉。
- _Clements et al. (EuroSys '13)_ — RadixVM 同样追求 page-table-centric 的可扩展地址空间，但它依赖 per-core private page table，缺少若干 Linux 式语义，还要承担更高的内存开销。
- _Bhardwaj et al. (OSDI '21)_ — NrOS 用 node replication 作为通用 OS 可扩展性机制来处理内存管理；CortenMM 则把重点放在 memory-specific 的事务接口上，同时保留 copy-on-write、swapping、reverse mapping 与 file-backed mapping。
- _Klein et al. (SOSP '09)_ — seL4 在更广的范围上验证整个内核，而 CortenMM 选择验证范围更窄但并发度更高的 memory-management core，并把简化预算优先花在性能上。

## 我的笔记

<!-- 留空；由人工补充 -->
