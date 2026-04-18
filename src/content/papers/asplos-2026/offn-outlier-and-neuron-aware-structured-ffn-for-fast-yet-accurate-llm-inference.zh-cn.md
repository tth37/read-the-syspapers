---
title: "oFFN: Outlier and Neuron-aware Structured FFN for Fast yet Accurate LLM Inference"
oneline: "oFFN 利用稳定 outlier 维度与 hot/cold neuron 的重排，把 FFN 稀疏预测做得更准，并把不同区域映射到最合适的 GPU 执行路径。"
authors:
  - "Geunsoo Song"
  - "Hoeseok Yang"
  - "Youngmin Yi"
affiliations:
  - "Sogang University, Seoul, Republic of Korea"
  - "Santa Clara University, Santa Clara, CA, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790194"
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

oFFN 通过把两种统计规律变成显式结构来加速 ReLU-fied LLM 推理：activation outlier 只出现在少数稳定维度上，而不同神经元的激活频率高度不均。它先离线重排 FFN 权重，让 outlier 维度连续、hot/cold neurons 成块；在线预测时对 outlier 维度做精确点积，对其余维度做近似；执行时再把 hot neurons 送到 Tensor Core 上跑 dense GEMM，把 cold neurons 送到 CUDA core 上跑预测驱动的 sparse GEMM。论文报告相对 dense inference 的端到端解码最高 `2.01x` 加速，以及 FFN 层最高 `5.46x` 加速，同时精度损失可以忽略。

## 问题背景

这篇论文的出发点是，decoder 延迟的瓶颈正在发生迁移。早期很多 LLM 推理优化优先盯住 attention，因为 KV-cache 流量让 MHA 很容易成为主瓶颈；但作者认为，这个判断已经不再总是成立。随着 Grouped Query Attention、sparse attention、FlashAttention 一类优化逐渐成熟，FFN 在解码路径中的占比越来越高，尤其是在小 batch 场景里，每生成一个 token 仍要穿过整套 FFN 层。

围绕 FFN 稀疏性的已有方法大致分成两类，但都有明显缺口。输入激活稀疏可以跳过第一层 FFN 矩阵的列，不过这会破坏内存访问的 coalescing，而且常常依赖对接近零的激活做阈值裁剪，容易伤到精度。输出激活稀疏更有吸引力，因为一旦输出为零，就能直接跳过整行权重和对应计算；问题在于，如果模型不是 ReLU，精确零值非常少。ReLU-fication 解决了“零值不够多”的问题，但并没有解决“怎样又快又准地预测稀疏模式”。

作者对现有预测器的评价是：各自抓住了一部分，但没有把结构吃透。DejaVu、PowerInfer 依赖学习式 predictor，模型一变就要重新训练，移植性差。SparseInfer 完全 training-free，而且很快，但只看符号，忽略了大量幅值信息。Grasp 往前走了一步，用分组方式纳入粗粒度大小信息，并近似处理 outlier；但论文认为，真正主导误差的是极少数统计上特别重要的维度。另一方面，PowerInfer 发现了 hot/cold neuron 现象，却主要服务于 CPU-GPU 混合执行，也没有把它和 outlier 结构、动态 batch 变化统一起来。于是，真正的问题就变成：能否做出一个 training-free 的 FFN 执行路径，既让稀疏预测足够准，从而值得跳过大量工作，又能在 GPU 上随着 batch 大小变化持续高效。

## 核心洞察

论文最重要的观点是：过去被分开讨论的两个现象，其实彼此相关，而且应该一起利用。第一，activation outlier 很少，但并不随机；跨 prompt 来看，它们集中在一小组稳定的输入维度上。第二，神经元的激活频率极不均匀：有些是经常被激活的 hot neurons，另一些则是大多数时候经过 ReLU 后都为零的 cold neurons。作者进一步指出，这种 hot/cold 模式和稳定 outlier 维度存在紧密关系，因为 outlier 往往会给大多数神经元带来巨大的负 partial product，却会给少数符号对齐的神经元带来大的正贡献。

这带来一个不同于以往的 predictor 设计思路。既然真正拉低预测精度的是少数 outlier 维度，那么这些维度就不该继续被粗略近似，而应该精确计算。既然不同 neuron 的激活频率本来就高度倾斜，那么也不该让所有 neuron 一律走同一条 sparse 路径，而应该把高概率致密的部分直接送进 dense 路径，把最可能受益于预测跳过的部分送进 sparse 路径。换句话说，oFFN 的贡献不只是“换了个更好的启发式”，而是把 FFN 本身重新组织成了一个预测精度与 GPU 执行策略互相配合的结构。

## 设计

oFFN 分成三个阶段。首先是 offline calibration：系统跑一小批校准数据，识别哪些 activation 维度容易成为 outlier，同时估计每个 neuron 的激活频率，然后对权重做两种彼此独立的重排。列重排把与 outlier 高相关的维度搬到 `Wgate` 和 `Wup` 的前部，使 predictor 能连续读取这些维度并精确计算它们的 partial product。行重排则把 hot neurons 放在前面、cold neurons 放在后面，让 dense 区与 sparse 区在内存里天然连续，而不需要运行时搬动数据。

在线预测阶段，oFFN 保留了 Grasp 的分组近似思想，但只用于非 outlier 维度；同时新增一个精确的 outlier 项。于是 predictor 的输出由三部分构成：对 top outlier 维度做真实点积、对其余维度按组近似求和、再加上一个离线用 binary search 选出的 bias，用来达到目标 specificity。论文在实验里使用 `64` 个 outlier 维度，大约相当于输入宽度的 `1%`。作者报告说，这些维度虽然数量极少，却贡献了总 `L1` 预测误差的 `45.99%`，这也是为什么“只精确处理很小一块”就能明显抬高 predictor 精度。

真正执行 FFN 时，系统再按 hot/cold neurons 分流。hot neurons 被视为足够接近 dense，继续走 predictor 反而不划算，因此它们的子矩阵直接在 Tensor Cores 上以 dense GEMM 计算。cold neurons 则先经过 predictor：被预测为 sparse 的行在 gate 和 up 投影里直接跳过，剩余行再走 sparse CUDA kernel。这个 hot/cold 边界会随 batch size 改变，因为 batch 一大，structural sparsity 会下降，只要某个 neuron 在 batch 的任何一列里非零，该行就还是得从内存加载。为此，oFFN 在离线阶段预先为每一层、每个 batch size 算好最佳分界点，运行时只做查表。

CUDA 实现部分说明这并不是一个停留在公式层面的想法。为了高效计算精确 outlier 项，系统构造一个很小的 `Wtiny` 和 `Xtiny`，让这部分点积也能在 Tensor Cores 上高效执行。对 sparse gate/up 路径，作者通过 indirection array 把非零 cold-neuron 行压紧，避免大量 warp 因为预测为零而立刻退出。对 down 投影，由于这里能利用的是输入稀疏而不是输出稀疏，论文把 `Wdown^T` 转成 column-major 存储，并复用前面构建好的 indirection array，让真正需要参与求和的行保持连续。也就是说，oFFN 不只是提出了一个更准的 predictor，而是围绕它重做了权重布局和 kernel 执行方式。

## 实验评估

实验使用了 ProSparse-LLaMA-2-13B 和 7B，两者都是 ReLU-fied 模型，论文给出的稀疏率分别为 `88.80%` 与 `89.32%`。运行时基于带 FlashAttention 支持的 `llama.cpp`，硬件包括 Jetson AGX Orin、NVIDIA A100 和 RTX A6000。校准集使用 `100` 条 GSM8K 训练 prompt，共 `20K` token；精度评估则覆盖 GSM8K、BBH、TruthfulQA-Generation、HumanEval 和 MBPP 等以解码为主的 benchmark。

准确率结果整体很稳。当目标 specificity 设为 `80%`、`84%`、`88%` 时，oFFN 在两个模型上的平均精度都基本维持在 dense baseline 的 `1` 个百分点之内，有些任务甚至略有提升。作者还特地把 SparseInfer 和 Grasp 调到“在所有测试上尽量把精度损失控制在约 `1%p` 内”的最快配置来比较，这样的速度-精度对比是比较公平的。就 predictor 本身而言，oFFN 在 ProSparse-LLaMA-2-13B 上的平均 recall 达到 `96.71%`，在 7B 上达到 `95.57%`；论文称这比 SparseInfer 平均高 `57.23%p`，比 Grasp 平均高 `16.06%p`。

速度结果最能体现它的目标场景，也就是小 batch 解码。在 Jetson AGX Orin、batch size 为 `1` 时，oFFN 取得了最好的端到端加速，并且在 ProSparse-LLaMA-2-13B 上比 Grasp 快 `13%`。论文给出的 headline 数字是：解码阶段相对 dense inference 最高 `2.01x` 端到端加速，FFN 内部最高 `5.46x` 加速。分解实验也很有解释力：显式处理 outlier 维度带来了最大的性能跃升，因为 recall 变高后，可跳过的工作显著变多；而 hot/cold 分流在 batch 增长到 `4` 或 `8` 后才更明显地体现价值，因为这时 structural sparsity 下降，把一部分 neuron 送进 Tensor Cores 开始变得划算。在 A6000 和 A100 上，oFFN 也在 `1-8` 的 batch 范围内持续优于 dense baseline，而且在更受内存带宽限制的 A6000 上收益更明显。整体来看，这组实验确实支持论文主张：它不只是 predictor 更准，而是真正把这种精度优势转化成了多个 GPU 上可见的延迟收益。

## 创新性与影响

相对 _Shin et al. (DATE '25)_，oFFN 延续了 SparseInfer 的 training-free 路线，但把只看符号的近似改成了 outlier-aware 的预测方式，从而显著提高 recall。相对 _Shin et al. (DAC '25)_，它最核心的前进一步是，不再把 outlier 只当作“需要更谨慎近似”的对象，而是通过重排把它们变成一个可精确计算的小块，并进一步和 hot/cold-neuron 重排、batch-aware dense/sparse 分区结合起来。相对 _Liu et al. (ICML '23)_，这篇论文则证明，不依赖额外训练出来的 predictor，也能得到很强的稀疏预测能力。

因此，这篇论文会同时吸引两类读者。一类是做 LLM serving 和 GPU kernel 的研究者，因为它给出了把 activation 统计规律转化为布局与执行决策的一套具体方法。另一类是关心端侧推理或小 batch serving 的工程团队，因为它比 CPU-GPU 混合设计更适合纯 GPU 部署。更广义地看，这篇论文的价值在于提出了一种 co-design 思路：如果 activation 结构本身具有统计稳定性，那么运行时系统就不该只在线近似它，而应该把权重布局和 kernel 组织都围绕这种稳定性重构。

## 局限性

这篇论文的适用范围其实比标题略窄。实验的主战场是 ReLU-fied 模型，尤其是 ProSparse-LLaMA-2 系列，所以“快且准”的最强证据主要成立在本来就能产生大量精确零值的模型上。论文虽然额外分析了 SiLU-based 的 Llama-3.1-8B 和 gpt-oss-20B，说明 outlier 位置稳定性可能具有一定普适性，但完整的速度实验并没有在这些非 ReLU 模型上展开。因此，读者更应该把结论理解为“对 ReLU-fied 部署场景特别有效”，而不是“对所有 LLM 都已经同样验证完毕”。

另外，它也依赖一套离线校准假设。oFFN 需要通过 calibration 识别 outlier 维度、设置 bias、并为每层每个 batch size 预计算 hot/cold 阈值。作者把这件事描述得比较轻量，但面对显著不同的模型、token 分布或运行时栈时，是否仍然稳定，仍然需要进一步实验。实现上，论文是嵌在 `llama.cpp` 中完成的，没有真正讨论多租户 serving、大 batch 数据中心推理，或者与 speculative decoding 的深度联动；后者只是从“小的 verification batch 也许会受益”的角度做了合理推测。最后，评估主要围绕 FFN 稀疏方法和 dense baseline 展开，对于 oFFN 与更大范围 serving bottleneck 的组合效果，论文涉及不多。

## 相关工作

- _Shin et al. (DATE '25)_ — SparseInfer 主要基于符号计数来预测激活稀疏；oFFN 保留 training-free 前提，但把稳定 outlier 维度改成精确计算，并支持面向多 batch 的 dense/sparse 分区。
- _Shin et al. (DAC '25)_ — Grasp 引入了分组幅值信息和近似 outlier 处理；oFFN 则把 outlier 变成重排后的精确计算块，并和 hot/cold-neuron 感知执行结合起来。
- _Liu et al. (ICML '23)_ — DejaVu 通过额外训练的辅助层来预测 contextual sparsity；oFFN 选择完全避免 predictor training，以换取更好的可移植性。

## 我的笔记

<!-- 留空；由人工补充 -->
