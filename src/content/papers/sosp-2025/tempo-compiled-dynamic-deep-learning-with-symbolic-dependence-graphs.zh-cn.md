---
title: "Tempo: Compiled Dynamic Deep Learning with Symbolic Dependence Graphs"
oneline: "Tempo 把时间显式建模为 tensor 维度，用 symbolic dependence graph 编译跨 timestep 依赖，并联合调度执行与显存管理来运行动态 LLM 和 RL。"
authors:
  - "Pedro F. Silvestre"
  - "Peter Pietzuch"
affiliations:
  - "Imperial College London"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764840"
code_url: "https://github.com/LSDS/Tempo"
tags:
  - ml-systems
  - compilers
  - gpu
  - scheduling
  - memory
category: llm-serving
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Tempo 面向那类“依赖关系会随 timestep 变化”的深度学习程序。它用 recurrent tensor 和 symbolic dependence graph 把动态 attention、RL 回报计算这类模式重新表示成可整体优化、可分块、可调度、可做显存管理的单一程序。在一张 RTX A6000 上，论文报告它在 Llama-3.2-3B decoding 上最高比 JAX 快 7x，在 RL 训练上最高比现有框架快 54x，同时把峰值 GPU 显存降到最多 1/16。

## 问题背景

这篇论文瞄准的是两类主流 DL 执行方式之间的空档。像 PyTorch 这样的 eager 系统可以很自然地用 Python 表达随时间变化的依赖，但真实计算直到运行时才展开，因此很难做 whole-program 级别的优化，也很难全局安排执行与显存。像 JAX、TensorFlow 这样的 graph 系统擅长编译优化，却默认图中的 tensor shape 必须是静态的；一旦某个 timestep 需要读取前缀、窗口或后缀这类动态范围，就只能把程序 pad 到最坏情况、再用 mask 修正，或者把一个程序拆成多个静态子图。

这在真实工作负载里代价很高。对 autoregressive decoding 来说，attention 在第 `t` 步要读取动态长度的历史 key/value，于是 K/V cache 的管理既依赖具体算法，又很难统一优化。对强化学习来说，前向窗口或反因果的 loss 依赖迫使主流框架采用 actor-learner 拆分：actor 先生成 trajectory，learner 之后再重放并训练。论文指出，这会带来三个直接问题：前向推理被重复做两次，acting 和 learning 被强制串行，以及长轨迹带来的高 GPU 显存压力。

## 核心洞察

Tempo 的核心洞察是：这类“动态”程序并不是不能编译，而是因为现有系统没有把时间当成一等张量维度。Tempo 让 tensor 除了空间维度之外，还显式带有 timestep、iteration、episode 等 temporal dimension。这样一来，对过去或未来值的访问就不再是藏在 Python 控制流里的特殊情况，而只是对时间维度做 symbolic index。

一旦这些 symbolic expression 被显式暴露出来，Tempo 就能构建 symbolic dependence graph（SDG）：每个算子记录自己在哪些时间点执行，每条边记录它在某个时间点需要另一个算子的哪一段 symbolic slice。论文真正想证明的是这一点：dynamic DL 的难点主要不是“shape 会变”，而是“跨时间的依赖被隐藏了”；只要把 temporal dependence 作为编译器的一等对象，whole-program compilation 就重新成立。

## 设计

用户层抽象是 recurrent tensor。RT 在普通 tensor 的基础上增加 temporal domain、自动 domain 推断、symbolic shape 和 symbolic indexing。它还支持 symbolic automatic differentiation：如果 `x` 的某个 timestep 会影响 `y` 的多个 timestep，Tempo 会把 dependence expression 反转回来，把梯度正确累加到 `x` 的对应时间片上。这样，用户就能直接写出依赖未来 reward 的 RL loss，而不必先拆成 actor 图和 learner 图。

Tempo 随后把 RT 程序 lowering 成 SDG。图里的每个算子都带有 temporal domain，每条边都带 symbolic dependence expression。分支通过 `MergeOp` 表示，而参数与优化器状态则通过图中的 cycle 编码，而不是引入语义复杂的可变变量。这样，状态、控制流和时间依赖都在同一张图里显式化了。

在此之上，Tempo 依次做四类关键变换。第一类是 symbolic algebraic simplification 和 domain reduction。第二类是 lifting：把用递归形式写出来的 reduction、scan、stencil 等模式识别出来，提升成更适合优化的 batch 算子。第三类是 vectorization，也就是把时间维搬到空间维上，以更少次、更大张量的执行换取并行度。第四类是在 vectorization 之后如果张量太大，就再把某个空间维切成新的 temporal tile 维度做 tiling。对 causal attention 来说，这一步把“一个动态长度的大算子”改写成“动态个数的固定大小 tile”，从而可以复用现有静态 code generator，并且只需要给最后一个 tile 补齐，而不是给整个序列补齐。最后，Tempo 还会把静态 island 融合成单个 dataflow operator，以减少 dispatch 并简化调度。

真正独特的是调度。由于 future dependence 的存在，单纯的 topological sort 不够用。Tempo 使用 polyhedral model，把 SDG 变成一个整数线性规划问题：validity constraint 负责保证依赖顺序，proximity constraint 负责鼓励局部性和更短的张量生命周期。得到计算调度之后，它又把 deallocation、GPU/CPU swap-out、swap-in 以及 buffer donation 这些显存管理动作显式加入图中，再一起调度。最终产物是一个 imperative AST，运行时按 AST 在 JAX 或 Torch backend 上解释执行。为了高效访问不同依赖模式的数据，Tempo 还实现了 point、block、window 三类 tensor store，并通过 kernel wrapper 避免额外 copy。

## 实验评估

实验覆盖面在系统论文里算比较全面，但边界也很明确：全部是在单机、单 GPU 上完成。对 Llama-3.2-3B decoding，Tempo 相比 eager 的 Torch 始终占优，因为它能做编译优化；而相比 JAX，它在长序列上开始明显拉开差距，因为 JAX 必须继续承受整段 padding 的代价。在 causal attention、batch size 为 4 时，Tempo 在 32,768 token 上比 JAX 快 2.0x，在 65,536 token 上快 2.5x。换成 window attention、batch size 为 16 时，Tempo 相对 Torch 最多快 3.9x，相对 JAX 在 16,384 token 时最多快 7x；更重要的是，只有 Tempo 会根据 window 依赖真的改变内存行为，及时释放旧 K/V，并用 circular store 支撑至少 4x 更长的序列。

RL 的结果更夸张。论文在 PPO、REINFORCE 和 `n`-step return 变体上，对比了 SampleFactory、RLGames、CleanRL 和 RLlib 等五个框架。对小到中等规模的 PPO 配置，Tempo 最多比 RLlib 快 54x，且平均比下一个最快的基线还快 2.6x。原因和论文的核心论点一致：Tempo 保留了 whole-program 视角，可以复用 actor 产生的 activation，而不用在 learner 中重算；它还能沿 timestep 做 vectorization，并根据真实依赖去安排学习阶段。对大尺寸图像观测，传统 actor-learner 框架因为要整段缓存 trajectory，很快就 OOM；Tempo 则通过 tiling 加上 CPU/GPU swapping，一路扩展到 `3x256x256` 观测。编译时间也基本不随 transformer 层数增长而恶化，大约稳定在 18 秒左右，因为层间重复结构被编码成 temporal dimension，而不是被展开成巨大图。

整体看，实验较好支撑了论文对“单 GPU、规则 temporal dependence 工作负载”的核心论断。主要保留意见是：RL 环境是为了放大框架开销而特意选择的，且所有证据都来自一张 RTX A6000，而不是多种 GPU 或分布式环境。

## 创新性与影响

这篇论文的新意不只是“支持 dynamic shape 的 DL compiler”。这条线之前已经有不少工作。Tempo 最特别的地方在于，它把 symbolic temporal dependence 设为编译器的中心抽象，然后让这个抽象贯穿整条链路：symbolic autodiff、vectorization、dynamic program 的 static tiling、polyhedral scheduling，以及显存规划都建立在同一张 SDG 上。

这也是它可能产生影响的原因。对编译器研究者来说，论文证明了 recurrence-equation 风格的时序结构可以被转化为实际可行的 DL 执行系统；对搭建 LLM runtime 或 RL runtime 的系统研究者来说，它提供了一个比手写 K/V cache 策略和 actor-learner 管线更统一的思路。即便 Tempo 本身仍是原型，这篇论文很可能会因为一个关键观点被持续引用：dynamic DL 应该被编译成“带显式时间索引的完整程序”，而不是被退化成 padding 加 masking。

## 局限性

作者对系统边界写得比较坦率。Tempo 目前只支持单 GPU；讨论部分虽然提到了可能如何扩展到分布式，但并没有实现。它也还不支持 temporal dimension 的动态终止，因此真正依赖运行时决定循环上界的程序仍然是未来工作。

不少关键策略也还比较初级。tile size 需要用户手工指定，没有自动搜索；swapping 决策不感知 kernel latency，可能引入等待；小模型上还会暴露 Python 层 AST 解释执行的开销。系统也缺少对 FlashAttention 这类手工高性能 kernel 的一等支持，而现代 LLM 栈对这类 kernel 的依赖很强。最后，虽然 Llama decoding 与若干 RL 算法上的结果很有说服力，但对更多模型结构、多 GPU 训练和真实生产 serving 栈的泛化能力，论文证据仍然有限。

## 相关工作

- _Ansel et al. (ASPLOS '24)_ — PyTorch 2 通过 symbolic shape 和 speculative compilation 支持动态 Python，而 Tempo 进一步把重点放在跨 timestep 的 symbolic dependence 与 whole-program scheduling 上。
- _Lai et al. (ASPLOS '25)_ — Relax 为动态 ML 编译提供可组合抽象，但 Tempo 关注的是更窄也更难的 dynamic temporal dependence，并把调度与显存规划一并纳入。
- _Vasilache et al. (arXiv '18)_ — Tensor Comprehensions 用 polyhedral model 做 kernel 级 tensor 优化，而 Tempo 把 polyhedral scheduling 提升到跨 timestep 的 whole-program 层面。
- _Rhu et al. (MICRO '16)_ — vDNN 通过 swapping 缓解训练显存压力，但 Tempo 是从显式 dependence-aware schedule 中导出 deallocation 和 swap 时机，而不是把内存管理作为独立子系统。

## 我的笔记

<!-- empty; left for the human reader -->
