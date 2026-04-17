---
title: "Falcon: Algorithm-Hardware Co-Design for Efficient Fully Homomorphic Encryption Accelerator"
oneline: "Falcon 围绕硬件重写 MKS 型 FHE bootstrapping：减少 ModDown、压缩跨集群通信，并在接近 SHARP 的面积下获得更高性能。"
authors:
  - "Liang Kong"
  - "Xianglong Deng"
  - "Guang Fan"
  - "Shengyu Fan"
  - "Lei Chen"
  - "Yilan Zhu"
  - "Geng Yang"
  - "Yisong Chang"
  - "Shoumeng Yan"
  - "Mingzhe Zhang"
affiliations:
  - "Ant Group, Beijing, China"
  - "State Key Laboratory of Cyberspace Security Defense, Institute of Information Engineering, CAS, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790160"
tags:
  - security
  - hardware
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Falcon 的出发点很直接：现代 FHE 加速器为了省 evaluation key 内存，普遍采用 minimum key-switching，但这会把 `H-IDFT/H-DFT` 的实际计算代价抬得很高。论文给出的答案不是回到 key 巨大的 hoisting，而是沿着硬件约束重新设计 `MKS-BSGS`：先去掉大量 `ModDown`，再重排 giant-step 中的表示变换与通信顺序，最后配合少量硬件级融合与复用。结果是在仅比 SHARP 多 `0.8%` 面积的前提下，Falcon 对 bootstrapping 达到 `1.48x` 加速。

## 问题背景

这篇论文关注的是一个很典型的“算法上更优，但硬件上不一定更快”的矛盾。对 CKKS 来说，bootstrapping 的主耗时来自 `H-IDFT` 和 `H-DFT`，而这两个过程通常通过 baby-step giant-step (`BSGS`) 结构实现，里面包含大量 rotation、`BConv`、`NTT/INTT` 和 key-switching。纯密码学视角下，hoisting 或 double hoisting 能显著减少这些计算；但一旦落到加速器实现，问题马上变成 evaluation key 太大、片上 SRAM 装不下、片外带宽又被 key loading 吞掉。

因此，先前硬件工作更愿意采用 ARK 提出的 minimum key-switching (`MKS`)，SHARP 也沿用了这一路线。MKS 的好处是很明确的：整个 baby-step 只复用一把 evaluation key，giant-step 再复用另一把，总共只需要两把 key，因此很适合硬件内存预算。可代价同样明显。论文在高层 `H-IDFT` 的三个 level 上比较后发现，`MKS` 版本的计算代价分别比 double hoisting 高 `2.44x`、`2.64x` 和 `2.64x`。反过来，double hoisting 虽然算得少，但 evaluation key 规模却高达 `403MB`、`540MB` 和 `514MB`，依然不适合直接部署。

于是，真正的系统问题变成了：能不能保留 `MKS` 的低 key-storage 特性，同时把它额外引入的计算和通信代价削掉大半？论文的回答是，必须把算法执行顺序、暂存开销、模数域表示和集群通信一起看，而不是只盯着单个 primitive 的算术量。

## 核心洞察

论文最重要的洞察是：`MKS-BSGS` 的很多额外成本，并不是密码学上不可避免的，而是来自“过早把中间结果从 `R_QP` 拉回 `R_Q`”以及“相邻 rotation 之间表示不匹配”这两个执行层面的决定。作者分析数据依赖后发现，在连续的 `HRot` 中，真正会被下一次 key-switching 消费的主要是第二个输出分量；第一个分量往往只参与加法和 automorphism，并不需要立刻做完整 `ModDown`。

这就打开了重写空间。第一步是只对必须回到 `R_Q` 的分量做 `ModDown`，把另一部分暂时保留在 `R_QP`。第二步则针对 giant-step 的通信路径：原本一次 `ModDown` 结束后数据留在 evaluation form，而下一次 `ModUp` 却希望拿到 coefficient form，于是系统被迫在两个 rotation 之间不断做 `INTT->BConv->NTT` 所需的数据重分布。由于 automorphism 与相关的表示转换是可交换的，论文证明可以把一部分 `ModDown` 跨 rotation 边界延后，从而直接减少跨集群数据交换。换句话说，Falcon 的关键不是“发明更便宜的 primitive”，而是“重新安排表示变换发生的时间和位置”。

## 设计

Falcon 的算法设计可以看成四层递进。起点是 `MKS-BSGS`。在这个基线里，baby-step 做 `(bs - 1)` 次 rotation，共享一把 key；giant-step 做 `(gs - 1)` 次 rotation，共享另一把 key；同时用 on-the-fly limb extension (`OF-Limb`) 动态恢复 plaintext limbs，减少片外流量。这套方法节省 key 内存，但 `ModDown` 很重。

第一层改进是 `AO-BSGS`。论文引入 `Compact-KS`，让 key-switching 的第一个输出分量继续留在 `R_QP`，只把第二个输出分量做 `ModDown` 回 `R_Q`。这样可以把 `ModDown` 数量大约砍半，但代价是 plaintext 也要扩展到 `R_QP`，中间结果存储也随之膨胀，因此它更像算法层面的过渡版本。

真正面向硬件的是 `HO-BSGS`。作者意识到 baby-step 和 giant-step 的存储压力完全不同：baby-step 需要保留 `bs` 个可复用临时 ciphertext，而 giant-step 同时只活跃一个临时值。因此 Falcon 在 baby-step 里继续使用传统 `Hybrid-KS`，让所有临时结果停留在 `R_Q`，避免存储爆炸；而在 giant-step 中改用 `Compact-KS`，把第一个分量保留在 `R_QP`，从而几乎消掉一半 giant-step 的 `ModDown`。为了解决 `R_Q` 与 `R_QP` 混合时的缩放问题，论文又引入 `RP-Hybrid-KS`，利用后续 `ModDown` 中的 `P^-1` 抵消显式乘 `P`，避免额外乘法。最终，`HO-BSGS` 只增加 `alpha` 个 polynomial limbs 的存储，却保住了主要的计算节省。

下一层是 `OC-HO-BSGS`，专门处理集群间通信。传统 giant-step 中，相邻两次 `HRot` 往往要经历四次数据重分布，因为 `ModDown` 输出是 evaluation form，下一轮 `ModUp` 却想要 coefficient form，`INTT->BConv` 和 `BConv->NTT` 都会切换数据布局。Falcon 把其中一部分 `ModDown` 拆出来变成 `Split-ModDown`，再配一个 `MD-ModUp`，使得相邻两次 rotation 只剩下两次重分布。论文通过 `INTT` 的线性性质以及 automorphism 与 base conversion 的交换性证明，新顺序在数学上与原流程等价。

硬件部署方面，Falcon 基本沿用 SHARP 的 clustered vector accelerator 结构，再加两项小而有效的协同设计。第一项是 `NTTU` 中的 arithmetic fusion：把 `BConv` 第一步的乘法融合进 odd-lane 的 butterfly，只需改预计算常数，不必改关键路径电路，却能去掉大约一半 `MBU` 乘法器，使该部分面积下降 `49.78%`。第二项是 functional reuse：`BConvU` 被复用来执行 double-prime scaling 和 `OF-Limb`，从而省掉专门的 `DSU`。此外，Falcon 还提出 memory-adaptive 策略，不再像 SHARP 那样简单把 `bs` 设成“能塞进内存的最大值”，而是按 level 选择真正让计算代价最低的 `bs`。

## 实验评估

实验设置对架构论文来说相当完整。作者给出了 RTL 实现，并在 ASAP7 7nm predictive PDK 上综合；片上内存为 `190MB` scratchpad 加 `18MB` register files，片外采用两组 HBM，总带宽 `1TB/s`。比较对象包括 BTS、CraterLake、ARK 和 SHARP。工作负载也不仅是单个 kernel，而是覆盖了 bootstrapping、加密 logistic regression 训练 (`HELR256` 与 `HELR1024`)、加密 `ResNet-20` 推理和加密 sorting。

主结果很清晰。相对 SHARP，Falcon 将 bootstrapping 延迟从 `3.12 ms` 降到 `2.11 ms`，即 `1.48x` 加速；`HELR256` 从 `1.82` 降到 `1.33 ms`，`HELR1024` 从 `2.53` 降到 `1.94 ms`，`ResNet-20` 从 `99` 降到 `72.84 ms`，sorting 从 `1.38 s` 降到 `0.96 s`。与此同时，面积只从 `178.8 mm^2` 增加到 `180.3 mm^2`。这点很关键，因为它说明 Falcon 的收益不是靠粗暴堆更多硬件换来的。

最有说服力的是消融实验，因为它直接对应论文提出的机制链条。把基线 `MKS-BSGS` 换成 `HO-BSGS` 后，bootstrapping 性能提升 `1.32x`；作者将这一收益主要归因于 giant-step 中几乎减半的 `ModDown`。在此基础上继续换成 `OC-HO-BSGS`，bootstrapping 还能再快 `1.12x`，应用端再提升 `1.08-1.11x`。NoC 带宽敏感性实验也印证了这一点：NoC 越宽，`OC-HO-BSGS` 的收益越大，因为通信不再压死流水线后，算法节省下来的计算与重分布次数才能更完整地显现出来。相反，片外带宽变化对收益几乎没有影响，说明 evaluation key prefetching 已经把外存访问大体隐藏掉了。

我觉得 memory-adaptive 部分也很重要，因为它解释了为什么“更大的 `bs`”并不总是更好。对 Falcon 而言，不同 level 的最优 `bs` 不一样：最高 level 最优是 `bs = 4`，而较低两个 level 则更接近 `bs = 7`。因此最终 `190MB` 的峰值内存压力反而由次高 level 驱动，而不是最高 level。论文还额外研究了有限硬件支持的 hoisting：为 level 35/33/31 额外缓存一批 evaluation keys 后，`H-IDFT` 只能再提升 `6.67-7.31%`，却至少要多付出 `58%` 片上内存。这是一个很有价值的负结果，它恰好支撑了论文的中心论点：在现实硬件里，更聪明的执行重排比把理论上更省算的 hoisting 硬塞回来更划算。

## 创新性与影响

和 _Kim et al. (MICRO '22)_ 相比，Falcon 的新意不是提出 `MKS`，而是把 `MKS` 从“硬件上的妥协方案”重新变成“可继续优化的算法起点”。和 _Kim et al. (ISCA '23)_ 的 SHARP 相比，Falcon 最核心的贡献是把三件事串起来：重写 `BSGS` 的执行顺序、压缩 giant-step 的跨集群通信、再通过 `NTTU` 融合和 `BConvU` 复用把新增硬件成本收回来。和 _Samardzic et al. (ISCA '22)_ 这类更依赖 hoisting 的工作相比，这篇论文则把问题重新定义为“什么算法在真实 key 存储和 NoC 代价下最合适”，而不是“什么算法的纯计算量最低”。

因此，这篇论文的影响不只在 Falcon 这颗具体芯片上。凡是构建 FHE 加速器，或者在 clustered execution resource 上实现高性能 FHE runtime 的人，都可以把它当成一个更普遍的经验：对这类系统来说，模数域表示转换和数据移动顺序本身就是一等优化对象，不能只把注意力放在乘法器和 `NTT` 上。

## 局限性

Falcon 的范围是有意收窄的。它聚焦 CKKS bootstrapping 以及相关加速器设计，并没有证明这些技巧能无缝迁移到其他 FHE scheme。它的优化也高度依赖对 `R_Q`、`R_QP` 和 level-specific `bs` 的显式控制，因此系统复杂度并不低。

实验虽然做得扎实，但本质上仍是 RTL 综合加 cycle-level simulator，而不是流片后的实测芯片。论文的主要比较对象也仍然是既有加速器，而不是最新的 GPU 软件栈，所以它更直接回答的是“ASIC 设计空间里怎样更优”，而不是“真实异构部署里 Falcon 是否一定优于软件方案”。

另外，Falcon 并没有从根本上消灭内存压力，而是更精细地管理它。最终设计依然需要 `190MB` 片上内存，且敏感性实验表明 memory frequency 和 NoC bandwidth 仍然会显著影响收益兑现程度。所以它适合的是一类资源较充足、通信组织良好的 FHE accelerator，而不是极小型或极端受限的设备。

## 相关工作

- _Kim et al. (MICRO '22)_ — ARK 提出了 Falcon 所以之为起点的 `MKS-BSGS` 结构，而 Falcon 的贡献是在保留其低 key-storage 特性的同时，把被牺牲掉的计算效率尽量拿回来。
- _Kim et al. (ISCA '23)_ — SHARP 是 Falcon 直接继承的架构底座；Falcon 证明，在几乎不增加面积的情况下，算法-硬件协同设计可以明显超越 SHARP。
- _Samardzic et al. (ISCA '22)_ — CraterLake 更偏向利用 hoisting 降低 bootstrapping 代价，而 Falcon 认为 hoisting 的 key footprint 让它难以直接适配现实硬件预算。
- _Samardzic and Sanchez (ASPLOS '24)_ — BitPacker 主要提升 FHE 加速器内部的算术效率，Falcon 的独特点则是围绕 bootstrapping 调度和跨集群通信做整体重排。

## 我的笔记

<!-- 留空；由人工补充 -->
