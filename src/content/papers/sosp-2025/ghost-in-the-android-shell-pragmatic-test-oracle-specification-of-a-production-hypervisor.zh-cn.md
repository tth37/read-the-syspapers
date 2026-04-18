---
title: "Ghost in the Android Shell: Pragmatic Test-oracle Specification of a Production Hypervisor"
oneline: "把可执行 ghost-state 规格嵌入 Android pKVM，在 hypercall 运行时做检查，以低于完整验证的成本发现真实 hypervisor 问题。"
authors:
  - "Kayvan Memarian"
  - "Ben Simner"
  - "David Kaloper-Meršinjak"
  - "Thibaut Pérami"
  - "Peter Sewell"
affiliations:
  - "University of Cambridge, UK"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764817"
code_url: "https://github.com/rems-project/linux/tree/pkvm-verif-6.4"
tags:
  - virtualization
  - security
  - formal-methods
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文并不试图把 Android 的 pKVM 做成“完整验证的 hypervisor”。它选择了一个更轻量的中间路线：把可执行的 ghost-state 规格直接写进 C 代码，在精心挑选的 lock 与 trap 边界记录抽象状态，并在每次 hypercall 或 exception 后检查实现是否到达了允许的 post-state。这个做法虽然不提供定理级保证，但已经足以发现真实的 pKVM bug 和大量规格错误，而且成本低到可以进入日常测试流程。

## 问题背景

pKVM 运行在 Arm 的 EL2，用来隔离 Android host kernel 与 protected VM。这个位置让 assurance 变得格外困难：代码是传统的 C 和 assembly，运行在 bare metal 上，要维护硬件也会隐式访问的 page table，还要和 host、guest 以及其他 CPU 并发执行。普通的 kernel 测试当然可以说明系统能启动、常见路径能跑通，但它很难回答更关键的问题：每个 hypercall 是否都保持了预期的 ownership 与 mapping invariant。

另一端的极限方案是 full functional verification。论文承认，这条路线已经在 kernel 和 hypervisor 上取得过成功，但 adoption 成本仍然很高，往往需要专门的 proof tooling、为验证而重写的代码结构，以及跨版本维护证明的持续投入。对 Linux tree 中一个已经部署的 production hypervisor 来说，这个门槛并不低。

于是论文追问一个更实际的问题：能不能在实现语言本身里写出足够丰富的 functional-correctness specification，把它当成 test oracle 随执行一起跑，从而在不重写 pKVM、也不建立完整证明栈的前提下，拿到更强的 assurance？真正困难的地方正是系统开发者平时最容易回避的部分：并发、需要保留弹性的 loose specification、强架构相关的 page-table 语义、EL2 上贫瘠的调试与覆盖率工具，以及“太随机”的测试会直接把整个测试系统打崩。

## 核心洞察

论文最重要的洞察是：不要直接对着 page-table tree、pointer 结构和零散元数据写规格，而是先构造一个 reified ghost state，只保留实现状态里和安全语义真正相关的部分。于是，规格面对的是抽象 mapping、ownership annotation、VM 元数据和 per-CPU 状态，而不是工程化的具体表示。

一旦有了这层抽象，每个 trap 或 hypercall 就可以被写成“从 recorded pre-state 计算 expected post-state”的函数。这样写的规格之所以可读，是因为它直接表达意图，而把具体实现细节藏进 abstraction function。论文更深的一点在于：这件事只有在 ghost state 跟随实现的 ownership discipline 时才真正成立。也就是说，状态必须在 pKVM 真的拥有它的时候记录，通常是在 lock acquire/release 或 trap entry/exit，而不是用一个全局大锁把并发结构抹平。

## 设计

整体设计分成三层。第一层是抽象 ghost state。本论文为 pKVM 自身 page table、host 的 logical ownership 与 shared mapping、guest VM 元数据、全局常量以及 per-CPU local state 各自定义了抽象表示。其中最关键的数据结构是 abstract mapping：它把输入页映射到输出页，并携带权限和 ownership 属性。具体的 Arm page table 会通过可执行的 abstraction function 被遍历，并转换成这种有限映射形式。

第二层是在 pKVM 中插入少量 instrumentation 来记录这些抽象。thread-local 状态在 top-level trap 入口和出口记录；由 lock 保护的共享状态则在 lock 获取和释放时记录。这样做的好处是可以面对真实并发，而不是假装 pKVM 是顺序程序。论文反复使用的 `host_share_hyp` 就是例子：它对 host 与 hypervisor page table 采用 two-phase locking，checker 会在加锁阶段记录相关 pre-state，在解锁阶段记录 post-state，然后计算预期状态并与记录到的状态比较。

第三层是 hypercall 规格本身，它们也是可执行的 C 函数。对 `host_share_hyp` 来说，规格远比实现简洁：先做地址转换，再检查目标页是否由 host 独占，随后构造正确的抽象属性，更新 host 与 pKVM 的 mapping，并把返回码写回记录下来的寄存器状态。为了在实现存在 nondeterminism 的情况下仍保持这种函数式风格，规格会把观察到的 return code 和从 shared memory 中读到的值当成参数输入。作者还刻意让规格在某些地方保持“松”，例如允许 `-ENOMEM` 失败，或不精确约束 map-on-demand 的具体行为，这样 oracle 检查的是“意图上的正确性”，而不是把当前代码结构硬编码进规格。

围绕这个核心，作者还补齐了 EL2 缺失的测试基础设施：一个 Linux “hyp-proxy” patch，把 pKVM 操作暴露给 user space 测试；EL2 的 coverage tooling；一个 OCaml 测试库；以及手写测试和随机测试生成器。最后这点很关键，因为完全无引导的随机 hypercall 大多只会让 host 崩溃，根本走不到有价值的状态空间。论文用一个更轻量的 ownership 模型来引导采样，从而兼顾探索性与可执行性。

## 实验评估

实验更有力地证明了“可行且有用”，而不是宣称“单靠 runtime oracle 就能自动抓到大量 bug”。手写测试一共 41 个，其中 19 个覆盖正常路径，22 个覆盖错误路径，还有若干专门针对并发与锁。对论文详细展开的 `__pkvm_host_share_hyp` 路径，作者在手工扣除 KVM 通用 helper 中不可达代码后，报告了 100% 的 line coverage。对全部 specification function 来说，覆盖率是 92%，也就是 497 行里覆盖了 459 行。

随机测试不是盲目的。它在 QEMU 中运行，在一台 Mac Mini M2 上大约每小时能执行 200,000 次 hypercall，最长运行 24 小时。这些测试发现了 9 个 specification 本身的错误，主要集中在微妙的错误路径上。这个结果很重要，因为它说明可执行 oracle 不是“陪跑代码”，而是真的有能力把实现、理解与规格之间的不一致暴露出来。

更广义地看，整个工作一共发现了 5 个得到开发者确认的 pKVM bug，其中包括一个 host pagefault race，可能导致 hypervisor panic，以及若干 allocator 和初始化路径的问题。论文非常诚实地指出：这 5 个 bug 里，只有 1 个是通过运行时规格检查直接发现的，其余 bug 则是在为了写规格而深入阅读代码时暴露出来的。这个表述反而让论文更可信，因为它真正强调的不是“神奇自动验错器”，而是一种迫使开发者精确定义系统语义、然后用可执行 oracle 持续守住这份理解的 workflow。

成本方面，论文的论证最有说服力。pKVM 本体大约 11 KLoC；规格、抽象记录和支持代码合起来大约 14 KLoC。总投入约 1 person-year，而 pKVM 的开发投入约 30 person-years。运行期开销对测试来说是可接受的：额外内存大约 18 MB，QEMU 中 boot 时间变慢 3.2 倍，手写测试变慢 11.5 倍。这个开销显然不适合 production，但论文也从未这样声称；它的目标就是 testing-time assurance，而在这个标准下，这些数字是站得住的。

## 创新性与影响

这篇论文的创新不在于提出新的 proof system、spec language 或 hypervisor 机制，而在于证明了一件很多人以为太别扭、其实却可以落地的事：对一个并发的、依赖硬件地址转换语义的 production hypervisor，可以在 plain C 里后验地写出 full-functional 的 executable specification，并把它真正跑起来。相较于 SOSP 2021 那篇关于 Amazon S3 的 executable-spec 工作，这里要解决的是更棘手的并发、ownership 和 bare-metal tooling 问题。

它的影响因此很实际。对于不可能马上导入完整验证工具链的 hypervisor 或 kernel 团队，这篇论文给出了一条比 sanitizer 和 integration test 更强、但又明显低于 full verification 门槛的路径。它也说明了一个工程收益：写规格本身就是一种纪律化的 code-reading 过程，能尽早暴露 bug 和模糊语义；而可执行 checker 则把这份理解变成后续回归测试时可持续使用的护栏。

## 局限性

覆盖范围并不完整。作者没有覆盖 pKVM 的 device-assignment 路径、GIC 和 IOMMU，一部分原因是这些部分更晚加入，另一部分原因是其底层架构语义更复杂、更不清晰。论文关注的是 functional correctness，而不是 side channel、denial of service 或 liveness。

并发方面也仍有边缘空白。一些会释放再重新获取锁的 phased hypercall 目前还没有处理；guest 或 host 执行与 page-table 更新之间的竞争也只被部分抽象。由于规格嵌在 pKVM 内部，理论上也存在一种可能：某个实现 bug 先破坏了 ghost state，从而掩盖另一个 bug。作者认为这种情况概率不高，并把 ghost allocator 放在独立内存区域以降低风险。最后，维护成本是真实存在的：因为 ghost state 紧跟实现的 ownership 结构，像新增 per-vCPU lock 这样的重构会迫使规格做不小的同步修改。

## 相关工作

- _Amit et al. (SOSP '15)_ — Virtual CPU validation 用 ISA 级语义测试 hypervisor 的 instruction emulation；本文则面向 pKVM 的 hypercall 与内存 ownership 行为，而这些本来并没有现成的 formal oracle。
- _Bornholt et al. (SOSP '21)_ — Amazon S3 那篇工作同样使用 ambient-language 的 executable specification 做差分检查，但本文把这种思路推进到了用 C 编写、在 bare-metal 上并发运行的 hypervisor。
- _Bishop et al. (JACM '19)_ — Engineering with Logic 强调对既有网络代码进行 post hoc test-oracle specification；本文把这种理念带到了 EL2 hypervisor 代码与运行时状态抽象上。
- _Cebeci et al. (SOSP '24)_ — 面向 standard C 系统组件的 practical verification 追求更强的自动化保证；本文则接受更弱的保证，以换取在既有 production 代码与常规工具链上的立即可部署性。

## 我的笔记

<!-- 留空；由人工补充 -->
