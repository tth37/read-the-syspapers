---
title: "T-MAC: CPU Renaissance via Table Lookup for Low-Bit LLM Deployment on Edge"
oneline: "T-MAC 把低比特权重乘法改写成按位查表，让 CPU 直接执行 W1-W4 与高精度激活的混精度计算，不再被反量化开销拖慢。"
authors:
  - "Jianyu Wei"
  - "Shijie Cao"
  - "Ting Cao"
  - "Lingxiao Ma"
  - "Lei Wang"
  - "Yanyong Zhang"
  - "Mao Yang"
affiliations:
  - "USTC / Microsoft Research"
  - "Microsoft Research"
  - "UCAS / Microsoft Research"
  - "USTC"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696099"
code_url: "https://github.com/microsoft/T-MAC"
tags:
  - llm-inference
  - compilers
  - energy
  - hardware
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

T-MAC 的出发点很直接：低比特边缘 LLM 之所以常常没变快，不是模型压得不够，而是现有栈通常先把低比特权重反量化回硬件熟悉的格式，再去做普通 matmul。它把 W1-W4 权重拆成多个 1-bit 平面，为当前激活预先生成小查找表，把混精度 GEMV/GEMM 变成查表加累加。论文报告相对 `llama.cpp` 的 kernel 加速最高 6.6x，端到端吞吐最高 2.8x。

## 问题背景

这篇论文面对的是很现实的边缘推理场景。设备侧部署 LLM 需要小内存、低延迟和低功耗，因此权重量化几乎是必选项。可一旦权重降到 4-bit、3-bit、2-bit 甚至 1-bit，而激活仍保留在 `int8` 或 `fp16`，计算就会变成 `WnA16` 或 `WnA8` 这类混精度 GEMV/GEMM。问题在于，通用 CPU、GPU、NPU 并没有一个原生、通用的这类指令接口，所以现有系统只能先把权重 decode 或 dequantize 回受支持的数据类型，再调用常规 kernel。这样一来，低比特模型本该得到的收益就被吃掉了。论文展示，baseline 从 4-bit 降到 3-bit 或 2-bit 时并不会线性提速，有些情况甚至更慢，因为权重解码已经成了主要开销。作者真正要解决的，就是怎样直接执行低比特 mixed-precision kernel，而且位宽越低收益越明显。

## 核心洞察

论文最重要的判断是：这类低比特 mixed-precision matmul 不该继续按「数据类型」来想，而该按「比特位」来想。把 `n`-bit 权重矩阵拆成 `n` 个 1-bit 矩阵之后，`A × W` 就能写成若干个 `A × Wi` 的加权求和。对每个 `Wi` 来说，权重只剩 bit pattern；如果按 `g` 个 bit 分组，每组只有 `2^g` 种可能。T-MAC 先把一段激活与这 `2^g` 种模式的结果一次性预计算出来，存进很小的查找表，执行时就不再做乘法，而是直接查表加累加。这样一来，不同位宽会落到同一条 bit-serial 执行路径上，开销也会随着权重 bit 数近似线性变化。更关键的是，只要表能放进最快的片上存储并行访问，查表就可能比反量化再乘更合算。

## 设计

T-MAC 分成离线和在线两部分。离线阶段先把量化后的权重按 bit-plane 拆开，再把每 `g` 个 bit 打包成一个索引。在线阶段则针对当前激活块生成查找表，表里保存这段激活与全部 `2^g` 种 bit pattern 的带符号求和结果。论文选择 `g = 4`，因为这样整张表刚好能塞进一条 NEON 或 AVX2 寄存器。真正执行时，每个 packed weight group 都只是一个查表索引，不同 bit-plane 的部分和最后再按 bit-serial 的缩放系数与偏置纠正组合起来。

真正让它可用的是围绕查找表重做的数据布局。T-MAC 把循环顺序改成先走归约维度 `K`，这样只需要为当前激活切片维护一张小表；再通过 tiling 让同一张表被更多输出列复用。为了压低随机访问代价，系统把表放进寄存器，并直接使用 ARM 的 `TBL` 和 x86 的 `PSHUF` 做 lookup。与此同时，weight permutation 让 DRAM 访问更连续，weight interleaving 降低 unpack 重排开销，mirror consolidation 利用正负对称性把显式存储的表项减半，table quantization 再把表压成带缩放因子的 `int8`。实现上，作者用 TVM/LLVM 生成代码，再把生成出的 C++ kernel 嵌进 `llama.cpp`。

## 实验评估

实验覆盖了论文的核心主张。作者从 Llama-2-7B 和 Llama-2-13B 里抽取真实 kernel 形状，在 Apple M2 Ultra、Raspberry Pi 5、Jetson AGX Orin、Surface Book 3 上做 benchmark，再把 T-MAC 集成进 `llama.cpp`，用低比特 Llama 和 BitNet 做端到端评测。baseline 也够强：既有各平台上优化过的 `llama.cpp` kernel，也有 mpGEMM 场景下的 BLAS 对照。

kernel 级结果很干净。`llama.cpp` 因为要先 decode 权重，位宽降下去之后收益很快被抵消；T-MAC 则几乎随着 bit 数减少而线性提速。单线程 mpGEMV 相对 `llama.cpp` 的最大加速分别达到 11.2x、5.8x、4.7x、3.1x，对应 1-bit、2-bit、3-bit、4-bit；论文整体总结的 kernel 提升最高是 6.6x。端到端上，把 T-MAC 接进 `llama.cpp` 后，Llama-2-7B-2bit 的 token 生成吞吐最高提升 2.8x；BitNet-b1.58-3B 在 M2 Ultra 上单核可到 30 tokens/s、八核到 71 tokens/s，在 Raspberry Pi 5 上也还有 11 tokens/s。M2 Ultra 上，不同模型的能耗下降区间是 20.6% 到 61.2%。在一些 2-bit 模型上，CPU 加 T-MAC 和同设备 GPU、NPU 相比也能打，因为 decode 阶段本来就偏 memory-bound，而 T-MAC 直接把反量化路径去掉了。主要保留意见是端到端栈仍绑定在 `llama.cpp` 上。

## 创新性与影响

T-MAC 的新意不在于量化本身，而在于量化之后怎么执行。和 GPTQ、AWQ、BitDistiller、BitNet 这类工作相比，它补上的是系统层缺口：怎样让 W1-W4 权重在通用边缘 CPU 上真的跑得更快。和 DeepGEMM 这类更早的 LUT 路线相比，T-MAC 把 lookup 方法专门改造成适合 LLM 非对称 mixed precision 的形式，又把布局、压缩和寄存器级执行一起围绕 CPU 的 byte-shuffle 指令重新组织。它的意义在于重新证明 CPU 仍然是严肃的边缘 LLM 目标平台，也提示未来低比特 LLM 加速器可能同样需要高效 LUT 访问。

## 局限性

T-MAC 最强的仍然是 decode 一侧、也就是 memory-bound 更明显的阶段。多线程结果虽然不错，但提升没有单线程那么夸张，因为带宽很快就成了瓶颈；而在 M2 Ultra 上，AMX 也会缩小它在 mpGEMM 上的优势。另外，这套设计明显依赖底层 ISA 特性：需要足够快的 byte-shuffle 指令、足够多的寄存器去常驻查找表，以及离线调好的 tiling、permutation、interleaving。查找表大小仍然会随 group size 指数增长，所以作者最后固定在 `g = 4`。还有一点不能忽略：虽然 table quantization 基本不伤精度，但 fast aggregation 会实打实地拉高 perplexity、降低下游任务表现。

## 相关工作

- _Dettmers et al. (NeurIPS '22)_ - LLM.int8() 通过隔离 outlier channel 让 8-bit Transformer 推理可用，而 T-MAC 处理的是更低的权重位宽，并把反量化从执行路径里拿掉。
- _Ganji et al. (CVPR '23)_ - DeepGEMM 同样用 LUT 取代低精度乘法，但面向的是量化 CNN 一类工作负载；T-MAC 把 LUT 路线改造成适合 `WnA16`、`WnA8` 这类 LLM mixed-precision kernel 的形式。
- _Du et al. (arXiv '24)_ - BitDistiller 说明 2-bit Llama 仍能保住质量，而 T-MAC 提供的是把这类模型真正部署到边缘 CPU 上的 kernel 路径。

## 我的笔记

<!-- 留空；由人工补充 -->
