---
title: "A Programming Model for Disaggregated Memory over CXL"
oneline: "CXL0 把 CXL 上的共享内存抽象为传播距离可区分的读写与 flush，并据此把 FliT 改造成可承受局部崩溃的 durable 方案。"
authors:
  - "Gal Assa"
  - "Moritz Lumme"
  - "Lucas Bürgi"
  - "Michal Friedman"
  - "Ori Lahav"
affiliations:
  - "Technion, Israel"
  - "ETH Zürich, Switzerland"
  - "Tel Aviv University, Israel"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790121"
code_url: "https://www.github.com/cores-lab/cxl0"
tags:
  - disaggregation
  - persistent-memory
  - pl-systems
  - verification
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文的核心判断是：CXL 让共享内存的接口看起来没变，但它背后的可见性、持久性和故障语义已经变了。CXL0 通过显式区分写入与 flush 到底传播到哪里来刻画这种差异，并据此把 FliT 改造成适用于 partial crash 的版本。

## 问题背景

CXL 想提供的是一种很诱人的抽象：把远端内存、设备内存和未来的共享内存池统一成缓存一致的 load/store 接口。问题在于，一旦内存从“单机共享”变成“跨节点共享”，程序员默认的两个前提就同时失效了：系统不再受单一 memory model 支配，系统也不再只有一个 failure domain。远端节点可能先缓存一个值，再独立崩溃，而发起写入的机器仍继续运行。

这会直接破坏旧有直觉。一个值可能已经被远端读到，却仍然不 durable；一次对本地持久化足够强的 flush，对远端 owner 也许仍然太弱。论文真正要解决的是：在 CXL 上，程序员应该假设怎样的执行语义，才能正确推理并发、持久化与恢复。

## 核心洞察

论文最重要的洞察是：在 CXL 上，关键不在于底层 transaction 的名字，而在于一次更新已经传播到了哪里。它只到发起者 cache、到 owner cache，还是已经进入物理内存，对 partial crash 下的正确性有本质区别。

所以 CXL0 明确区分 `LStore`、`RStore`、`MStore`，也区分 `LFlush` 与 `RFlush`。在单机场景里，这些差异常常只是性能选项；在 disaggregation 里，它们直接决定崩溃后什么会丢、什么不会丢。也正因为这种边界被显式化了，作者才能把 FliT 的本地持久化假设替换成 `LStore + RFlush`。

## 设计

CXL0 把系统建模成若干台通过 CXL 相连的机器，每台机器有自己的 cache 和本地 memory，而共享地址空间中的每个地址都只属于一个 owner memory。状态写成 `(C, M)`：`C` 描述各节点 cache 中的值，`M` 描述 owner 的物理内存。模型还包含 silent propagation step，用来表示 cache 到 cache、以及 owner cache 到 owner memory 的非确定性传播；局部 crash step 则表示某一机器单独丢失 cache 和 volatile memory。

在这个框架里，`LStore` 只保证值到达发起者本地 cache；`RStore` 保证值到达 owner 的 cache 或 memory；`MStore` 只有在值到达物理内存后才完成。`LFlush` 只是把 cache line 往下一层推进一步，`RFlush` 则要求它传播到 owner memory。作者先证明这些 primitive 之间的强弱关系，再用 litmus tests 展示真正危险的情况：远端已经观察到某次写入，但稍后另一个节点的局部崩溃仍可能把它抹掉；如果写入足够强，例如使用 `MStore` 或配合 `RFlush`，这种恢复后不一致就会被排除。

论文还说明了 CXL0 与现实系统形态的关系。host-device pair、partitioned pool 和未来 fully coherent pool 都能落在这套抽象里，只是当前硬件对某些 primitive 的支持还不完整。作者还给出两个变体：一个在 crash 后加入 cache line poisoning，另一个假设 remote load 会隐式 write back。

设计的另一半是 FliT 改造。原始 FliT 假设单一故障域上的 x86 persistent memory，因此它的 flush 纪律对 CXL 来说不够强。作者的修改很干脆：store 统一变成 `LStore`，持久化靠 `RFlush`，而 `completeOp` 在模型里可以为空，因为 `RFlush` 已经是同步的。

## 实验评估

这篇论文的评估重点不是端到端吞吐，而是两个更基础的问题：现实硬件能实现哪些 CXL0 primitive，以及这些选择的代价有多大。实验平台是一台 x86 host，加上一块用 Intel CXL IP 配成 CXL Type 2 device 的 FPGA，并在链路上接入 Teledyne LeCroy protocol analyzer。这样就能把实际观察到的 CXL.cache / CXL.mem 事务映射回 CXL0 的抽象操作。

最重要的发现有两个。第一，映射是 many-to-one，而且并不完整：host 侧无法直接生成 `RStore` 或 `LFlush`，device 侧也缺少可实际使用的 `LFlush`。第二，这些 primitive 的代价差异很明显。对 host 而言，remote `Read` 和 `MStore` 大约比本地慢 `2.34x`；对 device 而言，这个倍数是 `1.94x`。当 device 向 host-attached memory 写入时，`MStore` 比 `RStore` 慢 `1.45x`，`RStore` 又比 `LStore` 慢 `2.08x`，而 `RFlush` 的代价与 `MStore` 接近。

这些结果足以支撑论文的中心论点：CXL0 里区分不同传播边界，并不是形式化上的洁癖，而是和真实硬件的行为与成本直接对应。

## 创新性与影响

和 _Izraelevitz et al. (DISC '16)_ 相比，本文把 durable linearizability 从单机 persistent memory 推到了 coherent disaggregated memory 与 partial crash。和 _Wei et al. (PPoPP '22)_ 相比，它说明了 FliT 为什么在 CXL 上不能原样照搬，并给出修复后的 `LStore`/`RFlush` 版本。和 _Li et al. (ASPLOS '23)_ 这类系统论文相比，它贡献的是更底层的语义契约，而不是某个具体 runtime。

因此，这篇论文对 CXL 运行时、PL / verification，以及并发数据结构三个方向都会有价值。它本质上是一篇 formalization 加通用转换的论文，而不是性能优化论文。

## 局限性

CXL0 依赖 cache coherence 和共享内存接口，而现实中的共享 memory pool 今天往往还不完全满足这一前提，除非软件额外模拟 coherence。作者也刻意把节点内部的 memory model 抽象掉，并把重点放在 safety 而非 liveness 上，所以真正落地时仍可能需要额外 fence 与 non-blocking 设计。

硬件验证同样比较克制：平台是 host-FPGA 的 CXL 1.1，而不是完整的 CXL 4.0 fabric；测量的是单个 primitive 的延迟，而不是端到端应用。论文还表明，一些有用的 CXL0 primitive 目前并没有作为程序员可精确控制的接口出现，也没有继续做大规模应用案例验证。

## 相关工作

- _Izraelevitz et al. (DISC '16)_ — 提出了 full-system crash 下 persistent memory 的 durable linearizability；这篇论文沿用该正确性视角，但把故障模型改成了 CXL 上的局部崩溃。
- _Wei et al. (PPoPP '22)_ — FliT 为 x86 persistent memory 提供了通用对象转换；CXL0 说明其本地 flush 假设在 disaggregation 下不再充分，并用 `LStore`/`RFlush` 完成替换。
- _Li et al. (ASPLOS '23)_ — Pond 是面向云平台的 CXL memory pooling 系统，而这篇论文提供的是能为这类系统做并发正确性推理的语义层基础。

## 我的笔记

<!-- 留空；由人工补充 -->
