---
title: "PACT: A Criticality-First Design for Tiered Memory"
oneline: "PACT 在线估计每个页面对 CPU stall 的真实关键性，把真正拖慢 tiered memory 的页提到 DRAM，而不是只追逐热点页。"
authors:
  - "Hamid Hadian"
  - "Jinshu Liu"
  - "Hanchen Xu"
  - "Hansen Idden"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech, Blacksburg, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790198"
code_url: "https://github.com/MoatLab/PACT"
tags:
  - memory
  - disaggregation
  - kernel
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PACT 的核心主张是：tiered memory 不该继续围着 hotness 打转，而该围着 page criticality 做放置决策。它提出 Per-page Access Criticality (PAC)，用标准 CPU counter 加上 LLC-miss 采样在线估计每个页面对 CPU stall 的贡献，再据此驱动 page promotion / demotion。结果是在 DRAM、NUMA 和类 CXL 慢层配置里，PACT 相比次优方案最高可提升 61% 性能，同时把迁移次数压低很多。

## 问题背景

这篇论文盯住了 page-tiering 里一个非常根本、但又长期被默认接受的前提：大多数系统都把“热页”当成“该放进快层的页”。这个前提之所以流行，是因为访问频率确实最容易观测；但在异构内存里，它往往也是错误的。一个页面如果在 streaming loop 里被频繁访问，CPU 可能通过较高的 memory-level parallelism (MLP) 把很多 miss 重叠掉，于是这个页面虽然“很热”，却未必真的拖慢执行。相反，另一个访问次数较少的页面如果总出现在 pointer chasing 之类串行依赖链里，每次 miss 都可能直接把核心卡住。快层容量有限时，只按频率升页，很容易把 DRAM 花在错误的页面上。

这个问题在今天的 tiered memory 环境里更严重，因为慢层已经不只是传统远端 NUMA，还可能是 persistent memory 或 CXL memory，访问延迟显著更高。现有系统当然也在做采样、hint fault、热度估计和阈值迁移，但论文认为它们本质上仍在优化一个间接代理信号。哪怕是少数开始考虑访问代价的工作，也常常停留在粗粒度离线 profiling，或者把 criticality 只当成热度策略上的辅助提示。真正缺失的是一个在线、page-granular 的度量，直接回答“这个页面到底让 CPU 多 stall 了多少”。

难点在于可观测性。CPU 能给你 coarse-grained 的 stall counter 和 access counter，却不会直接吐出“每层、每页的 stall 成本”。所以论文面对的核心系统问题其实有两个：第一，怎样用便宜的在线硬件信号逼近每页关键性；第二，怎样让迁移策略真正利用这个信号，而不是在 page churn 里把收益抵消掉。

## 核心洞察

论文最关键的洞察是：在 tiered memory 里，真正该优化的目标不是“谁访问最多”，而是“谁的慢层访问造成了最多 stall”；而这个目标居然可以只靠少量标准硬件计数器在线估计出来。PACT 把 PAC 定义为某个页面对 CPU stall cycles 的贡献。它不再把所有 LLC miss 一视同仁，而是先看某一层当前承受的 MLP，再用 `LLC-misses / MLP` 去近似该层的 stall 成本，外加一个与硬件配置相关的系数。

这个定义的重要之处在于，criticality 不是页面静态自带的标签，而是执行阶段相关的属性。论文观察到，MLP 虽然会随着程序 phase 改变，但在几十毫秒这样的短窗口内通常相当稳定。于是 PACT 可以先估算一个采样窗口内慢层总 stall 成本，再把这部分成本按页面在窗口里被采到的访问比例分摊出去。这样一来，本来只能在处理器级别看到的粗信号，就被转换成了可操作的 per-page 估计。

## 设计

PACT 由三部分组成：PAC profiling、PAC tracking，以及 PAC 驱动的 migration policy。PAC profiling 默认每 20 ms 运行一次。系统读取 LLC miss 和 CHA/TOR occupancy 等四个标准 counter，用来估计 per-tier MLP 和慢层 stall；与此同时，Intel PEBS 对慢层 LLC-miss 访问做采样，记录虚拟地址和对应的采样访问次数。PACT 随后把该窗口估出的 stall 预算分配到被采样到的页面上，并更新每个页面的 PAC 值。默认不开启 cooling，因为新变得关键的页面本来就会快速浮到上层。

这里最有意思的技术动作是 MLP 建模。PACT 利用 CHA/TOR 队列位于 core 与 off-core memory 之间这一事实，把它当成观察某一层 outstanding requests 数量的窗口。通过队列 occupancy 除以非空周期数，系统就能在线估计某一层的 MLP，从而区分“导致串行 miss 的页”和“其 miss 大量被重叠掉的页”。论文用 96 个 workload 验证了这一建模方式，在三种 latency 配置下，模型预测和实测 stall 的 Pearson 相关系数都超过 0.98。

PAC 算出来之后，PACT 还需要一个便宜的方法找出最值得升的页面。它把 per-page PAC 元数据存在 hash table 里，但不做全局排序，而是用 adaptive bins 维护优先级。具体做法是用 reservoir sampling 近似当前 PAC 分布，再用 Freedman-Diaconis rule 在线决定 bin 宽度；如果高优先级候选挤得太多或太少，再动态放大或缩小 bin 宽度，以稳定 promotion 压力。

迁移策略分成 promotion 和 demotion 两面。Promotion 是 PAC-first 的：总是从最高优先级的非空 bin 中立刻选页，并通过 `move_pages()` 升到快层。Demotion 则是 eager 的，而不是等空间不够时再被动回收。PACT 会提前从 LRU 一侧回收一些 DRAM 空间，保证高 PAC 页面一出现就能升上来。实现上它保持务实：基于 Linux 5.15，修改了 `perf`，通过共享内存在 perf 和 PACT 间传递数据，外加两个辅助线程；每个被跟踪的 4 KB 页面只需约 25 字节元数据。

## 实验评估

这篇论文的实验很扎实，而且对 baseline 的覆盖在同类工作里算相当完整。PACT 跑在一台双路 Intel Skylake CloudLab 机器上，本地 DRAM 延迟约 90 ns，远端 NUMA 为 140 ns，模拟出的 CXL 慢层约为 190 ns。工作负载覆盖 graph analytics、GPT-2 inference、Redis/YCSB、SPEC CPU 等多类 memory-intensive 应用。比较对象也很多，包括 Soar/Alto、Memtis、Colloid、Nomad、TPP、Linux NUMA balancing tiering，以及不做 tiering 的 `NoTier`。

最醒目的结果是：在 13 个 workload、7 组快慢层容量比下，PACT 相比次优已有系统最高能提升 61% 性能。即使 PACT 不是绝对第一，它与最佳方案的平均差距也只有 4.1%，最大差距为 11.8%。在论文重点分析的 `bc-kron` graph workload 上，4 KB 页配置下 PACT 相比其他在线基线快 2-22%，同时 promotion 次数最多比 Colloid 少 10.4 倍、比 NBT 少 9.6 倍。切到 THP 后，它在几乎所有 tier ratio 下依然最好，也超过了 Memtis。

1:1 的全 workload 对比也很能说明问题。在 `bc-urand` 上，PACT 相比 Colloid 把 slowdown 再降 20%，相比 Nomad 降 80%。在 `gpt-2` 上，所有 hotness-first 系统都比什么都不迁移更差，只有 PACT 真正优于 `NoTier`，其 slowdown 是 27%，而 Colloid 和 Nomad 分别是 51% 与 49%。论文还补了 bandwidth contention、colocation 和参数敏感性实验，这些都很好地支撑了主线论点：PACT 赢在更会挑真正值得迁移的页面。

我认为这套评测整体是公平的。baseline 足够多，tier ratio 覆盖也足够广，而且作者明确把依赖离线 profiling 的 Soar 比较和在线系统比较区分开了。最大的保留意见是，论文里的“CXL”慢层本质上还是高延迟 NUMA 仿真，而不是真实商用 CXL memory pool。

## 创新性与影响

和 _Liu et al. (OSDI '25)_ 相比，PACT 的创新点在于把原本较粗、部分离线的 cost reasoning，推进成真正在线、按页粒度、直接驱动运行时 tiering 的 PAC 信号。和 _Vuppalapati and Agarwal (SOSP '24)_ 相比，它并不认为“访问延迟本身就是关键”，而是认为必须再结合 MLP，才能看清哪些页面真的在让 CPU stall。和 Memtis、TPP 这类 hotness-first 方案相比，它改的不是阈值，而是控制变量本身：page placement 决策不再问“谁最热”，而是问“谁对执行伤害最大”。

这种变化对研究和工程都很重要。对研究者来说，PAC 是一个很有潜力继续复用的抽象。对工程实践来说，论文给出了一条比较现实的路线：不必把迁移做得越来越激进，而是先把“该迁谁”测准，很多 page churn 自然就会消失。

## 局限性

PACT 最大的限制是混部场景下的 attribution 精度。它的 proportional attribution 依赖这样一个假设：在一个短采样窗口里，程序行为相对稳定。论文对许多 workload 验证了这一点，但对任意复杂的多租户干扰模式并没有完全覆盖。作者自己也承认，如果同一慢层里同时混入 streaming 和 pointer-chasing 两类访问，按采样频率分摊 stall 可能会把真正 latency-sensitive 的页面稀释掉，哪怕他们的受控混部实验里 PACT 依然占优。

这个系统也明显带有平台依赖色彩。当前实现依赖 Intel 的 PEBS 与 CHA/TOR counter；虽然论文讨论了 AMD 上的可移植思路，但并没有给出实测验证。评估使用的是模拟 CXL 慢层，而不是成熟商用 CXL memory pool；实验重点也还是单机 memory-intensive workload。最后，demotion 仍主要借助 Linux LRU 行为完成，PACT 的主要新意集中在 promotion 与 ranking，而不是把整个 eviction 面都彻底重写。

## 相关工作

- _Liu et al. (OSDI '25)_ — Soar/Alto 说明了访问代价比 hotness 更重要，但它依赖更粗粒度或离线的推断；PACT 把 criticality 做成了在线 per-page 信号。
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid 关注访问延迟和积极迁移；PACT 则进一步引入 MLP-aware criticality，用更少的迁移拿到相近或更好的表现。
- _Lee et al. (SOSP '23)_ — Memtis 会动态分类页面和页大小，但整体仍属于 hotness 主导的设计空间，而不是直接估计 stall 贡献。
- _Al Maruf et al. (ASPLOS '23)_ — TPP 是较早面向 CXL 的透明页放置系统，PACT 则重新定义了“哪些页值得占用快层”这个排序信号。

## 我的笔记

<!-- 留空；由人工补充 -->
