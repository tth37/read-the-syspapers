---
title: "A Framework for Developing and Optimizing Fully Homomorphic Encryption Programs on GPUs"
oneline: "EasyFHE 把 GPU FHE 做成类似 PyTorch 的运行时后端，用分层 lowering 减少密钥内存、运行期分配开销和冗余多项式计算。"
authors:
  - "Jianyu Zhao"
  - "Xueyu Wu"
  - "Guang Fan"
  - "Mingzhe Zhang"
  - "Shoumeng Yan"
  - "Lei Ju"
  - "Zhuoran Ji"
affiliations:
  - "Shandong University, Qingdao, China"
  - "The University of Hong Kong, Hong Kong, China"
  - "Ant Group, Hangzhou, China"
  - "State Key Laboratory of Cryptography and Digital Economy Security, Jinan, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790120"
code_url: "https://github.com/jizhuoran/EasyFHE"
tags:
  - security
  - gpu
  - compilers
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

EasyFHE 是一个位于前端编译之后、GPU kernel 之前的全同态加密运行时框架。它的关键做法是一条分层 lowering 管线，用 FHE 特定的优化 pass 去降低内存占用、削减分配开销并消除冗余算术，最终相对开源 GPU 基线取得最高 `4.39x` 的加速。

## 问题背景

论文抓住的是 primitive 加速和应用可用性之间的断层。过去的 GPU FHE 工作已经把 CKKS 的核心操作做得很快，但真正写一个端到端 FHE 程序仍然很难，因为开发者要同时处理密文状态、rescaling、evaluation key 和显存行为。对多数用户来说，他们真正想表达的是高层加密计算逻辑，而不是底层实现细节。

即便这些 primitive 已经存在，整套应用依然会慢，主要有三点原因。第一，rotation key 和编码常量往往比 ciphertext 更占内存，现实 workload 很容易超过 GPU 容量。第二，FHE 程序会频繁创建和销毁短生命周期中间对象，GPU 上这种细粒度内存管理代价很高。第三，lower 到多项式算术之后仍然会出现重复 modulus change、重复旋转辅助步骤和重复常量编码，单独优化 kernel 并不能解决这些问题。EasyFHE 的出发点就是：端到端 GPU FHE 需要一个运行时后端，而不只是更快的 primitive。

## 核心洞察

论文的核心命题是，后端结构和 primitive 吞吐同样重要。由于 FHE 工作负载不能依赖明文数据做控制流，EasyFHE 可以把输入程序改写成没有分支和循环的 SSA 风格 homomorphic primitive 序列，再逐层 lower。这样一来，系统就能跨 primitive 看见原本看不见的优化机会。

这正是它奏效的原因。把程序拆成实现选择、polynomial-set 级操作和 GPU kernel 之后，EasyFHE 就能在多项式集合层次管理内存、在显存预算下选择 rotation keys，并在代数允许时合并 modulus-up、modulus-down、key switching 和 rescaling。读者真正该记住的是：高效 GPU FHE 需要一个带编译器风格的运行时后端，而不只是若干个更快的密码学 kernel。

## 设计

EasyFHE 的实现分成四层：最上层是 `padd`、`hmul`、`hrotate` 这类稳定的同态 primitive 接口；下面是依据密文状态选择具体实现的 primitive implementation；再往下是 modulus-up、modulus-down、inner product 等 polynomial arithmetic；最底层是 NTT、automorphism 和 element-wise 算术等可复用 GPU kernels。这样的层次化设计让新 FHE 技术通常只需要改中间层，而不必重写接口或 kernel。

内存模型是设计核心。EasyFHE 不把整个 ciphertext 或单个 polynomial 当成管理单位，而是使用中间粒度的 polynomial set，这样既能避免严重碎片，也不会因为临时三多项式状态而过度分配。框架还跟踪 scale、noise degree、slot 和 active polynomial count 等 metadata，并提供 plaintext-twin 调试模式，让密文执行能和同步维护的明文结果对比。

优化框架主要有三类 pass。内存占用优化针对真正的大对象：在显存预算下选择 rotation offsets，并对常量采用 hybrid encoding，让一部分常驻显存、一部分从 host 获取、另一部分按需编码。内存管理优化会预分配最大活跃中间变量所需空间、复用符号目标避免反复分配，并提前调度数据传输以与计算重叠。冗余消除则直接利用 FHE 结构：加法链可以共享一次 key switching 和 rescaling，多 offset 旋转可以 hoist 共享的 modulus-up，编码常量也会在第一次生成后缓存。

## 实验评估

实验覆盖 `RTX4090`、`RTX A6000` 和 `H100 PCIe`，工作负载既有 dot product、bootstrapping、sorting 这类基础程序，也有加密 logistic regression 训练和 ResNet-20/110 推理。这个组合比较合适，因为它能同时检验密码学算子和运行时支持层。

相对 Troy 和 HEonGPU，EasyFHE 报告平均 `2.88x`、最高 `4.39x` 的端到端加速，而且复杂 workload 上的收益更大，这和论文的中心论点是一致的。内存结果也很关键：ResNet 这类工作负载会让小显存 GPU 上的基线直接失败，但 EasyFHE 仍然能通过减少 key 与 constant 内存占用并自动管理传输把程序跑起来。在 H100 上施加显式显存上限时，它在 `10 GB` 配置下比一个“optimal replacement”基线快 `2.18x`。

消融实验同样支撑机制解释。内存管理优化平均贡献 `1.48x` 加速，冗余消除平均贡献 `1.44x`，并且在带宽和容量更紧的低端 GPU 上更明显。论文还强调，EasyFHE 的提升并不是因为它用了最激进的 GPU kernel；相反，它复用了 over100x 的 kernels，并保持与 OpenFHE 风格算法兼容，所以主要收益确实来自框架组织方式。

## 创新性与影响

和 _Ebel et al. (ASPLOS '25)_ 相比，EasyFHE 处理的不是前端编译，而是 homomorphic primitives 已经确定之后如何高效映射到 GPU。和 _Jung et al. (TCHES '21)_ 相比，它也不只是更好的 bootstrapping kernel，而是面向整程序的运行时支持。和 _Fan et al. (HPCA '25)_ 相比，它最独特的地方是把 FHE 执行视为一个分层后端问题，而不只是 kernel 吞吐问题。

因此，这篇论文同时对实践者和系统研究者有价值。它降低了在 GPU 上写完整 FHE 应用的门槛，也很有力地说明：端到端 FHE 性能现在同样受制于内存和 lowering 决策，而不只是算术速度。

## 局限性

框架的实验基本都围绕 CKKS 风格 workload 展开，虽然作者认为这种结构也可以推广到更广泛的 RLWE 方案。它的 kernel 层也刻意比较保守：EasyFHE 使用 64-bit arithmetic，没有集成 on-the-fly rotation-key generation，也没有纳入最新库里最激进的 fusion 或 rescaling 技术。这样做换来了与 OpenFHE 风格算法的兼容性，但也意味着部分性能空间还没被吃干净。

这些内存优化本身也带有空间换时间的取舍。粗粒度 polynomial-set 分配能减少 allocation churn，但会故意浪费一部分显存。与此同时，论文范围基本停留在单机单节点 GPU，没有回答多 GPU、分布式 key 管理或服务化部署的问题。

## 相关工作

- _Ebel et al. (ASPLOS '25)_ — Orion 是把 ML 程序编译成 FHE primitive 序列的前端，而 EasyFHE 从这些 primitive 出发继续优化 GPU 后端。
- _Jung et al. (TCHES '21)_ — over100x 专注于 GPU 上的 bootstrapping kernel 加速，而 EasyFHE 把内存感知和冗余消除扩展到完整 FHE 应用。
- _Liu et al. (ASPLOS '25)_ — ReSBM 关注前端的 bootstrapping 放置与 level 管理，EasyFHE 则关注这些决策之后的运行时 lowering 与执行。
- _Fan et al. (HPCA '25)_ — WarpDrive 更进一步推动 GPU FHE kernel 吞吐，而 EasyFHE 强调应用级收益还需要自动内存管理和跨操作优化。

## 我的笔记

<!-- 留空；由人工补充 -->
