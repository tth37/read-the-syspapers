---
title: "Deterministic Client: Enforcing Determinism on Untrusted Machine Code"
oneline: "DeCl 直接验证 x86-64 与 Arm64 机器码的确定性执行与确定性 gas 计量，让不可信原生代码无需受信 JIT 或解释器也能运行。"
authors:
  - "Zachary Yedidia"
  - "Geoffrey Ramseyer"
  - "David Mazières"
affiliations:
  - "Stanford University"
  - "Stellar Development Foundation"
conference: osdi-2025
tags:
  - security
  - isolation
  - compilers
category: verification-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

DeCl 是一个直接在不可信 x86-64 与 Arm64 机器码上强制执行确定性的 software sandbox。它把 determinism 视为一种 machine-code safety property：只允许执行具有确定语义的指令，给程序插入可验证的确定性 metering，并在需要时与 lightweight software isolation 结合。这样一来，系统既能接近原生执行速度，又不必把解释器或 JIT 放进可信计算基。

## 问题背景

论文聚焦于 adversarial determinism，主要动机来自 smart contracts。在这个场景里，程序由完全不可信的用户提供，但所有诚实副本都必须观察到完全一致的行为与副作用。现有系统大多通过 WebAssembly 或 EVM bytecode 这类 deterministic intermediate language，再配合受信解释器或 JIT 来达到这个目标。这样做能保证一致性，但 trusted code base 会变大，而且 native-code 性能也会被解释执行或受信动态编译拖住。

仅仅做到 memory isolation 并不够。一个 sandbox 即使不越界，也仍可能因为 ISA 中存在 undefined 或 unpredictable 的指令、因为程序能观测到架构相关的 flags 状态，或因为 timeout 式 preemption 落在不同的 external effect 边界上，而破坏 determinism。DeCl 因此追求比传统 SFI 更强的性质：只接受那些在目标 ISA 的所有有效 microarchitecture 上都保证确定的 machine-code program，同时还支持 bounded execution 与低 startup cost。

## 核心洞察

论文的中心命题是，determinism 可以像 memory safety 一样，通过 machine-code verifier 来强制执行。SFI 的一般思路是限制程序只能执行 verifier 能完全理解的指令子集；DeCl 只是把验证目标从“不会逃出 sandbox”提升为“所有可能执行到的指令都具有确定语义，而且所有可能通向 undefined behavior 的路径都已被静态分析或局部 rewrite 排除”。

这个视角让 native code 在不信任 compiler 或 binary translator 的前提下仍然可用。LLVM 或 GCC 依旧负责生成 assembly，但 DeCl 会先把它改写成 verifier 友好的形式，再直接验证最终 binary。于是需要受信的核心不再是 interpreter、JIT 或 translator，而是一个 linear-time verifier。Deterministic preemption 也遵循同样的逻辑：gas accounting 直接成为受验证的 machine code 行为的一部分。

## 设计

DeCl 的流水线是 compile 到 assembly，再 rewrite，再 assemble/link，最后在 native execution 前验证最终 executable。verifier 只接受来自 deterministic subset 的指令。Arm64 这一侧相对简单，因为指令是 fixed-width，只要配合 W^X memory，就能保证 verifier 与 CPU 看到同一条指令序列。x86-64 则因为是 variable-length ISA，需要 aligned bundles 来防止跳转落入指令中间字节。

之后，论文分别处理 ISA 级别的 nondeterminism。对 Arm64，verifier 会拒绝 malformed encoding、exclusive-access 指令，以及所有 unallocated 或 undefined instruction，唯一保留的例外是把 `udf #0` 当作显式 trap。对 x86-64，DeCl 先把程序限制在一个由 Fadec encoder 枚举、再以 BDD 表示的有限指令子集里，然后再叠加语义检查。像 `SHLD`、`SHRD`、`BSR`、`BSF` 这类指令会先被插入 guard sequence，避免出现 undefined result；对 undefined flags，则通过 basic block 上的 data-flow analysis 来拒绝任何可能读取这些 flags 的路径。

Deterministic metering 是第二个关键模块。Branch-based metering 在保留寄存器中维护 gas，并要求每个 basic block 末尾都带一个 metering epilogue；verifier 负责重建 leader 并确认这些 epilogue 不能被跳过。Timer-based metering 则只把 nondeterministic timer 当作“发现 gas 可能为负”的手段，真正决定是否允许产生 externally visible effect 的，是 runtime 在每次 runtime call 前做的 gas check。这样可以在降低 steady-state overhead 的同时保持可观测行为确定。

为了与 LFI 集成，DeCl 还引入了 position-oblivious code。否则，运行在共享地址空间里的 LFI sandbox 可以读到自己的 absolute load address 并据此分支。DeCl 的做法是把持有 absolute address 的保留寄存器藏起来，只允许程序通过低 32 位观察 sandbox 内 offset；calls、returns、stack-pointer reads 和 PC-relative address generation 都需要相应 rewrite。

## 实验评估

论文同时评估了底层开销和 end-to-end smart-contract 场景。在能运行于 LFI 的 integer SPEC CPU2017 子集上，带有 position-oblivious code 的 DeCl-LFI 与原始 LFI 成本接近：x86-64 上的 geomean overhead 为 9.3%，Arm64 上为 9.4%；对应的 LFI 本身分别是 9.5% 和 8.5%。真正额外的成本主要来自 deterministic metering。Timer-based metering 在 x86-64 和 Arm64 上的开销分别是 19.2% 与 19.1%，branch-based metering 则是 39.3% 与 24.1%。如果和启用 fuel metering 的 Wasmtime 相比，DeCl 便宜得多：在 WebAssembly 可支持的 x86-64 基准子集上是 35.0% 对 76.5%，在 Arm64 上则是 19.7% 对 109%。

Groundhog 集成部分让论文的系统论点真正落地。作者为每个 sandbox 预分配 128 KiB code 区和 128 KiB data 区，并利用 page aliasing 让同一份 code 在 runtime 侧可写、在 sandbox 侧可执行，从而避免频繁 `mprotect` 带来的 system call 和 TLB shootdown。这样以后，一个空合约从 load、execute 到 exit 的总时间在 M2 上是 15 us，在 Ryzen 7950X 上是 2 us；Figure 8 进一步表明，DeCl 能保持 Groundhog 一直到 192 cores 的扩展性。

对 CPU-heavy contract，差距更明显。以 zero-knowledge proof verification 为例，DeCl-timer 在 x86-64 上验证 Groth16 需要 0.344 s，在 Arm64 上需要 0.202 s；Wasmtime-fuel 分别需要 0.745 s 和 0.587 s。解释执行的差距则更大：Wasm3 分别需要 10.5 s 和 5.38 s。这些结果支持论文的核心主张：受验证的 native code 确实能同时给出较小的 trusted base 和 smart-contract runtime 需要的性能区间。

## 创新性与影响

相对于 _Haas et al. (PLDI '17)_ 以及更广义的 WebAssembly 路线，DeCl 把 determinism enforcement 从受信语言 runtime 挪到了 native binary verifier 上。相对于 _Yedidia (ASPLOS '24)_，它把 lightweight software isolation 推进成了确定语义、确定性 metering 与 position-oblivious execution。相对于 _Aviram et al. (OSDI '10)_，它解决的是 hostile input 与 machine-code verification，而不是普通程序的 deterministic execution。

这种组合对 replicated state machine，尤其是 blockchain，很有现实意义。论文比较有说服力地说明了“bare-metal smart contracts”是可落地的：开发者可以直接部署 native cryptography，同时仍然得到 deterministic execution，而不必长期支付解释器或受信 JIT 的高额性能税。

## 局限性

最明显的局限是 portability。DeCl 程序只在某一个 ISA subset 内保证确定性，并不能跨 x86-64 与 Arm64 共享同一种执行语义；verifier 还把 floating point 全部排除在外。这更像一个可落地的工程边界，而不是一套完整覆盖所有程序行为的 determinism 方案。

实现本身也有典型 low-level verifier 的脆弱性。x86-64 支持依赖于精细建模的 instruction semantics、undefined-flag analysis、aligned bundles，以及对问题编码的手工知识。论文明确把“接受子集内的硬件是正确的”列为假设，也承认 hardware bug 仍可能在 verifier 更新前破坏 determinism。compiler toolchain 方面，现有编译器无法干净地区分 integer SIMD 与 floating point，因此有些代码会被拒绝或需要额外 rewrite。最后，最强的应用结果依赖一个经过特殊调优的 runtime：固定大小的预分配 sandbox，以及 deterministic runtime calls。

## 相关工作

- _Yedidia (ASPLOS '24)_ - LFI 展示了 static verification 加 reserved-register convention 可以实现 lightweight software isolation；DeCl 直接建立在这套机制之上，但把目标从 memory safety 提升到了 determinism。
- _Wahbe et al. (SOSP '93)_ - 经典 SFI 奠定了“先 rewrite/verify native code，再允许执行”的基本模式；DeCl 把这套模式从 address-space confinement 扩展到了 deterministic semantics。
- _Haas et al. (PLDI '17)_ - WebAssembly 通过语言定义的执行模型和受信 runtime 提供 determinism，而 DeCl 保留 native code，把可信核心缩小到 verifier 和 runtime API。
- _Aviram et al. (OSDI '10)_ - Determinator 为常规程序提供 deterministic execution，但它不是面向 adversarial machine code 的 sandbox，也不解决 deterministic gas metering。

## 我的笔记

<!-- 留空；由人工补充 -->
