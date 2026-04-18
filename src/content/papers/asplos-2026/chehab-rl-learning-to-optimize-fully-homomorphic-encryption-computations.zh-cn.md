---
title: "CHEHAB RL: Learning to Optimize Fully Homomorphic Encryption Computations"
oneline: "CHEHAB RL 用强化学习选择 FHE 重写序列，在比 Coyote 更短的编译时间内生成旋转更少、噪声更低的向量化电路。"
authors:
  - "Bilel Sefsaf"
  - "Abderraouf Dandani"
  - "Abdessamed Seddiki"
  - "Arab Mohammed"
  - "Eduardo Chielle"
  - "Michail Maniatakos"
  - "Riyadh Baghdadi"
affiliations:
  - "New York University Abu Dhabi, Abu Dhabi, United Arab Emirates"
  - "Ecole Superieure d'Informatique, Algiers, Algeria"
  - "Center for Cyber Security, New York University Abu Dhabi, Abu Dhabi, United Arab Emirates"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790138"
code_url: "https://github.com/Modern-Compilers-Lab/CHEHAB"
tags:
  - security
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CHEHAB RL 把 FHE 优化改写成“按顺序挑选重写规则”的决策问题，而不是继续依赖启发式或求解器搜索。它学到的策略能在 BFV 电路上自动做向量化，同时把旋转、乘法深度和编译时间一起压下来，因此通常比 Coyote 生成更快、噪声更低的代码。

## 问题背景

这篇论文抓住的是 FHE 落地里一个很硬的瓶颈：同态算术本身已经极贵，而编译器如果把向量化、打包和旋转安排得不好，整个应用的延迟和噪声预算都会迅速失控。FHE 开发者不只是要“把标量程序改成 SIMD 程序”，还得同时关心后续会多出多少 rotation、密文乘法会把 multiplicative depth 推高多少、最后剩余噪声预算是否还足够解密。

已有编译器各有短板。HECO 和 CHET 主要处理有规则的 structured program，对任意 unstructured arithmetic circuit 无能为力。Coyote 和 Porcupine 虽然支持 unstructured code，但它们把问题建模成组合搜索：哪些子表达式该打包、数据布局该怎样排、哪些地方需要旋转和 mask。这样的空间一大，局部决策就会牵动全局代价，搜索本身也会越来越慢。论文的核心出发点是：与其每次为一个新程序重新做昂贵搜索，不如直接学出一个能组合 rewrite 的全局策略。

## 核心洞察

作者最重要的命题是：只要状态表示和奖励函数足够 FHE-aware，FHE 向量化就可以被学成一个 rewrite policy。编译器不必对每个程序都从头找“最优布局”，而是把 IR 看成一个可被连续改写的对象，让策略网络逐步选择哪条规则、在什么位置应用，从而优化统一的全局代价。

这件事之所以可行，是因为 FHE 程序虽然难优化，但运算符集合其实相对受限，真正困难的是长程依赖。某个早期的交换律、提取公因子或者向量化改写，表面上看只是小调整，后面却可能决定一大片子树是否还能继续合并、是否会引入额外 rotation、是否会抬高 multiplicative depth。CHEHAB RL 的价值就在于，它学的是这种“先吃一点局部代价，换后面大收益”的序列决策，而不是只盯着眼前一步的改进。

## 设计

CHEHAB 整体上仍是一个常规编译器流水线：DSL 前端先降到 AST/IR，然后做优化、选择 rotation key，最后把代码生成到 Microsoft SEAL 的 BFV 后端。论文新增的是中间的优化阶段：一个由 actor-critic 驱动的 term rewriting system。系统总共有 84 条 rewrite rule，再加一个 `END` 动作。规则既包括把标量模式合并成向量操作的规则，也包括降低操作数、circuit depth 和 multiplicative depth 的代数化简规则。

状态表示是这套方法是否成立的关键。作者提出 Identifier and Constant Invariant tokenization，把变量名和大多数常量做 canonicalization，让语义相近的程序落到相同或相近的 token 序列上。随后用一个 4 层、8 个 attention head 的 Transformer encoder，把程序编码成 256 维向量。论文强调，这种表示比 BPE 更贴合此问题，因为它直接利用了编译 IR 的结构，而且更方便去重和泛化。

动作空间则分成两层。第一层 rule-selection network 先选“用哪条规则”；第二层 location-selection network 再选“把这条规则用在第几个匹配位置”。这样做是因为同一条规则往往能匹配多个子表达式，如果把“规则 x 位置”全部摊平，动作空间会迅速爆炸。奖励函数也明显针对 FHE 定制：总代价由 operation cost、circuit depth 和 multiplicative depth 相加构成，其中 vector add 记 `1`，vector multiplication 记 `100`，rotation 记 `50`，scalar operation 记 `250`，目的就是强烈推动策略去寻找真正划算的向量化。训练时同时给 step reward 和 terminal reward，避免 PPO 只学会追逐短视的局部改进。

另一个关键设计是训练数据。因为公开世界里并没有“可优化 FHE 程序”的现成数据集，作者用 Gemini 2.5 Flash 按 CHEHAB IR 语法、rewrite 示例和真实 kernel 提示去合成程序，再经过解析、ICI 去重和 benchmark 排除。最后得到 `15,855` 个唯一表达式。论文后面的 ablation 说明，这不是锦上添花，而是决定策略能否学到真实程序分布的重要前提。

## 实验评估

实验平台是一台 Xeon E5-2680 v4 CPU 服务器，FHE 方案为 BFV，参数使用 `n = 16384`，底层库是 SEAL 4.1。评测基准覆盖 Porcupine 的 kernels、Coyote 的 kernels，以及随机生成的不规则 polynomial tree。真正的对比对象主要是 Coyote，因为 Porcupine 虽被纳入讨论，但作者联系后仍拿不到其实现。为了让比较更聚焦算法本身，论文还关闭了 CHEHAB 的 automatic rotation-key selection，并在双方都关闭了 blocking。

结果相当扎实。按几何平均，CHEHAB RL 生成的代码执行速度比 Coyote 快 `5.3x`，编译时间快 `27.9x`，消耗的噪声预算少 `2.54x`。最有说服力的例子来自 `Poly. Reg. 32` 和 `Linear Reg. 32`：前者快 `50x`，后者快 `114x`。原因不是某个单独 kernel 更快，而是学到的策略常常能把电路压到极小，而 Coyote 则会引入大量 ciphertext-plaintext multiplication 和 rotation。噪声结果同样支持论文主张：在 `Sort 4` 和若干 tree benchmark 上，Coyote 会直接耗尽 budget 导致电路无法执行，而 CHEHAB RL 仍能生成可运行电路。

论文也没有回避失败样例。`Tree 50-50-10` 上 Coyote 更快，因为 CHEHAB RL 虽然把电路整体压得更紧凑，却引入了更多昂贵的 ciphertext-ciphertext multiplication。ablation 也比较有信息量：用 LLM 数据训练的 agent 比随机数据训练的 agent 好很多；step+terminal reward 比只有 step reward 的版本在执行时间上好 `1.291x`；ICI tokenization 在同样 `2` million PPO steps 下把训练时间从 `68` 小时降到 `43` 小时。

## 创新性与影响

相对 _Malik et al. (ASPLOS '23)_，这篇论文的创新点不是把 Coyote 的启发式再微调一下，而是直接换掉了优化控制环路：把昂贵的按程序搜索，变成离线训练、在线快速应用的 rewrite policy。相对 _Cowan et al. (PLDI '21)_，它同样覆盖 structured 和 unstructured 两类程序，但更强调自动数据布局与可扩展性。相对 _Dathathri et al. (PLDI '19)_ 和 _Viand et al. (USENIX Security '22)_，它把 FHE 编译问题从规则化的神经网络/循环程序，扩展到一般算术电路。

因此，这篇论文对 FHE compiler builder 的价值很直接：它说明“用一次训练成本换大量 per-program 编译成本”在这个领域是可行的。更广义地看，它也是一个不错的例子，展示 RL 在符号化编译优化中何时真正有用：动作有长程影响、真实执行反馈太慢、但又能写出一个足够靠谱的领域成本模型时，学习式策略就有现实优势。

## 局限性

实验范围还是比较收敛的。后端只覆盖 BFV on CPU through SEAL，论文并没有证明学到的策略能否无缝迁移到 CKKS、GPU 或其他 FHE 库。奖励函数依赖手工设计的 analytical cost model，而不是把真实执行时间放进训练环里；其中一些操作权重更多是为了形成优化压力，而不是逐项从硬件测得。

比较对象也有限。Porcupine 在 Related Work 里被认真讨论，但实验里无法复现；因此最核心的实验结论本质上是“明显优于 Coyote”。另外，为了公平对齐，作者关闭了 blocking 和 automatic rotation-key selection，这对算法比较是合理的，但也意味着论文没有完整展示最强端到端部署形态。最后，主实验把输入布局变换提前到加密前、交给客户端完成，这当然是现实可用的系统技巧，但也把一部分复杂度移出了服务器侧编译流程。

## 相关工作

- _Malik et al. (ASPLOS '23)_ - Coyote 用启发式加 ILP 搜索来向量化加密算术电路，而 CHEHAB RL 用学习到的 rewrite policy 取代高开销搜索。
- _Cowan et al. (PLDI '21)_ - Porcupine 同样面向 structured 与 unstructured FHE 向量化，但 CHEHAB RL 更强调自动数据布局与更好的扩展性。
- _Dathathri et al. (PLDI '19)_ - CHET 主要优化同态神经网络推理这类 structured tensor program，而 CHEHAB RL 面向更一般的算术电路与任意 unstructured 表达式。
- _Viand et al. (USENIX Security '22)_ - HECO 把 structured FHE 程序编译成向量化代码，而 CHEHAB RL 进一步处理 unstructured expression，并显式优化 rewrite 次序、深度和噪声。

## 我的笔记

<!-- empty; left for the human reader -->
