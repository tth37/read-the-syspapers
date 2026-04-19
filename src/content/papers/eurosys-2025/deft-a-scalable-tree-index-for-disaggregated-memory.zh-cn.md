---
title: "Deft: A Scalable Tree Index for Disaggregated Memory"
oneline: "Deft 不缩小 B+ 树节点，而是把远程访问切成 bucket pair 和 sub-node，再用 one-sided SX lock 与 OPDV 把分离内存上的查找和更新扩展起来。"
authors:
  - "Jing Wang"
  - "Qing Wang"
  - "Yuhao Zhang"
  - "Jiwu Shu"
affiliations:
  - "Tsinghua University"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696062"
code_url: "https://github.com/thustorage/deft"
tags:
  - databases
  - memory
  - disaggregation
  - rdma
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Deft 是为 disaggregated memory 设计的 RDMA B+ 树：逻辑上仍保留 `1 KB` 节点以压低树高，但远程访问只取 leaf 里的 hash bucket pair 和 internal node 里的 sub-node。再配合 one-sided SX lock 与 OPDV，它在 skewed YCSB-A 上做到 `42.7 Mops/s`，在 skewed YCSB-C 上做到 `91.0 Mops/s`，整体领先 Sherman、SMART 和 dLSM。

## 问题背景

一旦 ordered index 放到 disaggregated memory 上，代价模型就变了。compute node 只能靠 one-sided RDMA 去碰 memory node 上的数据，传统 B+ 树里那个默认成立的前提，也就是把整个节点读回来再在本地处理，就会立刻变成网络瓶颈。节点做大，树高和 round trip 会下降，但每次 lookup 都要把整页搬过网卡，带宽很快被吃满。节点做小，或者直接换成更稀疏的 radix 类结构，单次读取字节数是少了，可树会更高，upper tree 更难被有限的 index cache 吃住，远程跳数也会变多。论文用 Sherman 做的实验很说明问题：节点一旦超过 `1 KB`，单个 CN 就能把 `100 Gbps` RNIC 顶到饱和；反过来继续缩节点，又会因为树高上升把延迟找回来。

写入并发同样麻烦。用 `RDMA_CAS` 抢远端 exclusive lock，在 skewed workload 下很难扩展。作者测到的峰值锁吞吐不到 `4 Mops/s`，而且只出现在 `40` 线程附近，再往上就是大量重试把 NIC 队列塞满。read-write 冲突的处理也不轻松。checksum 要额外算校验，传统 versioning 要发三次独立的 `RDMA_READ`，FaRM 那类按 cache line 带版本号的方法又会把远端写放大到整对象。放在 DM 上，这些账都得按真金白银来算。

## 核心洞察

Deft 最关键的判断是：在 DM 上，真正该保持大的，是逻辑上的 fanout；真正该做小的，是远程访问和更新的单位。只要一次 point operation 不必再把整个 `1 KB` 节点拉回来，也不必让所有 writer 在一个 exclusive lock 前排队，B+ 树原本的浅层结构仍然值得保留。

换句话说，作者愿意多花一点本地 CPU，去做 hash、在小范围里扫 unsorted entry、顺着 pointer 算 sub-node 范围；因为和远程传输的字节数、以及跨网络同步的 round trip 相比，这点本地计算便宜得多。这个判断把 Deft 后面的三件事串到了一起：leaf 的细粒度访问、internal node 的分段读取，以及只把 exclusive mode 留给结构修改。

## 设计

Deft 的 leaf node 是 hash-based 的。一个 leaf 仍然负责一段有序 key range，但内部不再按 key 全局排序，而是把 entry 按 hash 映射到 bucket。两个 main bucket 共用一个 overflow bucket，point lookup 只需一次 `RDMA_READ` 取回对应的 bucket pair。按论文当前实现，这把远程读取粒度从整页 `1 KB` 压到了 `128 bytes`。update 只改 value，用 `8-byte RDMA_CAS` 保证原子性；insert 则尽量用 extended `RDMA_CAS` 一次写完整个 entry。leaf 只有在 main bucket 和它的 overflow bucket 都满时才触发 split。

internal node 则保持 `1 KB` 大小不变，但按 key range 切成多个 sub-node，通常是 `4` 个。sub-node 内部不排序，只要求最大 key 留在最右槽位，供搜索时快速定位。lookup 先根据 key 算出该读哪个 sub-node，再利用 child pointer 里顺带编码的 granularity 信息推断下一层该读哪一段，因此不需要额外的子指针。如果某个 sub-node 塞满，Deft 先尝试合并相邻 sub-node；只有整个 internal node 满了，才走普通 B+ 树 split。

并发控制围绕 shared-mode upsert 展开。writer 先拿 shared lock，然后直接用 `(extended) RDMA_CAS` 做 update 或 insert；只有 split 这类 structural modification operation 才升级到 exclusive mode。这个 `64-bit` 的 one-sided SX lock 基于 masked `RDMA_FAA` 实现，在无竞争时 shared 和 exclusive acquisition 通常都只要一个 round trip。read path 则用 OPDV：child node 里放 data-side version，parent pointer 里带 commit version，让 reader 顺着 search path 就能完成一致性验证，不需要第三次 read，也不需要整节点重写版本号。

## 实验评估

原型跑在 `10` 台服务器组成的集群上，每台是 `18` 核 Xeon `6240M`、`96 GB` DRAM 和 `100 Gbps` ConnectX-5 NIC。主实验使用 `2` 个 memory node、`10` 个 compute node、`400 million` 个 key、`8-byte` key 和 value，并给每个 CN 配 `1 GB` index cache。对比对象是 Sherman、修正为 checksum 同步的 Sherman-C、SMART 和 dLSM。

对 point workload，结果很有说服力。skewed YCSB-A 上，Deft 达到 `42.7 Mops/s`，相对 dLSM、Sherman、Sherman-C、SMART 最多高 `3.7x`、`6.1x`、`9.5x`、`1.3x`。skewed YCSB-C 上，它达到 `91.0 Mops/s`，相对 dLSM、Sherman、SMART 最多高 `34.2x`、`3.7x`、`2.2x`。ablation 也把功劳拆得比较清楚：在 cache 够用时，OPDV 单独带来 `46%`，可扩展并发控制带来 `2.5x`，hash-based leaf 带来 `2.1x`；当 cache 关掉后，segmented internal node 还能再给 `56%`。不过 scan 是明显短板，YCSB-E 上它和 Sherman 基本打平，因为 scan 仍要整 leaf 读取，而 leaf 内部又是 unsorted 的。

## 创新性与影响

Deft 最有价值的地方，不是某个孤立的小技巧，而是把 node size 和 remote access granularity 这两个在传统 B+ 树里默认绑定的概念拆开了。和 Sherman 相比，它保留大 fanout，却不再接受整页读写带来的带宽浪费；和 SMART 相比，它没有换成更高更稀疏的树，而是在 B+ 树节点内部做细粒度化。

这个思路对后续 DM 系统很有参考价值。只要系统本身是 pointer-chasing 的，作者关于细粒度访问、shared-first 写入协调、以及把版本验证搬到 search path 上的做法，都有机会被复用到别的远端内存数据结构里。

## 局限性

Deft 最擅长的是 point lookup 和 update，不是所有 ordered-index 场景。YCSB-E 上它只和 Sherman 相当，因为 scan 仍会整页取 leaf，再在 unsorted entry 里做线性搜索。实现上它也明显依赖 Mellanox 的 masked atomic 和 extended atomic；delete 为了避免重复 key 竞争，被放进 exclusive mode；真正的 crash recovery 也被留到了 future work。

另外，key 一旦超过 `64 bytes`，性能就会明显下滑，原因既有节点变大带来的 I/O 放大，也有 index cache 变得不够用。到了 Twitter 的大 value Storage workload，Deft 相对 Sherman 的优势也只剩大约 `20.2%`，因为那时主导成本已经不是 index traversal，而是 value 本身的远程传输。

## 相关工作

- _Wang et al. (SIGMOD '22)_ - Sherman 是最直接的 DM B+ 树基线；Deft 保留其浅树目标，但把节点访问和写入协调做得更细。
- _Luo et al. (OSDI '23)_ - SMART 通过 adaptive radix tree 获得细粒度远程访问，Deft 则试图在更浅的 B+ 树里拿到类似收益。
- _Wang et al. (ICDE '23)_ - dLSM 靠 batching 和 range sharding 把写入做快，Deft 则面向 ordered point operation，避免多 SSTable 读取路径。
- _Li et al. (FAST '23)_ - ROLEX 走的是 learned front-end 路线，Deft 继续坚持 tree structure，但瞄准的是同一组 DM 瓶颈，也就是带宽浪费和写入侧协调成本。

## 我的笔记

<!-- 留空；由人工补充 -->
