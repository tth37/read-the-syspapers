---
title: "QiMeng-Xpiler: Transcompiling Tensor Programs for Deep Learning Systems with a Neural-Symbolic Approach"
oneline: "QiMeng-Xpiler 先用 LLM 生成跨平台张量内核骨架，再用 SMT 修补低层错误，并用分层 auto-tuning 搜索 pass 参数与顺序。"
authors:
  - "Shouyang Dong"
  - "Yuanbo Wen"
  - "Jun Bi"
  - "Di Huang"
  - "Jiaming Guo"
  - "Jianxing Xu"
  - "Ruibai Xu"
  - "Xinkai Song"
  - "Yifan Hao"
  - "Ling Li"
  - "Xuehai Zhou"
  - "Tianshi Chen"
  - "Qi Guo"
  - "Yunji Chen"
affiliations:
  - "University of Science and Technology of China"
  - "Cambricon Technologies"
  - "SKL of Processors, Institute of Computing Technology, Chinese Academy of Sciences"
  - "Institute of Software, Chinese Academy of Sciences"
  - "University of Chinese Academy of Sciences"
conference: osdi-2025
tags:
  - compilers
  - ml-systems
  - gpu
  - hardware
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

QiMeng-Xpiler 不把张量内核移植当成一次性的大翻译，而是拆成一串小粒度的 source-to-source rewrite。LLM 负责为每个 pass 生成程序骨架，局部 SMT 修复负责补齐在单元测试后暴露出来的低层错误，分层 auto-tuning 再去搜索性能更好的 pass 配置。

## 问题背景

这篇论文要解决的是异构深度学习系统中的一个真实编译器缺口。NVIDIA GPU、AMD MI、Cambricon MLU 和 Intel DL Boost CPU 都有各自的低层编程语言，而且它们在并行模型、内存层次和专用指令上差异很大。开发者即使已经有一份可工作的 CUDA kernel，想支持 HIP、BANG C 或 VNNI intrinsic，仍然要重新手工移植。问题在于，张量程序不是单纯的算术表达式，它还把 thread binding、scratchpad 放置方式、以及架构特定指令都写死在代码里。

现有路线各有明显短板。HIPIFY、PPCG 这类 rule-based transcompiler 需要大量专家手写规则，而且很难跨越截然不同的硬件模型。纯 symbolic synthesis 在语义保持上更强，但一旦面对真实 tensor kernel，尤其是涉及并行语义和 memory placement 时，搜索空间就会失控。纯 LLM 翻译则更容易扩展，但论文给出的数据说明它远远不够可靠：在 CUDA 到 BANG 的方向上，GPT-4 zero-shot 的编译错误率是 100%，few-shot 虽然能编过一部分代码，但 computation error 仍高达 92.3%。

因此，作者想解决的核心矛盾很明确：如果系统研究者真的想让低层 tensor program 接近“write once, run anywhere”，就必须同时避开手写规则的高人工成本，以及单次 LLM 翻译的不可靠性。

## 核心洞察

论文的核心命题是，只有把“高层结构生成”和“低层语义修复”拆开，端到端 transcompilation 才会变得可做。QiMeng-Xpiler 让 LLM 去做它相对擅长的部分：在一个定义明确、范围受限的 transformation pass 中，结合检索到的 manual 片段和 pass-specific prompt，生成一个大体合理的程序骨架。随后再把 symbolic reasoning 收缩到一个更小的问题上，只修复那些具体数值、索引表达式或 tensor intrinsic 参数上的残余错误。

这种拆分同时服务于正确性和性能。因为每个 pass 只改程序的一小部分，所以单元测试和 buffer-level 比对就能把错误定位到具体代码区域；SMT 只需要处理 loop bound、index expression 或 intrinsic parameter，而不必从零合成整个 kernel。另一方面，性能优化也被改写成“搜索 pass 参数和 pass 顺序”的问题，而不是指望 LLM 一步猜出全局最优实现。

## 设计

QiMeng-Xpiler 暴露了 11 个 transformation pass，并分成三类。第一类是 sequentialization / parallelization，包括 Loop Recovery、Loop Bind、Loop Split、Loop Fuse、Loop Reorder、Loop Expansion 和 Loop Contraction，用来改写循环结构和线程绑定。第二类是 memory conversion，例如 Cache 和 Pipeline，用来适配目标平台的内存层次。第三类是 Tensorize / Detensorize，把标量代码映射成专用 intrinsic，或者把 intrinsic 还原为更便于继续改写的标量结构。作者的论点是，这三类 pass 足以覆盖四类 DLS 之间最主要的可移植性鸿沟。

每个 pass 都遵循同一套 neural-symbolic 工作流。第一步是 program annotation：先由 LLM 识别源程序里的计算语义，例如 matmul，再通过 BM25 在目标平台 programming manual 中检索相关 intrinsic、memory-space 约束和示例，最后把这些参考信息重新标注回程序。第二步是 meta-prompt based transformation。每个 pass 都有自己的 prompt 模板，里面包含平台无关的 rewrite 描述、来自目标 manual 的平台特定示例，以及可选的 tuning knob，例如候选 split size 或 loop order。

正确性主要来自 pass 后的 repair 路径。每次变换后，QiMeng-Xpiler 都先跑 unit test；若失败，就通过对中间 buffer 做二分定位，找出第一个值不匹配的 buffer，再把对应错误映射回变换后的 AST，并将错误分成两类：index error 和 tensor-instruction error。前者用 SMT 约束 loop bound 与 access expression 来修复，后者则抽取出对应的标量逻辑，再调用 Tenspiler 合成等价的 tensorized 片段，最后把修复结果 stitch 回程序中。

性能优化被拆成两层。Intra-pass auto-tuning 负责枚举局部参数，例如 block size、loop split、loop order 和 binding，在搜索空间足够小时直接 brute force。Inter-pass auto-tuning 则把整个翻译过程建模成一个 Markov decision process，用 MCTS 搜索 pass sequence，以真实执行吞吐作为 reward，凡是 test 失败的候选都记为零奖励。实现上，系统大约包含 35k 行 Python，并配套了约 38k 行测试内核，覆盖 CUDA、HIP、BANG C 和 VNNI。

## 实验评估

这篇论文的评估范围足够广，能够支持其主要 systems claim，但还算不上对端到端等价性的完全形式化证明。作者在四个平台上评测了 21 个算子、每个算子 8 个真实模型 shape，总计 168 个 benchmark case。算子类型覆盖 matmul、convolution、activation、pooling、elementwise，以及更贴近大模型工作负载的 LayerNorm、Self Attention、RMSNorm 和 Deformable Attention。

在准确性上，QiMeng-Xpiler 明显优于各类 baseline。跨不同方向，它达到接近 100% 的 compilation accuracy，以及 86.9% 到 100% 的 computation accuracy。对最有代表性也最困难的 CUDA C 到 BANG C 方向，它实现了 100% compilation accuracy 和 91.7% computation accuracy；相比之下，OpenAI o1 few-shot 只有 51.8% 和 48.2%。在较容易的 CUDA C 到 HIP 方向上，它在两项指标上都达到 100%，也明显优于 HIPIFY 的 85.7%。论文里的 ablation 很关键：一旦移除 SMT，准确性就会出现明显缺口，例如 CUDA C 到 BANG C 的 computation accuracy 只剩 54.2%，HIP 到 BANG C 只剩 52.4%。这直接支持了作者的中心论点，即 LLM 引导本身并不足以构成可靠 transcompiler。

性能方面，结果是“可用但还没追平专家手写内核”。在四个常见 transcompilation 方向上，生成程序平均达到 cuDNN、cuBLAS、oneDNN、CNNL 和 rocBLAS 等 vendor-tuned library 的 0.78x。FlashAttention case study 更能说明问题：QiMeng-Xpiler 只能达到 vendor implementation 的 0.61x 到 0.81x，说明它仍然抓不住最深层的 shared-memory tiling、pipeline 和数据搬运技巧。编译代价也不低，6 个代表性 CUDA 到 BANG 算子的编译时间在 1.2 到 7.8 小时之间，平均 3.7 小时。相比之下，生产力 case study 更乐观：在大约 200 行的 Deformable Attention kernel 上，junior coder 的时间节省可达 96.0x（CUDA 到 BANG）和 34.3x（VNNI 到 CUDA）。

## 创新性与影响

相对于 _Qiu et al. (ECOOP '24)_，QiMeng-Xpiler 并不试图让 symbolic synthesis 本身成为完整编译器，而是把 Tenspiler 当成一个局部 repair backend 嵌入更大的 transcompilation pipeline。相对于 _Bhatia et al. (ECOOP '23)_，它不要求开发者先写出每种语言的完整语义规格，而是依赖 manual 检索、pass-specific prompt 和局部修复。相对于 _Verdoolaege et al. (TACO '13)_ 或 HIPIFY 这类工具，它也不是只为某一对 source-target language 写一套固定规则。

因此，这篇论文的主要贡献不是“prompt 工程更好”，而是一种新的 compiler architecture。它最可能影响的是 accelerator compiler 团队，以及那些必须把低层 tensor kernel 在多家硬件之间移植的 ML systems 工程师，尤其是在“先把支持做出来”比“第一天就榨干最后 20% 性能”更重要的场景里。

## 局限性

论文并没有真正实现普适的正确性保证。最主要的失败模式是复杂控制流：像 Deformable Attention 这类内核包含多层循环和条件分支，会同时击穿 LLM 生成正确 SIMD intrinsic 的能力，以及 SMT 构造紧凑 repair constraint 的能力。作者还承认，GPT-4 对任意 special instruction 的理解仍然有限，这会在 annotation 阶段就埋下后续错误。

另外，论文在“correctness guarantee”的表述和实验验证之间仍然有距离。某个 pass 内部的 repair 可以借助 symbolic 方法校验，但端到端结果的 computation accuracy 仍然是靠 unit test 定义出来的，而不是完整的语义等价证明。对 systems 论文来说这并不奇怪，但更准确的解读应该是“比直接 LLM 翻译可信得多”，而不是“完整验证过的 transcompilation”。

最后，这套流程仍然偏重。编译耗时以小时计，性能仍落后于 vendor library，适配新 DLS 也仍需一次性的人工输入，例如线程数量提示、memory scope 提示、intrinsic 示例，或 Tenspiler backend 扩展。它显著减少了人工劳动，但并没有把硬件专家完全移出回路。

## 相关工作

- _Qiu et al. (ECOOP '24)_ — Tenspiler 在统一 IR 内合成并验证 tensor program，而 QiMeng-Xpiler 只把它用于更大 transcompiler 中的局部 tensor-intrinsic 修复。
- _Bhatia et al. (ECOOP '23)_ — MetaLift 依赖语义规格来构建 DSL transpiler，而 QiMeng-Xpiler 面向真实 vendor programming model，依赖 LLM-guided pass 和 SMT repair。
- _Ikarashi et al. (PLDI '22)_ — Exocompilation 改善的是人类如何编写 accelerator program，而不是自动把现有 tensor kernel 在不同硬件栈之间移植。
- _Bansal et al. (PLDI '23)_ — Mosaic 是面向 tensor algebra 的 interoperable compiler，而 QiMeng-Xpiler 关注的是已有低层 tensor 实现跨异构 DLS 语言的迁移。

## 我的笔记

<!-- 留空；由人工补充 -->
