---
title: "ReliaFHE: Resilient Design for Fully Homomorphic Encryption Accelerators"
oneline: "ReliaFHE 为 FHE 加速器加入分层校验和保护，同时覆盖存储与计算故障，以约 1.5% 运行时和 1.9% 面积开销显著提升可靠性。"
authors:
  - "Fan Li"
  - "Mayank Kumar"
  - "Ruizhi Zhu"
  - "Mengxin Zheng"
  - "Qian Lou"
  - "Xin Xin"
affiliations:
  - "University of Central Florida, Orlando, FL, USA"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790211"
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

ReliaFHE 追问了一个此前多数 FHE 加速器论文都默认跳过的问题：如果硬件并不完美，FHE 计算还能不能可靠运行？它给出的答案是一个基于 checksum 的分层韧性框架，同时保护存储和 FHE 最核心的算术内核，并把保护拆成行列校验、总校验和小粒度 intra-element checksum 三层。论文报告称，该框架能把可靠性提升到超过 `10^4` 倍，同时只带来约 `1.5%` 的运行时开销、`1.9%` 的面积开销，以及低于 `1%` 的校验存储开销。

## 问题背景

这篇论文的出发点是：FHE 对硬件故障的脆弱性，比普通数值程序严重得多。RLWE 类 FHE 的 ciphertext 本质上是大多项式，而现代实现又会把很多 plaintext 值通过 SIMD 风格编码塞进同一个 ciphertext，所以一个底层硬件错误往往会同时污染很多逻辑结果。随后，模运算会把本来很小的 ciphertext 扰动在解密后放大成很大的 plaintext 偏差；对矩阵乘法常用的 diagonal packing 会把局部错误传播到整批输出；NTT 与 RNS BaseConv 这样的表示变换又会把局部故障扩散到整个 ciphertext。

作者用 fault injection 把这个问题量化了。实验显示，在 plaintext 算术里只会扰动一个输出元素的单比特翻转，在 FHE 里会让所有解密 slot 都接近随机值；在应用层，encrypted ResNet-20 在错误率达到 `10^-5` 左右时就会跌到接近随机猜测，而对应的 plaintext 模型此时仍然接近 `90%`。现成的保护手段又不适配：memory ECC 只管存储，重复执行对 FHE 太贵，RRNS 又和 ciphertext 已经采用的 RNS 表示相冲突。于是，问题被收紧成一个更具体的系统设计题：怎样做一个和 FHE 算术兼容、同时保护计算与存储、而且总开销还能控制在 `~1%` 量级的韧性框架。

## 核心洞察

论文最重要的洞察是：FHE 最令人头疼的一个特征，恰好也是低开销保护的机会。由于多项式 limb 的长度 `N` 通常在 `2^12` 到 `2^16` 之间，系统可以构造很大的 checksum codeword，而这些 parity 相对于原数据的占比会非常小。与此同时，在 FHE 里 modular addition 远比 modular multiplication 便宜，因此只要保护逻辑尽量建立在“加法式 checksum”而不是“额外乘法”上，额外成本就能压得很低。

基于这个观察，ReliaFHE 采用分层设计。它把真正的 error correction 放在 storage 侧，因为行/列 checksum 可以重建丢失数据；而 computation 侧只做 error detection，再依赖重算。随后，保护形式再跟随算术内核的结构匹配：对标量式操作使用 total checksum，对 element-wise modular multiplication 使用紧凑的 intra-element checksum，对 four-step NTT 里的成批 sub-NTT 则使用行/列 checksum 联合验证。最值得记住的命题是：只要保护结构沿着高性能 FHE 本身的算术分解来设计，韧性就不必靠高额冗余来换。

## 设计

ReliaFHE 先从存储保护开始。它把一个 polynomial limb 或 NTT vector 重排成二维矩阵，然后为每一行、每一列，以及整个矩阵分别保存 checksum。这个布局和物理内存阵列的行列组织天然一致，因此不仅能检测零散 bit error，还能恢复整行或整列失效。由于 FHE 保护对象本身很大，额外 parity 的存储开销可以压到 `1%` 以下。

计算路径则被分成三类操作。第一类是 `ScalOp`，即对每个元素施加同一个标量或同一种变换的操作，例如 BaseConv 里的缩放步骤和 modular reduction。它们会保持数据 checksum 与结果 checksum 之间的简单关系，因此能便宜地做验证，并辅以 range check 去捕捉 checksum 本身可能漏掉的错误商值。第二类是 `ElemOp`，即 element-wise modular multiplication。作者把它拆成宽位乘法和模约减两段，再用小粒度 intra-element checksum 保护前者、用 total checksum 跟踪整向量结果。

第三类是 `NttOp`，也是全篇最巧妙的部分，因为直接套传统 ABFT 保护 NTT 会太贵，而且 NTT 的结构对简单权重向量并不友好。ReliaFHE 利用现代 FHE 实现普遍采用的 four-step NTT，把一个大 NTT 拆成两批较小的 sub-NTT。重排后的矩阵上天然存在行/列 checksum，于是系统可以一次性联合验证一整批 sub-NTT，而中间插入的 twiddle multiplication 直接复用 `ElemOp` 的保护逻辑。论文还把 checksum 带过模块边界和 memory interface，避免传输与 buffering 变成漏网之鱼。

## 实验评估

这篇论文的实验比较完整，覆盖了 arithmetic kernel、primitive operation、端到端 workload，以及独立的 reliability 和 hardware study。先看内核级结果。对实际使用的多项式规模 `N > 2^12`，ReliaNTT 的开销大约只有 `1%`，ReliaElemOp 稳定在 `4.6%` 左右，而 BaseConv 的保护开销低于 `0.1%`。由于 NTT 是 FHE 运行时里的主导部分，这组数字基本决定了方案是否成立。

在 primitive operation 层，BFV/CKKS 的 homomorphic multiplication 与 rotation 在 `N = 2^14` 时平均开销约为 `1.5%`。端到端层面，作者基于 SEAL、Lattigo 和 Orion 跑了 MLP、LoLA CryptoNet、LeNet-5，以及带 bootstrapping 的 ResNet-20 等工作负载，整体运行时开销保持在 `2%` 以内，bootstrapping 自身大约是 `1.45%`。更关键的是可靠性：在 primitive-operation fault 场景下，ReliaFHE 相比无保护基线把可靠性提升到了 `10^4` 以上；在应用层，即便 fault rate 很激进，encrypted inference 的精度下降也能控制在 `3%` 以内。内存实验则说明大 codeword 的价值：与 HBM3 风格的 `RS(19,17)` 相比，ReliaFHE 在论文报告的行级和列级故障案例中都能做到无 silent data corruption。

硬件综合方面，把它加到 F1、ARK、CraterLake 和 Trinity 风格的加速器上，平均面积开销约为 `1.9%`，平均功耗开销约为 `1.46%`。整体来看，论文的证据链是扎实的。需要保留的一点是，运行时开销来自软件栈测量，硬件成本来自综合，而不是一个真正流片、端到端部署的 resilient FHE 芯片。

## 创新性与影响

和 _Kim et al. (MICRO '22)_、_Kim et al. (ISCA '23)_ 这些 FHE accelerator 工作相比，ReliaFHE 的贡献不是让某个算术内核再快一点，而是第一次正面回答“这些 datapath 在真实故障下怎么活下来”。和 RRNS 一类算术保护相比，它最大的创新是兼容性：它不要求 ciphertext 额外改成一套冗余算术表示，而是直接顺着 FHE 已有的 RNS/NTT 结构去布置保护。和传统 ECC 相比，它也不是只守 memory，而是把 storage、transport、以及三类主导计算内核统一进一个框架里。

因此，这篇论文更像是在提出一类新的韧性机制，而不是一篇边际提速论文。对于 accelerator architect，它给出了 FHE 专用可靠性设计的第一套清晰蓝图；对于想把 FHE 推向真实集群部署的人，它也提醒大家可靠性不会永远是次要问题。

## 局限性

论文的边界也很明确。计算侧保护主要还是 error detection 加重算，真正的 error correction 只发生在存储侧。因此，整个设计里最薄弱的一环仍然是窄位宽的 intra-element checksum。作者也明确承认，特别是在 `+e` 和 `-e` 这种对称错误模式下，checksum collision 是最主要的残余风险。虽然 Monte Carlo 结果表明 `24` 位 checksum 已经把碰撞概率压得很低，但它终究是概率式保护。

此外，最佳的 NTT 保护效率依赖 four-step NTT 这一现代 FHE 实现中常见的分解方式。落在 `ScalOp`、`ElemOp`、`NttOp` 之外的少数特殊 kernel，则通过简单 duplication 处理，因为它们只占不到 `0.5%` 的运行时。最后，实验基于 fault injection 和综合模型，而不是长期运行在真实大规模 FHE 集群上的 field data，因此部署层面的长期行为仍有待观察。

## 相关工作

- _Kim et al. (MICRO '22)_ — ARK 展示了如何通过 runtime data generation 和 key reuse 加速 FHE，但仍默认硬件执行正确；ReliaFHE 则为这一类 datapath 加上韧性层。
- _Kim et al. (ISCA '23)_ — SHARP 优化的是 short-word hierarchical FHE arithmetic，而 ReliaFHE 关注的是这些 NTT、BaseConv 和乘法单元建成之后如何被保护。
- _Deng et al. (MICRO '24)_ — Trinity 把 FHE acceleration 推向更通用的设计空间，而 ReliaFHE 提供的是一套正交的可靠性基础设施，可被这类通用加速器吸收。
- _Cilasun et al. (ISCA '24)_ — resilient processing-in-memory 工作研究了 memory-centric accelerator 的低成本纠错/检错，而 ReliaFHE 把这类思路进一步改造成适配 FHE 的 SIMD packing 与 modular arithmetic。

## 我的笔记

<!-- 留空；由人工补充 -->
