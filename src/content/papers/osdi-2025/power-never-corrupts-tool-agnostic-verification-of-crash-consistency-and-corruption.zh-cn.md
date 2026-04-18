---
title: "PoWER Never Corrupts: Tool-Agnostic Verification of Crash Consistency and Corruption Detection"
oneline: "PoWER 把 crash consistency 编进写入前置条件，再结合 CRC 级腐化模型与 CDB，让 Verus 和 Dafny 都能验证 PM 存储系统。"
authors:
  - "Hayley LeBlanc"
  - "Jacob R. Lorch"
  - "Chris Hawblitzel"
  - "Cheng Huang"
  - "Yiheng Tao"
  - "Nickolai Zeldovich"
  - "Vijay Chidambaram"
affiliations:
  - "University of Texas at Austin"
  - "Microsoft Research"
  - "Microsoft"
  - "MIT CSAIL and Microsoft Research"
conference: osdi-2025
code_url: "https://github.com/microsoft/verified-storage"
tags:
  - verification
  - storage
  - persistent-memory
  - crash-consistency
category: verification-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

PoWER 把 crash consistency 改写成每一次 durable write 都必须满足的义务：在发出写入之前，先证明这次写入任何部分持久化后可能产生的 crash state 都是可恢复的。论文再把这个想法与基于 CRC 的介质腐化模型和一个极小的原子原语 CDB 结合起来，于是可以在普通验证器生态里验证两个 persistent memory 系统。CAPYBARA KV 在 1 线程下 54 秒完成验证，在 8 线程下 23 秒完成验证，并且在多项 PM KV workload 上与未验证系统具有竞争力。

## 问题背景

这篇论文瞄准的是存储系统里两个非常重要、但现有验证工具都不太擅长表达的性质：crash consistency 和 corruption detection。难点不在于开发者不会写 recovery 逻辑，而在于标准 Hoare-style specification 只能描述函数入口和出口的状态，崩溃却发生在函数执行中途。此前的 verified storage system 因此往往要引入额外机制，例如 Crash Hoare Logic、crash invariant，或者 TLA-style refinement proof。它们当然能工作，但代价是方法高度绑定特定 verifier，学习曲线陡，而且很难直接复用 Dafny、Verus 这类现成工具。

corruption detection 也有类似问题。此前最接近的 verified work，尤其是 VeriBetrKV，把 checksum 的正确性建立在很强的布局假设上：checksum 必须和数据一起存，且两者要原子更新。这个假设对很多真实系统都不成立，对 persistent memory 尤其不自然，因为 PM 的持久化原子粒度只有 8 字节。于是就出现了三重断层：证明方法太 verifier-specific，腐化模型太僵硬，做出来的 verified system 也很难说明自己仍然接近高性能 PM store 的设计空间。论文的目标就是同时填上这三处缺口。

## 核心洞察

论文最重要的洞察是：与其把 crash reasoning 做成 verifier 的新语言特性，不如把它塞进 storage write API 的 precondition。一次写入在调用点已经知道 pre-state、目标地址、待写字节以及设备的原子写粒度；这些信息足够刻画“如果只有部分 chunk 真正持久化，会出现哪些 crash state”。只要调用者在写入前证明这些新引入的 crash state 全部合法，那么普通 Hoare logic 就够用了，验证器不需要额外支持“在这里崩溃”这种中间态逻辑。

论文对 corruption 也采取了同样的简化路线。它不再公理化一种特定的数据与 checksum 布局，而是把设备建模成一个有界 corruption bitmask：读出的字节最多有 `c` 个 bit 被翻转，同时系统可以使用一个受信任的 CRC 定理，保证 Hamming distance 位于 `[1, c]` 的两个 buffer 不会有相同 CRC。这样一来，corruption detection 就建立在物理错误模型上，而不是建立在“checksum 是否必须紧贴数据、是否必须与数据一起原子更新”这种实现细节上。

## 设计

PoWER 对外仍然暴露 `read`、`write`、`flush` 这类熟悉的 storage API，但 `write` 多了一个关键 precondition。调用者必须提供一个 ghost permission，证明这次写入任意部分落盘后产生的状态都属于允许集合。论文用一个 prophecy-based storage model 来实例化这个接口，其中状态由 `read_state` 和 `durable_state` 两部分组成。`write` 会完整更新 `read_state`，却只把某个 chunk 粒度子集写进 `durable_state`；`flush` 的语义也不是“再执行一次写入”，而是确认此前预言出的 durable state 现在与 readable state 对齐。permission 既可以描述允许的 crash states，也可以描述允许的状态转移；既可以是可反复使用的 blanket permission，也可以是某次状态变更消耗掉的 single-use permission。

真正让 PoWER 变得可用的是它在此基础上抽出来的证明套路。论文把 durable update 分成四类。tentative write 写到 recovery 时不可达的位置，因此证明只需要说明被写地址在抽象语义上尚未被使用。committing write 用一次 crash-atomic 更新切换抽象状态，因此证明会收敛成两个 case：这次 commit write 落盘了，或者没有落盘。recovery write 用于 journal replay 等恢复过程，核心要求是 recovery 幂等，并且任何 torn write 都会在后续 recovery 中被覆盖修复。in-place write 则会把部分更新后的用户可见状态暴露出去，因此只适用于较弱的 crash semantics，目前论文也没有给它提供库级简化支持。对于并发，作者进一步提出 atomic PoWER：引入 durable ghost state 和 completion object，从而能支持 reader-writer lock 与分片式 region，但仍然不能处理同一 region 上相互重叠的并发写。

corruption 这一边的设计也很完整。`read` 返回的数据只保证满足 `maybe_corrupted` 谓词，调用方在真正使用这些字节前必须先做 CRC 检查。在 PM 上，传统“每个 block 带一个 CRC”的做法无法保证 crash-atomic，于是论文提出 corruption-detecting Boolean。CDB 是一个 8 字节值，只允许取两个预先选好的 CRC 常量 `CRC(0)` 与 `CRC(1)`。因为它本身正好落在 PM 的原子写粒度内，所以它可以充当两个独立 checksummed 副本之间的原子切换点。作者据此实现了两个系统：Verus 中的 CAPYBARA KV，它包含主表、item 表、list-element 表、redo journal、copy-on-write 更新，以及一个负责安全复制 PM 数据结构的受信任 `pmcopy` crate；还有 Dafny 中的 CAPYBARA NS，一个通过 CDB 原子更新 timestamp/hash 对的 notary service。

## 实验评估

实验分成两部分：证明成本与 CAPYBARA KV 的性能。先看证明成本，论文给出的数字是扎实的。CAPYBARA KV 有 14,255 行 specification/proof、5,531 行实现代码，以及 5,244 行 trusted code，proof-to-code ratio 为 2.6。CAPYBARA NS 更小：673 行 specification/proof、278 行实现、414 行 trusted code。验证时间也很短：CAPYBARA KV 在 1 线程下 54 秒，在 8 线程下 23 秒；CAPYBARA NS 在 1 线程下 12 秒。论文还特别报告，把 PM specification 与支撑库从 Verus 移植到 Dafny 只花了几个小时而不是几周，这是“tool-agnostic”主张最有力的证据。

性能部分把 CAPYBARA KV 与 pmem-Redis、pmem-RocksDB、Viper 对比。microbenchmark 显示，它在 item operation latency 上与 pmem-RocksDB 相当或更好，而 pmem-Redis 因为 client-server 开销在所有操作上都更慢。YCSB 中，CAPYBARA KV 在单线程和 16 线程实验里都明显优于 pmem-Redis 与 pmem-RocksDB；单线程下大致接近 Viper，而在 16 线程的分片配置下经常超过 Viper。论文也没有回避代价：由于需要重建 volatile index，CAPYBARA KV 的启动时间比 RocksDB 风格系统慢得多，空实例启动 7 秒、满实例启动 53 秒，而且它把所有 key 都放在 DRAM 中。整体而言，这组结果足以支持“验证并没有把系统逼成一个明显不具竞争力的 PM 设计”，但它更直接验证的是 CAPYBARA KV，而不是对 PoWER 本身做了独立的 head-to-head 证明。

## 创新性与影响

相对于 _Chen et al. (SOSP '15)_ 以及 Perennial 一系工作，这篇论文的新意在于：crash consistency 不再依赖 verifier 暴露新的 crash-specific logic，而是被编码进标准 verifier 都能表达的 write precondition。相对于 _Hance et al. (OSDI '20)_，它既去掉了 TLA-style refinement 这套更重的证明栈，也把 corruption axiom 从“checksum 与数据必须按某种方式摆放”降到了更底层、也更灵活的 bit-flip 模型。CDB 也不是纯粹的 proof trick，而是一个真正有系统意义的 PM 原语：它给出了一种紧凑且可证明正确的方法，让带 checksum 的更新表现得像原子切换。

这篇论文最可能影响两类人。对 verified storage builder 来说，它提供了一条可以跟着主流 verifier 生态走的路径，而不是被迫进入某个 proof assistant 与某种 crash reasoning 风格。对 persistent memory 系统设计者来说，它给出了一个既符合 PM 现实约束、又适合写证明的 corruption/update 模式。因此它既是方法论文，也是系统论文，而不只是一个“我们把某个系统证出来了”的 case study。

## 局限性

PoWER 的 tool-agnostic 有明确边界：verifier 仍然必须支持 Hoare logic、ghost state 和 quantifier。论文明确指出，像 Yggdrasil、TPot 这类高度自动化工具并不满足这个前提。并发支持也刻意收得很窄。PoWER 可以支持并发读、支持按 region 分片的并发写，但不能处理同一 storage region 上细粒度交错的读写或写写并发，因为调用 `write` 时调用方必须逻辑上知道该 region 当前的状态。

此外，论文仍然依赖若干 trusted 和 workload-specific 假设。它与 Crash Hoare Logic 的对应性证明是 metalogical 的，因为作者并没有在 Rocq 里直接实现 PoWER，而是把 PoWER 语义翻译进 Rocq。CAPYBARA KV 还依赖 `pmcopy`、编译器和 verifier 等受信任组件，并且它的设计明显针对“小而定长的记录 + 数十 GiB 专用 PM”这一使用场景：需要静态预分配空间，不支持动态扩容和 range query，启动时要重建 volatile key index，并承担明显的启动延迟。最后，PM model 还故意 overapproximate 了一些实际硬件上不一定发生的重排序，因此这些证明是保守的，而不是最小化到某个具体硬件实现的。

## 相关工作

- _Chen et al. (SOSP '15)_ — FSCQ 在 Rocq 内部引入 Crash Hoare Logic；PoWER 则把 crash reasoning 压进普通 write precondition，使主流 verifier 也能表达。
- _Hance et al. (OSDI '20)_ — VeriBetrKV 把存储验证建模成 distributed-system refinement；PoWER 避开这套更重的证明栈，并放松了 checksum 布局假设。
- _Chajed et al. (SOSP '19)_ — Perennial 提供 crash invariant 与 logically atomic crash specification；PoWER 展示了其中相当一部分效果可以包装成更简单的 API 合同。
- _Chajed et al. (OSDI '21)_ — GoJournal 展示了 verified concurrent crash-safe journaling，而本文的重点是把类似证明义务做成可跨 verifier 生态复用的 PM 方法学。

## 我的笔记

<!-- 留空；由人工补充 -->
