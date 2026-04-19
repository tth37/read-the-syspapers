---
title: "eNetSTL: Towards an In-kernel Library for High-Performance eBPF-based Network Functions"
oneline: "eNetSTL 把 35 类 eBPF 网络功能里反复出现的瓶颈抽成一个小型内核库，既补上纯 eBPF 做不到的功能，又把吞吐最高提升到 1.8x。"
authors:
  - "Bin Yang"
  - "Dian Shen"
  - "Junxue Zhang"
  - "Hanlin Yang"
  - "Lunqi Zhao"
  - "Beilun Wang"
  - "Guyue Liu"
  - "Kai Chen"
affiliations:
  - "Southeast University"
  - "Hong Kong University of Science and Technology"
  - "Peking Univeristy"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696094"
code_url: "https://github.com/chonepieceyb/eNetSTL"
tags:
  - networking
  - ebpf
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文的判断很直接：eBPF 网络功能之所以做不全、跑不快，很多时候不是单个算法的问题，而是它们反复撞上同一组缺失原语。eNetSTL 把这些共性瓶颈收敛成一个由 1 个 memory wrapper、3 类算法和 2 个数据结构组成的内核库，通过 kfunc/kptr 暴露给 eBPF；结果是原本做不到的功能可以做了，能做的那批又比纯 eBPF 快 14.6%-75.4%，而且平均只比手写 kernel 版本慢 3.42%。

## 问题背景

作者不是从一个单点用例出发，而是先把 35 个已经发表的 network function 核心操作重新用 eBPF 实现了一遍，覆盖 key-value query、membership test、packet classification、load balancing、counting、sketching、queuing 七大类。结论并不好看：有 3 个功能根本无法落到 eBPF 上，另外 28 个虽然能写出来，但相对内核实现会慢 14.8%-49.2%，真正没有性能损失的只有 4 个。根因也很具体：eBPF 很难安全持久化数量不定的动态对象，所以 skip list 这类 non-contiguous memory 设计直接被卡死；同时 SIMD、bit manipulation instructions、低开销随机数和适合队列场景的链表接口都不够顺手，于是 sketch、bitmap queue、multi-bucket compare、probabilistic update 这类热路径都会掉速。最直观的补救办法要么是改 eBPF ISA 和 verifier，要么是给每个 NF 单独写 kernel module；前者侵入太大，后者维护成本太高。

## 核心洞察

这篇论文最值得记住的一点是：不要按单个 NF 去补洞，而要按共享行为去补洞。作者从 35 个实现里抽出了 6 类反复出现、且决定性能上限的行为：位图上的 bit 操作、多哈希、基础数据结构、随机更新、non-contiguous memory，以及 contiguous bucket 上的比较或归约。只要把抽象层次抬到这里，问题就从「要不要为某个算法开后门」变成「能不能给 eBPF 提供一组稳定的小原语」。eNetSTL 的回答是可以，而且接口不该做得过低层。

## 设计

eNetSTL 的第一块是 memory wrapper。作者用一个 proxy 数据结构统一持有动态分配出来的对象，再把这个 proxy 持久化到 BPF map 里，于是 eBPF 就能间接保存数量可变的对象集合。对象关系通过 `node_connect` 和 `get_next` 维护，skip list 这类需要 pointer routing 的布局因此才变得可行。难点在安全性：若每次 `get_next` 都去查关系是否合法，遍历成本太高；eNetSTL 的做法是 lazy safety checking，把关系记录在连接时，等节点释放时再统一把相关边改成 `NULL`，从而避免 use-after-free。

第二块是接口层次。论文强调，高性能不只是把 kernel instruction 包起来，更关键的是别把接口做成会引入额外 memory copy 的低层包装。像 `ffs`、`popcnt` 这种 bit 操作可以直接暴露；但 SIMD 不行，所以 eNetSTL 给的是 `find_simd`、`reduce_simd` 这类高层算法，以及把哈希和后续动作合并起来的 `hash_simd_cnt`、`hash_simd_bit`、`hash_simd_comp`。另外还有两个按 NF 使用模式设计的数据结构：`list-buckets` 解决 map lookup 和锁竞争，`random_pool` 负责把随机数预先备好。安全方面则依靠 Rust、`rust-no-panic`、引用计数，以及带 `KF_ALLOC`、`KF_RELEASE` 注解的 kfunc metadata 来约束 eBPF 端的调用方式。

## 实验评估

实验平台是两台背靠背服务器，网卡为 Intel XL710 40 Gbps，CPU 为双路 Xeon E5-2630 v4，内核版本 Linux 6.6，接收端把程序挂在 XDP native mode 上；流量由 `pktgen` over DPDK 22.11 回放，并通过 RSS 固定到单队列做单核测量。论文详细评测了 11 个代表性 NF，对比 pure eBPF、kernel 和 eNetSTL 三种实现。

功能性最关键的例子是 NFD-HCS 的 skip-list key-value query。原生 eBPF 做不出来，eNetSTL 做出来之后，lookup 吞吐只比 kernel 低 7.33%，update/delete 只低 8.54%。在那些本来能写、但写出来会慢的场景里，收益也比较稳定：Count-min sketch 平均快 47.9%，在 8 个 hash function 时最高快 70.9%；Carousel queueing 平均快 38.4%；Cuckoo Switch 平均快 27.4%，满载时快 33.08%；Eiffel 平均快 14.6%，在 level 4 时快 20.9%；Nitro Sketch 则快 75.4%。更重要的是，它离 kernel 版本并不远：总体平均差距 3.42%，最差 5.24%。另外，单个算法或数据结构的操作级性能提升可达 52.0%-513%，若改成论文否定掉的低层接口，反而会再慢 59.0%-73.1%；嵌进 PolyCube、Katran、RakeLimit 等真实项目后，平均还能多拿 21.6% 吞吐。

## 创新性与影响

这项工作的创新点，不在于「让 eBPF 能调用 kernel 代码」这件事本身，kfunc 和 kptr 已经提供了这条路。真正新的是它划出的库边界：不是给每个 NF 做专用 kernel module，也不是试图把 eBPF 直接扩展成一门更强的内核语言，而是把 NF 里跨论文、跨类别重复出现的热路径抽成一个小而稳定的标准库。这套思路对做 eBPF dataplane、NF framework、kernel-side packet processing acceleration 的人都很有参考价值。

## 局限性

论文对安全边界交代得比较诚实。Rust 在这里降低了风险，但没有把风险消灭掉，因为 eNetSTL 仍然需要 `unsafe` Rust 来做 raw pointer 交互和低层 SIMD 封装，所以人工审查依旧不可省；现有工具链也还不能证明任意 unbounded loop 一定会安全退出。另一方面，它只覆盖作者从 35 个 NF 里总结出的 6 类共享行为，若未来瓶颈不在这些模式里，就得继续扩库。实验也主要集中在 XDP 风格的单机测试床上，没有展开多核扩展性。

## 相关工作

- _Jia et al. (HotOS '23)_ - 这篇工作指出只靠 verifier 来维持 kernel extension 安全性并不现实；eNetSTL 的路线更收敛，它不替换 eBPF，而是在现有模型上用 Rust 和 metadata 把库接口管起来。
- _Kuo et al. (EuroSys '22)_ - KFuse 解决的是多个 verified eBPF program 之间 tail call 带来的额外成本；eNetSTL 处理的是单个 NF 内部缺失高性能原语的问题。
- _Miano et al. (ASPLOS '22)_ - Morpheus 会针对 eBPF dataplane 的 fast path 做运行时专门化，而 eNetSTL 的重点是把本来就难以高效表达的共享操作变成可复用的内核组件。
- _Bonola et al. (ATC '22)_ - 这类工作把 eBPF packet processing 往 FPGA NIC 上卸载；eNetSTL 则留在主机 CPU 上，通过重新定义软件抽象边界来提速。

## 我的笔记

<!-- 留空；由人工补充 -->
