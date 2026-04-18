---
title: "ZipServ: Fast and Memory-Efficient LLM Inference with Hardware-Aware Lossless Compression"
oneline: "ZipServ 把 BF16 权重压成适配 Tensor Core 的定长格式，并将解压与 GEMM 融合，让无损 LLM serving 同时省内存和加速 decode。"
authors:
  - "Ruibo Fan"
  - "Xiangrui Yu"
  - "Xinglin Pan"
  - "Zeyu Li"
  - "Weile Luo"
  - "Qiang Wang"
  - "Wei Wang"
  - "Xiaowen Chu"
affiliations:
  - "The Hong Kong University of Science and Technology (Guangzhou), Guangzhou, China"
  - "Harbin Institute of Technology, Shenzhen, Shenzhen, China"
  - "The Hong Kong University of Science and Technology, Hong Kong, Hong Kong SAR"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790250"
code_url: "https://github.com/HPMLL/ZipServ_ASPLOS26.git"
tags:
  - llm-inference
  - gpu
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

ZipServ 的核心观点是：无损压缩想在 LLM serving 里真正带来收益，压缩格式必须顺着 GPU 的执行方式来设计。它用定长的 `TCA-TBE` 取代变长熵编码，并在 decode 阶段用融合式 `ZipGEMM` 直接把权重还原到 Tensor Core 寄存器里。论文报告最多可减少 `30%` 模型体积、在 kernel 层面相对 cuBLAS 获得 `2.21x` 加速，并在端到端上平均比 vLLM 快 `1.22x`。

## 问题背景

这篇论文切入的是一个很现实的矛盾：推理系统希望保留 bit-exact 权重，因为激进的有损压缩确实可能伤害模型质量，尤其是在长上下文或可靠性要求更高的场景里；但现有无损压缩大多只适合做 checkpoint、存储或训练通信，一旦放进在线推理链路，解压开销往往会把“少读一些字节”带来的好处吃掉。

ZipServ 认为，这不是无损压缩天然太慢，而是传统 codec 和 GPU 架构根本不匹配。像 Huffman 或 ANS 这样的变长编码会生成长度不一的 bitstream，不同 warp lane 需要解析不同数量的位、走不同的控制流，于是出现分支发散、同步等待和不规则访存。论文给出了直接测量：在 L40S 上，DietGPU 和 DFloat11 的解压只达到峰值带宽的 `43.7%` 和 `76.5%`。系统层面还有第二个问题。很多方案先把整块权重完全解压到 global memory，再启动 GEMM，这样压缩读、解压写、后续计算读都要付一次代价。论文的 roofline 分析显示，对一个代表性的 `4096 x 4096` 权重矩阵，这种 decoupled pipeline 相比标准 GEMM 会把 compute intensity 拉低大约 `62%`。也就是说，旧方案确实省了容量，却在性能上回吐了太多。

## 核心洞察

论文最重要的观察是，现代 LLM 的 BF16 权重其实有足够强的结构性，可以支持一种对 GPU 友好的无损格式。作者发现 exponent 字段高度偏斜：top-7 exponent 覆盖超过 `95%` 的权重，而且在 `99.6%` 的矩阵里，这七个最常见 exponent 还是数值上连续的一段窗口。于是 ZipServ 不必使用通用熵编码器，而可以把大多数权重表示成“一个 base exponent 加一个很小的 offset”，再留一个 fallback 状态给少数离群值；这样解码路径就能在 warp 内保持规整。

但这个统计性质只有在系统把它用对地方时才会转化成收益。ZipServ 的真正命题是：只有把解压直接并入 decode 阶段的 GEMM 数据路径，存储节省才会变成 serving 加速。如果权重以压缩形态从 DRAM 读入，并且只在 Tensor Core warp 真正消费它们的那一刻才被还原，就能消掉之前那个拖后腿的中间 buffer。于是这篇论文不是把“压缩格式”和“推理 kernel”分成两个独立优化，而是把它们当作同一个联合设计问题。

## 设计

ZipServ 由离线压缩器和在线推理引擎两部分组成。离线阶段，它先统计每个权重矩阵的 exponent 直方图，找出覆盖率最好的连续 7-exponent 窗口，并记录 `BaseExp = min(window) - 1`。随后它把矩阵切成 `8 x 8` 小 tile，并用 `TCA-TBE`（Tensor-Core-Aware Triple Bitmap Encoding）编码。每个元素都有一个 3-bit 状态：`001` 到 `111` 表示七个高频 exponent 之一，`000` 表示 fallback 的完整 BF16。落在高频窗口内的元素只保存 sign 和 mantissa；不在窗口里的离群值则进入 full-value buffer。

真正关键的不只是“每个元素 3 bit”，而是这些 bit 怎么排布。ZipServ 没有把 codeword 挤成一个致密 bitstream，而是把每个 `8 x 8` tile 拆成三张独立的 64-bit bitmap，每张对应一个 bit-plane。这样做带来两个直接好处：访存天然对齐，而且所有线程都能走同一条、无分支的解码路径。整个数据布局还专门贴合 Tensor Core：`8 x 8` 的 `FragTile` 组成 `16 x 16` 的 `TensorCoreTile`，再组成 `64 x 64` 的 block tile。由于压缩后的排布已经对齐 `mma.sync` 期望的寄存器布局，运行时就不必再做额外 reshuffle。

decode 阶段的核心 kernel `ZipGEMM` 把四件事串成一条流水线：把压缩权重 tile 和激活搬进 shared memory、在 warp 内做局部解压、把激活转到寄存器、然后启动 Tensor Core 矩阵乘。解压器本身也很干净。第一步，把三张 bitmap 做 OR，得到一个 spatial indicator，让每个 lane 知道自己负责的两个元素来自高频 buffer 还是 fallback buffer。第二步，用 `popc` 风格的前缀计数动态算地址，因此不需要显式的逐元素索引。第三步，用 `BaseExp + code` 的算术重建 exponent，避免查表。最终得到的 BF16 值会被直接打包进 Tensor Core 消费的 `bf16x2` 寄存器。

ZipServ 还有一个很务实的 stage-aware 策略。decode 阶段的 GEMM 往往是 memory-bound，因此使用“load-compressed, compute-decompressed”的融合路径最划算；prefill 阶段则因为 `N` 很大而更接近 compute-bound，这时系统退回到 decoupled 路径：先解压，再调 cuBLAS。论文报告在 `N = 8192` 和 `16384` 时，这个 prefill 路径只相当于额外付出约 `4%` 和 `2%` 的 GEMM 时间。整个原型大约 `3.5K` 行代码，通过自定义 CUDA/C++ backend 和少量 Python glue 接入 vLLM。

## 实验评估

实验最有说服力的地方，在于它主要覆盖了论文最想服务的那类平台：消费级和推理优化 GPU。kernel 实验选取了 LLaMA3.1、Qwen2.5、Gemma3、Mistral 中具有代表性的线性层，在 RTX4090 和 L40S 上测试，并额外在 RTX5090 上验证前向兼容性。相对 cuBLAS 的 Tensor Core GEMM，`ZipGEMM` 在 RTX4090 上平均加速 `1.31x`，在 L40S 上平均加速 `1.36x`，峰值分别达到 `1.71x` 和 `2.21x`。其他无损方案则明显落后：DietGPU、nvCOMP 和 DFloat11 相对原生 cuBLAS 都是减速，而不是加速。

微观分析解释了为什么融合式方案能赢。在一个 RTX4090 案例里，ZipServ 用更多整数指令换来 `29.3%` 的 DRAM read 降幅，同时仍保持了相当于 cuBLAS 基线 `71.6%` 的 Tensor Core 利用率。单看解压 kernel，本身也不弱：对完整 Transformer block 的权重解压，它平均比 DietGPU、nvCOMP 和 DFloat11 快 `2.14x`、`1.83x` 和 `1.10x`。这一点很重要，因为它说明不是只有“融合后碰巧更快”，而是 `TCA-TBE` 这个格式本身就确实更适合 SIMT。

端到端结果才是论文主张是否成立的关键证据。在 LLaMA3.1-8B、Mistral-24B 和 LLaMA3.1-70B 上，ZipServ 相比 vLLM 平均降低 `17.60%` 延迟、提升 `1.22x` 吞吐；在 LLaMA3.1-8B、batch size `32`、输出 `2048` token 的设置下，吞吐达到 `1105` tokens/s，相当于 vLLM 的 `1.66x`。权重存储则从 `14.96/43.92/131.56 GB` 降到 `10.83/31.30/93.52 GB`，释放出的显存还能让 KV cache 变大。论文给出的 breakdown 也很扎实：在 LLaMA3.1-8B 上，线性层总时间从 `24.99 ms` 降到 `14.76 ms`，KV cache 容量从 `5.07 GB` 提高到 `8.60 GB`。这些数据基本支撑了论文的中心论点：它不是只把模型“存得更小”，而是真的把 decode 路径加快了。

## 创新性与影响

和 _Yubeaton et al. (arXiv '25)_ 相比，ZipServ 的贡献不只是再做一个 lossless codec，而是把 codec 的定长结构、GPU warp 的执行规律，以及 Tensor Core 的 tile 布局一起考虑。和 _Dao et al. (NeurIPS '22)_ 相比，它继承的是 FlashAttention 那种“尽量别把中间结果再写回慢内存”的系统思路，只不过应用位置不同：ZipServ 融合的是解压与 GEMM，而不是 attention 内部的数据流。和 _Kwon et al. (SOSP '23)_ 相比，PagedAttention/vLLM 解决的是连续 serving 与 KV-cache 管理，ZipServ 则更像它下面的一层 backend，把权重 footprint 和 decode kernel 一起优化掉。

因此这篇论文最可能影响两类人。一类是做生产级 LLM serving 的工程师，他们会把它看成一种适合 bit-exact 部署的新后端。另一类是系统与体系结构研究者，他们会把它当成一个信号：无损压缩并不是只能做“存储层面的节省”，只要 codec、内存布局和 accelerator kernel 一起设计，就能重新变成性能优化手段。

## 局限性

这套方案并不是处处都赢。论文明确承认，ZipServ 主要面向消费级和推理优化 GPU；在 A100、H800 这类训练型数据中心 GPU 上，融合 kernel 不一定总能超过 cuBLAS，因为那里的内存带宽瓶颈更弱，而 ALU 密集的解压计算更难被完全隐藏。压缩率本身也相对克制，大致是 `30%` 左右，而不是有损量化那种更激进的位宽下降。

另外还有几个更细的限制。某些小层不好调优，论文就报告了一个 `O_proj` 场景只有 cuBLAS `0.79x` 的表现。prefill 仍然走“先解压再 GEMM”的两段式路径，所以真正完全融合的收益主要集中在 decode。最后，有一组 baseline 对比不像其他部分那样扎实：由于拿不到 DFloat11 的压缩代码，作者对部分形状只能通过整块测量后线性缩放来估算。这不会推翻整体趋势，但确实让那一项 head-to-head 的说服力略弱于 cuBLAS 或 vLLM 对比。

## 相关工作

- _Kwon et al. (SOSP '23)_ — PagedAttention/vLLM 解决连续 LLM serving 与 KV-cache 内存管理，ZipServ 则优化其底层的权重表示与 GEMM 路径。
- _Dao et al. (NeurIPS '22)_ — FlashAttention 通过融合和片上 tiling 减少 attention 的 IO；ZipServ 把同样的 IO-first 思路用于无损权重解压与 GEMM。
- _Frantar et al. (PPoPP '25)_ — MARLIN 展示了硬件感知 kernel 如何隐藏低比特推理开销，但它是有损量化设计，而 ZipServ 追求的是 bit-exact 的 BF16 权重。

## 我的笔记

<!-- 留空；由人工补充 -->
