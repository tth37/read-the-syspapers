---
title: "DARTH-PUM: A Hybrid Processing-Using-Memory Architecture"
oneline: "DARTH-PUM 把模拟 MVM 阵列与数字布尔 PUM 瓦片放到同一颗 ReRAM 芯片上，用协同数据流和移位累加支持把整段内核留在存内执行。"
authors:
  - "Ryan Wong"
  - "Ben Feinberg"
  - "Saugata Ghose"
affiliations:
  - "Univ. of Illinois Urbana-Champaign, Urbana, IL, USA"
  - "Sandia National Laboratories, Albuquerque, NM, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790151"
tags:
  - hardware
  - memory
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

DARTH-PUM 把负责高速矩阵向量乘的模拟 ReRAM 阵列，与负责移位累加、查表和控制密集阶段的数字布尔 PUM 流水线放进同一个混合瓦片里。它的关键创新不是再加一个专用单元，而是做出一套能让完整 kernel 留在存内执行的混合接口。这样一来，模拟 PUM 就不再只是一个狭义的 MVM 加速器。

## 问题背景

论文抓住的是模拟 PUM 的核心短板。模拟 crossbar 很擅长做大规模 MVM，但真实工作负载远不止这一种操作。CNN 还要做激活和池化，Transformer 还要做 softmax 与 normalization，AES 甚至大部分时间都花在查表、移位和 XOR 上。已有模拟 PUM 方案通常只能靠外挂专用 CMOS function units，或者频繁把非 MVM 阶段送回主机处理，两种做法都会削弱 PUM 原本依靠“少搬数据”获得的收益。

数字 PUM 则是另一端的极端。它更通用，也更不怕模拟噪声，但做矩阵类计算时明显慢于模拟 PUM。更麻烦的是，简单把两种阵列放在同一颗芯片上也不够，因为两边的数据布局与执行节奏天然不同：模拟阵列沿 bitline 吐出宽向量，数字 PUM 却要求 bit-striped 数据；再加上输入 bit-slicing，会产生很多 partial products，需要额外的移位、累加和临时寄存器管理。论文真正要解决的因此不是“能不能混合”，而是“怎样把两种域协同到足以让完整 kernel 留在存内执行”。

## 核心洞察

论文最重要的洞察是：混合 PUM 真正缺的不是更多应用专用单元，而是把模拟和数字域接起来的协调机制。如果让数字 PUM 成为模拟 PUM 的可编程后处理引擎，那么原本会把模拟加速器逼回 CPU 的 shift-add、S-box 查表、逐元素逻辑和一部分控制路径，就都能留在芯片内完成。DARTH-PUM 因而把重点放在数据重排、速率匹配和可变精度抽象上，而不是继续堆更多 SFU。

## 设计

DARTH-PUM 的基本构件是 hybrid compute tile（HCT）。每个 HCT 都有一个 analog compute element（ACE）和一个 digital compute element（DCE）：ACE 内含 64 个模拟 ReRAM 阵列，DCE 内含 64 条 RACER 风格的数字 PUM 流水线，再加上一组本地协调部件。芯片前端负责取指和译码，而瓦片内部负责把模拟执行与数字执行串起来。ACE 和 DCE 之间的数据网络配置为每周期 8B，目的是尽量让模拟输出带宽与数字写带宽对齐。

核心机制是：ACE 逐 bit 产生 MVM partial-product 向量，再交给 DCE 做 shift-and-add 规约。由于模拟结果沿 bitline 产生、数字 PUM 又要求 bit-striped 布局，DARTH-PUM 加入了 A/D transpose 单元和固定 shift 支持，负责把两边的数据形状接起来。为了避免长延迟模拟操作与短延迟布尔操作互相干扰，系统还增加了 analog-digital arbiter，让模拟操作在数字侧看起来是原子的；同时用 pipeline reserve 机制避免尚未消费完的临时向量被覆盖。

为了不让前端在大量布尔微操作上堵死，论文还设计了 instruction injection unit，在瓦片本地展开重复出现的 shift-add 序列。针对可变位宽，DARTH-PUM 提出 `vACore` 抽象，把多个模拟阵列逻辑上捆成更宽的虚拟模拟核，并自动配置对应的规约序列。数字侧新增的 element-wise load/store 则让 AES `SubBytes` 这样的按元素查表操作可以直接在邻近流水线中完成。

论文还考虑了模拟误差。以 AES 为例，作者把原本严格为正的矩阵 remap 成差分 `-1/+1` 表示，以减少 IR drop 误差，再在数字 PUM 中施加补偿因子。这个例子说明，数字侧不仅负责逻辑后处理，也承担了廉价误差修正的角色。

## 实验评估

实验把修改过的数字 PUM 模拟器、CrossSim 和 MILO 噪声模型结合起来。DARTH-PUM 在等面积条件下对比模拟 PUM 加 CPU 的 Baseline、纯 DigitalPUM、若干应用专用加速器，以及 RTX 4090 GPU。使用 SAR ADC 时，模型中的 DARTH-PUM 可以在 CPU 面积预算内放下 1860 个 HCT，总容量约 4.1 GB。

总体结果很强。相对模拟 PUM 加 CPU 的 Baseline，DARTH-PUM 在 AES、ResNet-20 推理和 LLM encoder 上分别获得 `59.4x`、`14.8x` 和 `40.8x` 的吞吐提升，几何平均为 `31.4x`；对应的能耗收益分别是 `39.6x`、`51.2x` 和 `110.7x`，平均达到 `66.8x`。相对纯 DigitalPUM，它还能把平均能耗再降约 `2.0x`，说明模拟 MVM 确实显著缩短了矩阵阶段原本需要的长布尔运算链。

分 workload 看，论文给出的解释也成立。对 AES，DARTH-PUM 比应用专用对照还快 `36.9x`，因为它用模拟 PUM 加速 `MixColumns`，同时把 `SubBytes`、`ShiftRows` 和 `AddRoundKey` 留在数字 PUM 中完成，避免主机往返。对 ResNet-20，它虽然没有任何 CNN 专用 SFU，但与专用加速器相比只差 `26.2%`，且相对 Baseline 把推理延迟降了 `40.0%`。对 LLM encoder，DARTH-PUM 仍落后于最专门化的方案，因为还有 `71%` 的执行时间耗在非 MVM 阶段，但相对 Baseline 仍能取得 `45.6x` 的收益。我认为这足以支撑论文的核心主张：混合接口确实改变了系统瓶颈，即使它还没有抹平专用 datapath 的全部优势。

## 创新性与影响

相对 _Truong et al. (MICRO '21)_，DARTH-PUM 的新意不在数字布尔 PUM 本身，而在于把数字流水线重新定义成模拟阵列的可编程伙伴。相对 _Shafiee et al. (ISCA '16)_，它拒绝继续沿着“为不同 workload 追加专用后处理硬件”的路线走下去。它更大的贡献，是把混合接口做成可复用机制，让同一套瓦片组织同时覆盖 AES、CNN 和 LLM encoder。因而这篇论文更像是在提出一种端到端 in-memory execution 的架构模式，而不只是某个 benchmark 的一次提速。

## 局限性

DARTH-PUM 仍是一篇以建模和仿真为主的论文，而不是硅实现结果，因此很多结论依赖器件、外设和系统模型的准确性。可靠性故事也还不完整。论文虽然报告 ResNet-20 on CIFAR-10 的端到端精度保持在 `75.4%`，与基线一致，但对更全面的 chip-level variation、drift、stuck-at faults 和制造计量数据，作者都明确留到未来工作。

架构本身也有边界。部分 Transformer 操作需要动态更新矩阵，因此仍必须留在数字 PUM，这也是它在 LLM encoder 上落后于专用设计的关键原因。单个瓦片内所有活跃 `vACore` 必须共享同一位宽，也限制了 mixed-precision 的灵活性。换句话说，DARTH-PUM 用额外的协调结构和数字容量换掉了应用专用 SFU；对多样 workload 这很划算，但对单一算法家族未必始终是最优点。

## 相关工作

- _Truong et al. (MICRO '21)_ — RACER 提供了比特流水化数字 PUM 的基础，而 DARTH-PUM 把这类流水线转化为模拟 MVM 阵列的可编程后处理与控制伙伴。
- _Shafiee et al. (ISCA '16)_ — ISAAC 展示了模拟 ReRAM MVM 的高效率，但 DARTH-PUM 的区别在于把非 MVM 支持尽量放到邻近数字 PUM 中，而不是依赖按工作负载定制的模拟外设和 SFU。
- _Yazdanbakhsh et al. (MICRO '22)_ — SPRINT 面向 Transformer 一类模型做 in-memory 加速，而 DARTH-PUM 追求的是可复用的混合接口，希望同一架构同时覆盖 AES、CNN 和 LLM encoder。
- _Truong et al. (HPCA '26)_ — The Memory Processing Unit 从接口层面推进端到端 in-memory execution，DARTH-PUM 则从具体瓦片组织上展示这种执行模式如何落到混合模拟/数字 PUM 硬件里。

## 我的笔记

<!-- 留空；由人工补充 -->
