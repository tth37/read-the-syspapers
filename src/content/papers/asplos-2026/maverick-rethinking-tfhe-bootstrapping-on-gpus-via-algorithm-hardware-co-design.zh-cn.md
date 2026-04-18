---
title: "Maverick: Rethinking TFHE Bootstrapping on GPUs via Algorithm-Hardware Co-Design"
oneline: "Maverick 把 TFHE blind rotation 改写成延后注入 test vector 的多链流程，再用 partial-domain NTT 把更多工作推给 Tensor-Core 友好的 MAC。"
authors:
  - "Zhiwei Wang"
  - "Haoqi He"
  - "Lutan Zhao"
  - "Qingyun Niu"
  - "Dan Meng"
  - "Rui Hou"
affiliations:
  - "State Key Laboratory of Cyberspace Security Defense, Institute of Information Engineering, CAS, Beijing, China"
  - "School of Cyber Security, University of Chinese Academy of Sciences, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790186"
tags:
  - security
  - gpu
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Maverick 认为，GPU 上 TFHE bootstrapping 的真正瓶颈不只是乘法吞吐，而是 blind rotation 本身的依赖结构。它把 `TestP` 的注入从链头推迟到链尾，把原本串行的 blind rotation 改写成 `sqrt(n)` 路并行的多链流程，再通过 partial-domain `NTT/INTT` 把更多工作转成适合 Tensor Core 的 `MAC`。结果是在 programmable bootstrapping 上相对 CPU 达到最高 `331.2x`，相对最佳 GPU 基线仍有 `3.4x`，在 circuit bootstrapping 上相对 CPU 达到最高 `108.5x`。

## 问题背景

这篇论文从 TFHE 的一个根本矛盾出发。TFHE 之所以重要，是因为它的 bootstrapping 机制既能支持 bit-level logic，也能支持 programmable look-up-table evaluation 和 circuit bootstrapping，因此适合私有推理、加密数据库和密码学 transpiler 这类对表达力要求很高的场景。但代价也非常明确：一次 bootstrapping 往往包含上万次 polynomial multiplication，而论文指出，在 `PBS` 和 `CBS` 中，blind rotation 单独就占了接近 `70%` 的总运行时间。

过去几年里，ASIC、FPGA 和 GPU 上已经有不少 TFHE 加速工作，但作者认为它们大多仍被同一套算法依赖关系锁死。传统 blind rotation 是一条长度为 `n` 的 external product (`EP`) 单链，每一步都依赖上一步，因此每轮最多只能发出一个 `EP`。batching 能提升吞吐，却几乎不改善单个 ciphertext 的延迟；loop unrolling 虽然能缩短链深，但本质上仍留在单链框架里，还会引入 key size 和存储方面的额外代价。换句话说，现有方案大多是在“硬件更强”的前提下继续执行“并行度很差”的算法。

硬件侧的问题同样严重。论文显示，blind rotation 中 `(I)FFT/(I)NTT` 的时间占比超过 `70%`。在 GPU 上，全域变换需要按 stage 反复同步，还伴随不规则内存访问；而下游 `MAC` 却只剩下比较轻量的标量乘法。结果就是整个流水线很不平衡：最耗时的部分恰好最依赖同步、最容易让 GPU 闲着，而后续算子又不足以把这些损失补回来。所以这篇论文真正要解决的，并不是“把某个 kernel 再优化一点”，而是“能否把 blind rotation 本身改写成更适合 GPU 的依赖结构和算子分工”。

## 核心洞察

Maverick 的核心命题是，TFHE blind rotation 的串行性并没有想象中那么不可打破。问题的根源在于 test vector 绑定得太早。标准 blind rotation 一开始就把 `TestP * X^b` 放进整条链里，之后每一个 `EP` 都在这个状态上继续推进，因此看起来整条流程天然就是一条长链。Maverick 观察到，指数项的累积其实并不需要 test vector 一路跟随。只要把 `TestP` 延后到最后再注入，前面的 `EP` 就只是在累积 exponent，而不再依赖 test vector 本身。

这一步让 blind rotation 可以从长度为 `n` 的单链，重写成 `x` 条深度为 `y` 的子链，只要满足 `x * y = n`。论文进一步把总 `EP` 等价代价写成 `y + c + x`，其中 `c` 是 ciphertext conversion 的开销，并用这个模型推导出最优点在 `x = y = sqrt(n)`。具体来说，每条子链都从 trivial `GLWE(1)` 开始，先独立执行自己的串行 `EP`；随后通过一段 ciphertext conversion 把输出重新变成 `GGSW`；最后再用一条深度为 `sqrt(n)` 的链，从延后注入的 `TestP * X^b` 出发，把这些结果依次吸收回去。六个月后读者最该记住的，不是某个 kernel 提升了多少，而是 blind rotation 的最佳加速路径其实是“先改依赖图，再谈硬件”。

第二个洞察是，光把 `EP` 并行度放出来还不够，剩下的瓶颈会立即转移到算子失衡上。为此 Maverick 又把 `NTT` 提前终止，只做到中间阶段，输出 sub-polynomial 而不是 scalar。缺掉的那部分变换工作并没有被省掉，而是被吸收到后续 `MAC` 里，从而把原本同步很多、算术密度很低的全域变换，改造成同步更少、但 `MAC` 更重更密集的执行路径。这样一来，`MAC` 才有机会更好地贴合 GPU 的矩阵计算单元。论文真正的 insight 是，算法层面的依赖改写和硬件层面的算子边界重划必须一起做，单独做任何一边都不够。

## 设计

Maverick 的多链 blind rotation 分成三步。第一步，把原始单链拆成 `sqrt(n)` 条并行子链，每条子链深度也是 `sqrt(n)`。每条子链都从一个 trivial `GLWE` 密文 `1` 开始，再用对应的 `GGSW` bootstrapping key 去累积局部 exponent。第二步，把每条子链的输出从 `GLWE` 转回 `GGSW`。这里很关键的一点是，论文没有为此额外发明新 primitive，而是把 homomorphic trace 和 scheme switching 都建立在现有 `EP` operator stack 上。第三步，再执行一条深度为 `sqrt(n)` 的最终 `EP` 链，这时才从延后注入的 `TestP * X^b` 出发，把前面所有中间结果吸收进去，从而恢复与标准 blind rotation 完全一致的多项式移位语义。

这种改写当然不是零成本的，所以论文对开销算得比较细。Ciphertext conversion 会增加额外的 `EP` 等价工作量，也会引入少量额外 key material。但在作者给出的 `PBS-I` 参数下，这部分附加内存只有 `1.06 MB`，不到 `163.125 MB` bootstrapping key 的 `0.7%`，规模上基本可以忽略。作者也做了明确的 noise 分析。系统安全性仍然依赖与标准 TFHE 相同的 `(R)LWE` 假设；新增噪声主要来自 homomorphic trace 和 scheme switching。沿用 prior circuit-bootstrapping work 的参数选择方法后，论文报告 decryption-failure probability 可控制在 `2^-40` 以下，也就是说这套改写仍处在常规 TFHE 的正确性预算之内。

硬件侧的另一半设计是 partial-domain transformation (`PDT`)。传统 full-domain `NTT` 会一直做到 scalar evaluation form，因此每个 stage 都要做全局同步，而 `MAC` 只剩便宜的逐点乘法。Maverick 在更早的 stage 停下来，让表示形式变成一组 sub-polynomial。后面的 `MAC` 改为对子多项式做乘法，逆变换 `IPDT` 也采取对称的做法。论文强调，这并不是近似技巧，而是对标准 `NTT-MAC-INTT` 流水线的代数重排：被“省略”的那些变换 stage 其实被吸收到 `MAC` 的代数里了，因此语义不变。由于 `NTT` 本身是在有限域上的精确线性变换，这种改写也不会引入新的近似误差。

为了让这种表示在 GPU 上真的高效，Maverick 又把 sub-polynomial multiplication 映射成矩阵运算。Bootstrapping key 会先离线排成固定 layout，因此运行时不用再付一次转换代价。执行时，ciphertext 系数被打包成矩阵，`MAC` 就退化成 vector-matrix 或 matrix-matrix multiplication，并且同一批次里可以重复复用 bootstrapping key。实现上，作者使用 `CUTLASS`，把 32-bit integer 拆成多个 `int8` slice，交给 Tensor Cores 执行，再用 Booth-style recomposition 合回全精度结果。最终系统包含 `Decompose`、`PDT/IPDT`、`MAC`、sample extraction 和 LWE key switching 等 CUDA kernels，并通过一个 client/server 形式的 TFHE runtime 组织起来。

## 实验评估

实验覆盖面对于一篇 GPU 密码学论文来说相当完整。主实验平台是一台配有 Intel Xeon W5-3435X、`128 GB` 内存和八张 `RTX 4090` 的服务器，同时作者也在 `A100` 和 `H100` 上验证可移植性。参数集覆盖 `GBS`、两组 `PBS` 和两组 `CBS`，应用工作负载则包括 non-linear functions、decision trees、DeepCNN-X 私有推理和 AES transciphering。这个组合是合理的，因为 Maverick 的论点针对的是 bootstrapping substrate 本身，而不是某个狭窄 microbenchmark。

主结果对论文的中心论点支撑很强。相对 CPU 基线，Maverick 在 programmable bootstrapping 上比 `TFHE-rs` 快 `216.7x-331.2x`，在 circuit bootstrapping 上比 `RJX+` 快 `101.1x-108.5x`。相对同样运行在 `RTX 4090` 上的 GPU 基线，它比 `XLK+` 快 `7.7x`，比 `HEonGPU` 快 `5.7x`，相对论文里最强的 GPU programmable-bootstrapping 基线 `VeloFHE` 也还有 `3.4x` 优势。跨平台比较则更能说明它的位置：Maverick 比 `XHEC` FPGA 快 `8.3x`，比 `MATCHA` ASIC 快 `3.3x`，但面对专门为 TFHE 设计的 `Morphling` ASIC 仍然落后约 `4.4x`；把平台换成 `H100` 后，这个差距缩小到 `2.5x`。这个结果很符合预期，因为 Maverick 的目标本来就不是打败专用芯片，而是逼近它们。

论文的敏感性实验也很有价值，因为它们直接检验了设计机制本身。子链配置的最优点出现在 `x = ceil(sqrt(n))`，与前面的分析模型一致。对 `PDT` 而言，`PBS` 和 `CBS` 的最优执行 stage 数都是 6：再少的话，虽然 `(I)NTT` 的同步成本继续下降，但 `MAC` 会变得过重，反而拉低整体性能。Batching 实验则揭示了收益来源：在小 batch 下，多链 blind rotation 会显著提高 GPU `SM` 利用率，相比传统 blind rotation 和 loop unrolling 都更有效；到了大 batch，前者会更早进入饱和区，这时 `PDT` 成为主要贡献者，仍能带来大约 `3x` 的改善。论文还把目标 decryption-failure probability 从 `2^-40` 进一步压到 `2^-47`，方法是提高 homomorphic-trace 和 scheme-switching 的 level，但性能几乎不受影响，这一点对可用性很重要。

应用端结果说明，这些收益并没有在真实 workload 上蒸发掉。在 `PBS-II` 参数下，Maverick 对 non-linear functions 相对 `Pegasus` 最高提升 `197.4x`，相对 `Concrete-ML` 提升 `10.6x`，相对 `XLK+` 提升 `6.7x`；从 `RTX 4090` 换到 `H100` 还能再拿到 `1.7x`。在 private decision tree 上，Iris 分类相对 `Pegasus` 提升 `46.8x`，相对 `XLK+` 提升 `9.5x`。在 DeepCNN-X 私有推理上，`RTX 4090` 上相对 `Concrete-ML` 有 `2.7x-4.8x`，`H100` 再加 `1.9x-2x`。在基于 `CBS` 的 AES transciphering 上，相对 CPU `RJX+` 则达到 `71.8x-74.7x`。这些结果说明 Maverick 的 co-design 并不是只对某个 synthetic benchmark 有效，而是对 programmable 和 circuit-style 的 TFHE 使用场景都成立。

## 创新性与影响

和 _Xiao et al. (TCHES '25)_、_Shen et al. (TCHES '25)_ 这类既有 GPU TFHE 工作相比，Maverick 的新意不只是更快的 `NTT` kernel 或更激进的 Tensor Core 使用方式。它真正改变的是 blind rotation 的依赖结构：通过延后注入 test vector，再配合 conversion-backed 的多链调度，把原本“只能串行发一个 `EP`”的算法改写成 GPU 更吃得下的形式。和 _Wang et al. (EUROCRYPT '24)_ 这类 circuit-bootstrapping 工作相比，它的新意则在于把 homomorphic trace 与 scheme switching 从 end-to-end `CBS` 里的组成步骤，重用成 programmable bootstrapping 内部的一座桥。

这让论文有不错的后续影响潜力。按作者自己的表述，Maverick 是首个同时覆盖 `GBS`、`PBS` 和 `CBS` 的 GPU 方案，更重要的是它证明了通用 GPU 上的 TFHE 还有明显的结构性优化空间。未来无论是 TFHE runtime 还是加速器论文，都很可能会引用 Maverick 的更大观点：homomorphic evaluation 里的算子边界不是固定不动的，可以为了机器结构而重新划分。

## 局限性

论文并没有回避多链改写的代价。在 CPU 单线程下，额外的 ciphertext-conversion 开销会让 multi-chain blind rotation 比基线慢 `1.26x`，也就是 `GBS` 设置下的 `8.21 ms` 对 `6.5 ms`。只有当线程级并行或 GPU 级并行足够高时，这种额外结构才能被摊薄。同样地，在很大的 batch 下，多链 blind rotation 会更早进入饱和区，因此边际收益下降，后续更多是靠 `PDT` 支撑提升。这个失败模式并不糟糕，但它说明收益是负载区间相关的，而不是无条件存在。

此外，Maverick 仍然是一个相当平台相关的设计。它围绕 NVIDIA GPU、CUDA、Tensor Core 以及特定 TFHE 参数集做了深入调优；当 `n` 不是完全平方数时，甚至还要把它上调到下一个完全平方数 `n'`，才能保留那套平衡分解。论文也没有讨论能耗、多租户服务场景或异构集群部署问题。再加上最强的专用 ASIC 仍然更快，可以说 Maverick 证明了“通用 GPU 能走多远”，但并没有终结“为什么还需要定制 TFHE 硬件”这个问题。

## 相关工作

- _Xiao et al. (TCHES '25)_ — XLK+ 在 GPU 上加速 TFHE bootstrapping，但仍沿用传统 single-chain blind rotation；Maverick 直接改写了这张依赖图。
- _Shen et al. (TCHES '25)_ — VeloFHE 是论文里最接近的 GPU programmable-bootstrapping 基线，而 Maverick 在更快 kernel 之外，还加入了 multi-chain blind rotation 和 partial-domain transform。
- _Wang et al. (EUROCRYPT '24)_ — Circuit bootstrapping 提供了 homomorphic trace 与 scheme switching 这套机制，Maverick 把它们重新利用成 ciphertext conversion 阶段。
- _Putra et al. (HPCA '24)_ — Morphling 展示了 transform-domain reuse 在 ASIC 上的收益，而 Maverick 则在通用 GPU 上用“重划算子边界”的思路去逼近类似效果。

## 我的笔记

<!-- empty; left for the human reader -->
