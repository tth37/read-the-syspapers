---
title: "CoGraf: Fully Accelerating Graph Applications with Fine-Grained PIM"
oneline: "CoGraf 用 tuple 化缓存聚合、多列 FGPIM 更新和 bank-parallel 谓词执行，同时加速图算法的 update 与 apply 两个阶段。"
authors:
  - "Ali Semi Yenimol"
  - "Anirban Nag"
  - "Chang Hyun Park"
  - "David Black-Schaffer"
affiliations:
  - "Uppsala University, Uppsala, Sweden"
  - "Huawei Technologies, Zurich, Switzerland"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790142"
code_url: "https://github.com/alisemi/CoGraf"
tags:
  - graph-processing
  - hardware
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CoGraf 的核心论点是：如果 FGPIM 只加速图算法里不规则的 scatter/update，那还称不上“完整加速”。它把缓存侧聚合、多列 DRAM 内执行，以及 bank-parallel 的谓词指令一起设计，让不规则的 update phase 和规则但带条件的 apply phase 都能在 DRAM 内外协同完成。结果是，PIM 不再只是局部优化，而是变成了面向整条图处理流水线的加速方案。

## 问题背景

论文抓住的是 FGPIM 与图处理之间一个很典型的结构性错位。FGPIM 最擅长的是利用 DRAM 的行局部性和列级 SIMD，在一行被激活后尽量多做计算；但 vertex-centric、push-based 图算法的 update phase 恰恰会产生高度不规则的 read-modify-write 访问。已有工作通常走两条路：一种是把单个原子更新直接下推到内存里执行，另一种是在缓存里先做 cacheline 粒度的合并，再对每个 DRAM 列分别发 PIM 命令。两者都能减少 CPU 侧数据搬运，但都没有真正把 DRAM 的行级结构吃满。

更关键的是，这还只解决了一半。同步 push-based 图算法在 update 之后还有一个 apply phase，它确实更规则，但并不是单纯的向量加法。这里常常包含条件判断，例如“只有 delta 足够大才写回 score”，也包含 frontier 生成、误差累加这类 hybrid reduction。此前很多 FGPIM 论文实际上默认 apply 仍留在 CPU 侧，于是 update 一旦被加速，apply 就会立刻变成新的瓶颈。CoGraf 的目标因此不是“把图原子操作搬到内存里”，而是“让 PageRank 一类 update-apply 算法的两个阶段都能被 PIM 有效覆盖”。

## 核心洞察

CoGraf 最值得记住的洞察是：图更新应该按照最匹配 DRAM 行行为的粒度来聚合，而不是被普通 cacheline 粒度绑死。只要多个稀疏更新最终落在同一个 DRAM row，把它们在 LLC 里按“行”聚在一起，就能让一次 row activation 驱动更多有用工作。这既提升了缓存利用率，也减少了 row activation，还让每次送往 FGPIM 的工作包足够大，值得在 DRAM 里处理。

但更大粒度的聚合会立刻带来第二个要求：PIM 侧必须理解“同一个被逐出的缓存行，可能对应同一 DRAM row 内的多个 column”。CoGraf 因而把更新编码成 tuple 形式送给 FGPIM，让 memory controller 预先看懂这个命令会触及多少列，从而静态调度其可变延迟；接着又加入 bank-parallel predication，让 apply phase 里的条件执行也能在 DRAM 内完成。换句话说，这篇论文真正的主张不是某一条新指令，而是缓存、内存控制器和 PIM 单元都围绕同一套 row-oriented work representation 协同工作，图的不规则性才会变得可管理。

## 设计

第一部分是 tuple-based LLC。CoGraf 让用于 update 聚合的缓存行进入一种 tuple 模式，不再默认这 64B 对应一段连续地址，而是显式存 `{offset, update}` 对。缓存的 set index 和 tag 只由 DRAM row 地址决定，row 内的列偏移与字偏移则放进 tuple 元数据里。对 32-bit update 而言，这会把每条缓存行可存的更新数从 64B 粒度下的 `16` 个，降到 1 KB 粒度下的 `12` 个、8 KB 粒度下的 `11` 个；但换来的好处是，这些槽位现在可以吸收整个 DRAM row 范围里的更新。论文指出，固定 cacheline 粒度的方案里，送去 DRAM 的更新 cacheline 平均有 `88%` 是零，因此更大粒度的主要收益并不是“存更多值”，而是少浪费缓存空间和带宽。

第二部分是 FGPIM 的多列更新执行。因为一个 row 粒度的 tuple line 往往会跨越多个 DRAM column，如果仍然按列分别发命令，就会把前面聚合出的收益重新吐回去。CoGraf 的做法是把整个 tuple cacheline 直接发给 FGPIM，由硬件并行识别它会触及哪些 column，然后在同一次 row 打开的窗口内按顺序处理这些列。memory controller 会先检查 tuple line，算出这条命令要访问多少列，因此无需等待 PIM 端回传完成信号，就可以静态安排这条可变延迟命令。论文报告说，相比“每列一条命令”，这种做法平均减少了 `79%` 的 FGPIM update commands。

第三部分是 apply phase 的加速。CoGraf 新增了 `BP_FGPIM_mov`、`BP_FGPIM_add`、`BP_FGPIM_mul`、`BP_FGPIM_mad`，以及 predicate-setting 和 conditional-move 等 bank-parallel 指令，并利用 FGPIM 内部的 temporary storage 保存中间状态。像 `scores`、`next_scores`、`deltas` 这样的数组会被重新布局，使得相应分块落在同一个 bank 中但位于平行的 DRAM rows。这样一来，系统就能在所有 bank 上并行评估 `delta > e * score` 这类条件，只在 predicate 为真时写回 score，并把大部分规则的 apply 运算放到 DRAM 内做完。

还有两件事仍需要 CPU 收尾，但接口已经很窄。其一是 frontier 生成：CoGraf 把 predicate 结果写成紧凑 bitmap，由 CPU 读回这些 bitmap 后组装下一轮 frontier。其二是 convergence error：每个 bank 先做部分归约，CPU 再从每个 bank 读回一个 DRAM column 的 partial sum，完成最终累加。因此，这个设计并不宣称“主机完全退出”，而是把主机压缩到只做那些不适合 in-bank SIMD 的跨 bank 归约与控制逻辑。

## 实验评估

这篇论文的实验是基于模拟器，但建模相当细。作者在 Ramulator 上扩展了 HBM-PIM 风格的模型，使用 32 MB 的共享 LLC，同时评估 `HBM2`（`1024 GB/s`、`1 KB` row）和 `DDR4`（`137 GB/s`、`8 KB` row）。应用包括五个 push-based 图算法：`BFS`、`CC`、`PR`、`PRD`、`RD`；输入图来自 GAP 风格数据集，包括 Twitter (`TW`)、sk-2005 (`SK`)、USA-road (`RO`) 以及生成的 `k27`、`u27`。基线也选得比较到位：`PHI` 代表 CPU 侧 state-of-the-art cache coalescing，`FGPIM` 是不做聚合的朴素内存内执行，`AIM` 是固定列粒度聚合，随后再叠加 CoGraf 自己的 `Optimal`、`Multi` 和 `Bank-parallel`。

总结果非常清楚。完整方案相对 `PHI` 在 HBM 上达到 `4.4x` 加速、在 DDR 上达到 `9.8x` 加速，同时 DRAM energy 分别下降 `88%` 和 `94%`。即使相对 naive FGPIM，它仍然快 `1.8x` 和 `3.0x`，DRAM energy 下降 `67%` 和 `86%`。更重要的是分步结果。`AIM` 到 `Optimal` 的变化本身主要带来能耗收益：HBM 下降 `22%`、DDR 下降 `57%`，原因是更大粒度聚合显著减少了 row activations；但它对性能帮助极小，HBM 甚至还慢了 `2%`。只有加入多列命令后，update phase 才真正把额外聚合转化成性能收益。再往上叠加 bank-parallel apply 支持，又相对 `Multi` 带来 `1.5x/1.6x` 的额外提升，这正好证明了论文的核心观点：只加速 update 并不完整。

按图结构拆开看，实验也很有解释力。像 `TW`、`k27`、`u27` 这类低局部性图，收益主要来自 update phase；而高局部性的 `SK` 和边顶点比很低的 `RO`，最大收益则来自 bank-parallel apply。以 `PRD` 为例，完整方案相对 `PHI` 在 `SK` 上只有 `1.7x/1.8x` 的提升，但在 `u27` 上可以达到 `12.1x/57.5x`，对应能耗节省最高到 `97%/98%`。这说明 CoGraf 不是一个“任何图上都差不多”的常数级优化，而是明确受图局部性和瓶颈阶段支配的系统设计。另一方面，所有基线都在同一模拟框架中实现，这也让对比比“拿别的论文数字拼起来”更可信。

## 创新性与影响

和 _Mukkara et al. (MICRO '19)_ 相比，CoGraf 把 `PHI` 那种缓存侧更新合并思路真正接到了 FGPIM 上，而不是让 apply phase 继续留在 CPU。和 _Ahn et al. (ISCA '15)_、_Nai et al. (HPCA '17)_ 相比，它的创新点也不只是“把图原子操作移到内存附近”，而是让缓存表示、命令形态和 bank-parallel 执行共同贴合 DRAM 的 row/column 结构。和更近的图-PIM 工作如 _Shin et al. (MICRO '25)_ 相比，CoGraf 最特别的一点是把 conditional apply logic 当成一等目标，而不是只关注更好的 gather/scatter 局部性。

因此，这篇论文最可能影响两类人。对做实用 PIM 接口与内存架构的人来说，它给了一个很具体的例子，说明“fine-grained” PIM 本身还不够，系统上层仍需要配套协同设计。对图系统研究者来说，它则更明确地说明了为什么“只加速一半”会让瓶颈不断迁移。它本质上是一篇机制设计论文，但它的说服力来自完整流水线层面的论证。

## 局限性

论文的边界也很明确。首先，结果全部来自模拟，而且主要聚焦在最大迭代上，也就是工作集明显超过 LLC、聚合最有价值的那一段；作者自己也承认，对很小的迭代，CPU 方案可以通过跳过未触及顶点而做得更好。其次，编程模型并不自动：update phase 只需要把原子操作替换成 FGPIM update，但 apply phase 需要显式算法改写、专门的数据布局、pinned pages，以及 bank-parallel 分配辅助库。再者，CoGraf 也继承了典型 PIM 成本，作者估算 DRAM 容量大约减少 `25%`；对于超出内存容量的大图，论文更多是建议用 CXL memory 或 graph tiling，而不是直接展示端到端实现。最后，它最强的证据集中在同步、push-based 图算法上，论文并没有声称 pull-style 算法或任意图软件都能同样自然地映射过去。

## 相关工作

- _Ahn et al. (ISCA '15)_ — PEI 展示了如何把细粒度操作下推到内存中执行，但 CoGraf 更进一步，让缓存聚合粒度和 apply-phase 执行方式都贴合 FGPIM 的 row/column 结构。
- _Nai et al. (HPCA '17)_ — GraphPIM 将图更新 offload 到 PIM，和 CoGraf 的 naive-FGPIM baseline 最接近，但没有提供 CoGraf 的 tuple 聚合或 apply-phase 谓词执行。
- _Mukkara et al. (MICRO '19)_ — PHI 在 CPU cache 中合并 commutative 图更新；CoGraf 延续这个思路，但把合并后的工作推进 FGPIM，并继续加速后续 apply phase。
- _Shin et al. (MICRO '25)_ — FALA 通过 locality-aware PIM-host cooperation 和细粒度列访问改进图处理，而 CoGraf 更强调大粒度缓存聚合加上 bank-parallel 条件执行。

## 我的笔记

<!-- 留空；由人工补充 -->
