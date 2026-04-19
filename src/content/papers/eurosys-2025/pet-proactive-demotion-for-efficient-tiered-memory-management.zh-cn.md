---
title: "PET: Proactive Demotion for Efficient Tiered Memory Management"
oneline: "PET把 anonymous mmap 区域抽成 P-block，并分阶段完成 demotion 与 promotion，在不明显放大 slow-tier stall 的前提下大幅压低 fast-memory 占用。"
authors:
  - "Wanju Doh"
  - "Yaebin Moon"
  - "Seoyoung Ko"
  - "Seunghwan Chung"
  - "Kwanhee Kyung"
  - "Eojin Lee"
  - "Jung Ho Ahn"
affiliations:
  - "Seoul National University, South Korea"
  - "Samsung Electronics, South Korea"
  - "Inha University, South Korea"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717471"
tags:
  - memory
  - kernel
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PET 认为，tiered memory 里真正限制主动 demotion 效果的，不是阈值调得不够激进，而是 OS 一直在用 page 这种过细的管理单位。它从 anonymous `mmap` VMA 中抽取更接近分配边界的 P-block，用分阶段冷度判定来决定 demotion，再用 canary fault 驱动 promotion，把 slow tier 的代价尽量挡在性能临界点之外。作者在 Linux 6.1.44 加上 Optane 慢层的原型上报告：当工作集能放进 fast memory 时，平均可节省 39.8% 的 fast memory、平均性能只降 1.7%；当工作集放不下时，相比默认 Linux，slowdown 可再降低 31%。

## 问题背景

很多 OS-level tiered-memory 方案本质上还是被动的。它们通常等到 fast memory 的空闲量跌到 Linux watermark 之类的紧阈值，才开始把冷页往慢层赶。这样做的问题并不神秘：一旦热点数据突然出现，promotion 和新分配就会和 demotion 本身抢同一小块 DRAM 余量，关键路径里还会多出迁移开销。

已有 proactive demotion 工作当然意识到了这一点，但大多仍围着 page 粒度打转。4 KB page 的好处是精确，可代价是扫描、记账和迁移都很碎，想把 demotion 做得更激进时，这套控制路径本身就会变贵。论文前面的 PMU 分析给出一个不同的观察：在不少 benchmark 里，热度往往不是在 page 内随意散开，而是沿着更大的分配单位聚集。问题于是变成了另一个方向的系统设计题：OS 看不到高级语言对象，怎样才能在不要求应用配合的前提下，近似抓住这种 allocation-scale locality？

## 核心洞察

PET 的答案是，不要把 page 当成唯一自然单位，而要先从内核已经掌握的地址空间结构里，提炼出更接近内存分配边界的区域。论文把新建的 anonymous `mmap` VMA 当成这种代理，再把它保存成 P-block。对评测工作负载来说，这个代理不算粗糙：作者报告 P-block 与 `malloc()` 对象的重叠度超过 97%。

但 P-block 变大以后，误判的代价也会变大，所以 PET 的关键不只是换单位，而是把判定流程做成逐步加严的多阶段机制。先用很便宜的采样去筛出可能很冷的 P-block；再把它们拆成更小的 temporary block 看内部冷热是否混杂；最后只对少量 canary page 制造 fake fault，确认这些区域是否真的冷到可以整体 demote。换句话说，这篇论文最重要的命题不是「区域比页面更好」，而是「只要 region 选得像分配边界，再配合分阶段验证，主动 demotion 才能既激进又不至于误伤性能」。

## 设计

PET 在内核里新增了 P-block 这层元数据。当 Linux 为一个新的 anonymous `mmap` 分配 VMA 时，PET 会在后续 VMA merge 发生前先把这段边界抓下来。考虑到超大分配内部可能冷热混杂，系统还会先把过大的 P-block 继续切开；默认最大 P-block 是 1 GB。

后台线程 `kdemoted` 负责维护 P-block 状态和执行 demotion。它在每个 sampling interval 里只随机抽取每个 P-block 的一页，清掉这页的 access bit，再在更长的 scan interval 上汇总结果。没有被观察到访问的 P-block 不会立刻 demote，而是依次经历 `NORMAL`、`PHASE1`、`PHASE2` 和 `DEMOTED` 四个状态。

真正的机制价值就在这条状态机里。进入 `PHASE1` 后，PET 会把一个冷疑似 P-block 再拆成多个 temporary block，因为一个大区域里可能同时塞着热段和冷段。若扫描后冷 temporary block 的总大小仍大于热块，它就进入 `PHASE2`。这一步 PET 会把每个 temporary block 的 10% 页面当作 canary page 先行 demote，并设成 `PROT_NONE`，借助随后的 fake fault 去确认这些 supposedly cold 区域是否真在被重新访问。若冷块仍占优势，PET 会把相邻冷块重新合并为新的冷 P-block 并真正 demote，把访问过的子块恢复成 `NORMAL`。相比简单阈值策略，这套流程更复杂，但它正是 PET 能在 region 粒度上保守落地的原因。

promotion 由独立的 `kpromoted` 处理。canary page 上的 fake fault 只负责给对应 P-block 记一次访问，不会在 fault handler 里直接把整个区域搬回 DRAM。PET 先用 3% 的 tolerable slowdown 和 8.3 微秒的 mis-demotion penalty 算出系统级 promotion 预算，得到每秒 360 次 fault 的目标速率；再按 demoted P-block 的大小，把这个预算分摊成各自的 `th_block`。一旦某个块自己的阈值，或者整个 interval 的全局阈值被打满，`kpromoted` 就把该 P-block 整体 promote。除此之外，PET 还加了 file-page demotion：对 `open_count == 0` 的文件，在后台把其缓存页视作冷数据处理。

## 实验评估

实验平台是一台双路 Xeon Platinum 8260，配 64 GB DRAM fast tier 和 256 GB Intel Optane DC Persistent Memory slow tier。工作负载覆盖 Graph500、SPECspeed 2017、GAPBS、liblinear、Redis+YCSB、XSBench、相位切换 microbenchmark，以及一个专门用来刁难 PET 的 Java H2 场景。基线也算完整，包括 AutoTiering、TPP、Thermostat、DAMON-based tiering，以及基于 MGLRU 的 proactive demotion。

当总工作集超过 fast-memory 容量时，PET 的证据最有说服力。作者把多组 workload 调到大约 1.5 倍 fast memory 大小后，PET 相对 Fast-only 理想情况平均只慢 5.7%，但平均只用了 28.4 GB fast memory，比非 proactive 方案少了 21 GB 以上。相位变化实验更能说明它为什么有效：在 `XSBench` 进入前，PET 先把 `imagick_s` 的 fast-memory 占用压掉 90.7%，于是两者分别只损失 2.3% 和 1.9% 性能；默认 Linux 和 AutoTiering 在同一设置下，会让 `XSBench` 额外慢 17.2%。

更重要的是，就算工作集本来就能装进 fast memory，PET 仍然能把 DRAM 占用继续压下去，而不是像传统方案那样什么都不做。关闭 file-page demotion 时，它相对 Base 仍能节省 30.7% fast memory，平均只损失 1.40% 性能。打开 file-page demotion 之后，论文给出的总结果是平均节省 39.8%，最高 80.4%，平均性能只降 1.7%；在 `liblinear` 和 GAPBS 上，这个数字进一步变成 49.3% 的节省和 1.6% 的 slowdown。reactiveness 实验也很关键：PET 达到与 page-granularity MGLRU proactive demotion 相同的峰值吞吐，反应时间只慢 1 秒，但扫描的页面数只有后者的 0.87%。

整体上，这组实验是支持中心论点的。不过也要看清楚，论文证明的是一整套设计组合的价值：P-block capture、multi-phase demotion、canary-based promotion，加上 file-page 策略共同成立，而不是某一个单独小技巧就足以带来全部收益。

## 创新性与影响

相对 Thermostat、TPP 和 MEMTIS，PET 的创新点并不只是更激进地提前 demote，也不是又换了一套 page hotness 信号。它真正重画的是 OS-level tiered memory 的管理单位：不再默认 page 才是唯一合理粒度，而是先用 VMA 抽出 allocation-shaped region，再为这种更大粒度专门设计 demotion 与 promotion 的控制路径。

这会对后续 Optane 类或 CXL 类 tiered-memory 系统有持续影响。PET 给出了一条很明确的判断标准：如果 coldness 的确沿着逻辑分配边界成团出现，那么 page 粒度扫描可能从一开始就选错了抽象层。即便后续系统不再用 VMA 当代理，而是换成更精细的 region extractor，这篇论文仍把一个原本常被视作实现细节的问题抬成了核心机制问题。

## 局限性

PET 最大的边界也正好来自它最重要的假设：allocation unit 内部要存在足够强的访问局部性。Java H2 这个对抗场景把问题暴露得很清楚。PET 在那里仍比 DAMON 快接近 2 倍，但依赖 page 粒度判断的 MGLRU-based proactive demotion 仍比 PET 高 7%，因为 JVM 管理的大堆空间并不会天然保留同样清晰的 allocation-locality 信号。

部署层面也有现实成本。PET 需要新的内核元数据、两条后台线程、多组可调参数，以及一个建立在固定 tolerable slowdown 假设上的 promotion budget。file-page demotion 目前也比较保守，只处理 `open_count == 0` 的文件。作者还明确承认，PET 默认 hot working set 能装进 fast memory；一旦超过，就可能发生 thrashing，而论文只是把反馈式暂停 PET 当成 future work。最后，实验主要集中在一套 Intel+Optane 平台上，不同慢层介质上的阈值和收益未必完全同形。

## 相关工作

- _Agarwal and Wenisch (ASPLOS '17)_ - Thermostat 也做 proactive demotion，但它主要围绕 huge page 采样和 page fault 阈值展开；PET 则先构造 allocation-shaped region，再把 canary fault 放到最后一道验证环节。
- _Al Maruf et al. (ASPLOS '23)_ - TPP 的目标是提前留出一小块可用 fast memory 供 promotion 和新分配使用；PET 更进一步，它在没有即时空间压力时也持续 demote，直接降低 steady-state 的 fast-memory footprint。
- _Lee et al. (SOSP '23)_ - MEMTIS 关注的是 THP 环境里的页面分类与页大小决策，而 PET 的主贡献是把 tiered-memory 管理单位从 page 改成 VMA 派生的 region。
- _Moon et al. (IEEE CAL '23)_ - ADT 已经提出过利用 allocation unit 做 proactive demotion 的直觉；PET 则把这个思路扩展成完整内核机制，包括动态 P-block capture、block splitting，以及更及时的 region-granularity promotion。

## 我的笔记

<!-- 留空；由人工补充 -->
