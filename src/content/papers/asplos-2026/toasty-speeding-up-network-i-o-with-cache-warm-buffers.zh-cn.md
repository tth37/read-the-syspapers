---
title: "Toasty: Speeding Up Network I/O with Cache-Warm Buffers"
oneline: "Toasty 通过 LIFO 缓冲复用与自适应 RX ring 回填，把 AF_XDP 包缓冲维持在 cache-warm 工作集内，同时保住突发流量韧性。"
authors:
  - "Preeti"
  - "Nitish Bhat"
  - "Ashwin Kumar"
  - "Mythili Vutukuru"
affiliations:
  - "Indian Institute of Technology, Bombay, Mumbai, India"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790235"
code_url: "https://github.com/networkedsystemsIITB/toasty"
tags:
  - networking
  - kernel
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Toasty 针对的是 AF_XDP 一类高速包处理栈里的一个具体瓶颈：只有当最近收到的包缓冲在应用再次访问时仍留在 cache 中，DDIO 才真正有价值。它把“已释放缓冲的复用顺序”和“NIC RX ring 中同时在飞的描述符数量”一起控制起来。这样系统在稳态下能逼近小工作集的 cache 命中率，但在突发流量来临时又不会像永久小缓冲池那样把包直接丢掉。

## 问题背景

论文从一个很容易被忽视、但实际上决定性能上限的矛盾出发。AF_XDP、DPDK 这类 kernel-bypass 框架会在用户态预先分配一大块 packet buffer pool，把这些缓冲的描述符交给 NIC，然后让 NIC 直接 DMA 到这些缓冲里。若平台支持 Intel DDIO，这些 DMA 写入会优先落到 LLC，而不是立刻去 DRAM，因此应用读取包时本应从 cache 里受益。但只要活跃的 packet buffer 工作集超过了 DDIO 可利用的 LLC 空间，这个好处就会迅速消失。

作者强调了两个直接后果。第一是 leaky DMA：新包在到达时会把旧包从 LLC 中挤掉，而旧包甚至还没被应用处理，结果应用最后还是得从内存里把它们重新取回来。第二是 unnecessary writebacks：应用已经处理完并归还给 free pool 的缓冲，仍可能因为 cache 置换被写回内存；但这些内容在下一次 DMA 时本来就会被覆盖，因此这部分写回纯属浪费。前者浪费了 DDIO 想提供的“就地可读”优势，后者则浪费了 cache 与内存带宽。

最直观的解决办法是把 buffer pool 缩到足以塞进 cache。论文确实证明，对若干 AF_XDP 网络功能而言，在稳定负载下这样做能拿到最高吞吐。但这个解法会把问题推向另一个极端：在 microburst 或 Poisson 到达流量下，NIC 可能因为 RX ring 里没有足够的空缓冲可用而直接开始丢包。于是真正的问题并不是“缓冲池越小越好”，而是“在负载平稳时只让一小批 warm buffer 循环，在即将出现突发时再临时扩大工作集”。

## 核心洞察

论文的核心命题是：即便不改 commodity NIC 硬件，只要同时控制“缓冲被再次使用的顺序”和“当前在流通中的缓冲数量”，软件也能逼近理想的 cache-aware NIC 接口。顺序之所以重要，是因为刚被应用处理并归还的缓冲最有可能仍驻留在 LLC，甚至在更低层 cache 中。流通数量之所以重要，是因为如果硬件 RX ring 始终堆着几千个更冷的描述符，那么这些 warm buffer 即便被放到了 free pool 前端，也不会很快轮到它们。

这就导出了 Toasty 的两个关键判断。第一，把 free buffer pool 从 FIFO 改成 LIFO，让最近回收的缓冲优先重新进入服务。第二，不要永久把 RX ring 填满，而是依据最近的包到达速度和应用回收速度动态决定回填多少描述符，使在飞缓冲数量只跟当前需求大致匹配。两者结合后，系统在稳态下能把工作集收缩到一小片 cache-warm 区域，而在需要抵御突发时又能暂时拉入更多冷缓冲，不至于把 NIC 饿死。

## 设计

Toasty 构建在 AF_XDP 的 busy-poll、zero-copy 模式之上。第一处修改发生在用户态。AF_XDP 默认的 fill queue 是 FIFO：应用在 producer 端归还 free buffer，驱动随后从 consumer 端取走它们，而这些刚归还的缓冲通常要等整个队列轮一圈才会再次被 NIC 使用。Toasty 不移动真实包数据，只调整 buffer descriptor 的排列顺序。每当应用回收一批缓冲后，它会把这批描述符与 fill queue 头部的描述符做原子交换。这样 free pool 的行为就等价于 LIFO：最近刚被应用访问过的缓冲会最先成为下一批 DMA 目标。论文还特别说明，这样做能在 busy-poll 模式下避免额外同步，因为 producer 和 consumer 不会并发执行；如果换成 interrupt mode，就需要额外的 race protection，而论文并没有实现这一条路径。

第二处修改发生在内核驱动。仅靠 LIFO free pool 还不够，因为 NIC 的 RX ring 仍然是 FIFO。只要驱动继续像默认实现那样长期在 ring 里塞满大量描述符，那些刚被挪到 fill queue 前端的 warm buffer 仍会被一长串更冷的描述符挡在后面。Toasty 因此让驱动在每轮迭代里动态决定应该往 RX ring 里放多少 buffer。它依赖三个软件中现成可得的计数：应用自上一轮以来回收到 fill queue 的缓冲数量、NIC 在上一轮 DMA 进来的包数量，以及当前 RX ring 里仍可供 DMA 使用的空缓冲数量。驱动的目标是把 ring 里的可用缓冲大致维持在 `k * N_RXQ`，实现里取 `k = 10`。

这个回填策略会按负载分情况处理。如果当前可用缓冲低于目标值且最近流量较高，Toasty 会积极补充 RX ring，即便这意味着要从更深处拉入较冷的 buffer，也要优先保证不会因为 ring 耗尽而掉包。若最近链路利用率低于 50%，Toasty 就主要只回填那些刚被应用回收的 warm buffer，甚至本轮干脆不回填，从而让之前为突发而放进来的冷缓冲逐渐自然排空。论文还顺手修改了发送路径，使已发送描述符更快回到 free pool；这对 L2Fwd 这种需要把包重新发回网络的工作负载尤其重要。

## 实验评估

实验选择了六种访问模式差异很大的 AF_XDP 应用：NAT、IDS、decryption、L2Fwd、MICA 和 Maglev。主要测试平台是一台 Intel Xeon Gold 5418Y 服务器，配 Intel E810 100GbE NIC。默认基线使用 16,384 个 packet buffer 和 4,096 项 RX ring；另一组“ideal”基线则为每个应用手工挑选一个小得足以让工作集更贴近 DDIO cache 容量的静态配置，用来代表“吞吐最优但不一定抗突发”的方案。

最关键的结果是，Toasty 基本拿回了这个 hand-tuned 小缓冲配置的 cache 优势，却没有继承它的脆弱性。六个应用中，Toasty 相对默认 AF_XDP 的单核饱和吞吐提升最高达到 78%，同时 LLC miss 率接近零，表现与 ideal 配置相近。在利用 Intel MLC 制造的共置内存压力下，Toasty 对默认基线的优势进一步扩大到 30-86%。这一点很重要，因为它说明改进来源确实是“更好的 cache residency”，而不是某种偶然的调度副作用。

突发流量实验也很好地支撑了论文的中心论点。在 Poisson 到达模式下，Toasty 的持续吞吐甚至高于两个基线，因为它既避免了 ideal 小缓冲配置那样的显著 packet loss，又没有像默认大缓冲配置那样长期承受 leaky DMA 的代价。换成 no-drop-rate 指标后，相对排序依然不变。对论文给出的 microburst 与 Poisson 流量，Toasty 的掉包率整体上接近默认大缓冲方案，却远低于 ideal 小缓冲方案，这正是它想解决的矛盾。

我认为这篇论文的实验设计是比较扎实的。它不只比较两个显而易见的 AF_XDP 基线，还补充了 user-only LIFO 复用、DPDK stack mempool、ShRing、software prefetching，以及用户态和内核态两个组成部分的 ablation。这样的对照让主张更可信：单独做 LIFO 的确有帮助，但只有把自适应 RX-ring refill 也加上，系统才会获得完整收益。当然，实验边界也很清楚。大部分测试仍集中在一个 CPU 家族、一个 NIC 家族和一种 AF_XDP 运行模式上，所以论文证明的是一个很强的机制，而不是已经覆盖所有部署环境的通用结论。

## 创新性与影响

相对 _Tootoonchian et al. (NSDI '18)_，Toasty 的新意在于它不接受“把 RX 资源静态缩到能装进 LLC”为最终答案，而是保留一个较大的配置容量，却在运行时动态缩小真正活跃的工作集。相对 DPDK 的 LIFO mempool，它更关键的一步是指出：如果硬件 RX ring 仍然深排队，单改 free pool 顺序并不足以把 warm buffer 快速送回 DMA 路径。相对 _Pismenny et al. (OSDI '23)_ 和 _Liu et al. (SIGCOMM '25)_，它选择的是另一条路线：不依赖 smart NIC 新能力，也不重构 NIC-CPU 接口，而是在 commodity NIC 上用软件控制达到类似的 cache 效果。

因此，这篇论文对两类读者都有价值。对工程实践者来说，它像是一个可以直接部署到现有 AF_XDP 处理栈上的优化方案。对系统研究者来说，它证明了 packet-buffer lifetime management 本身就是一等设计变量，而不只是驱动实现里的小技巧。它的贡献本质上是一个新的软件机制，而不是新的负载模型或单纯的测量研究。

## 局限性

Toasty 的收益很大程度上建立在 DDIO 与 cache 驻留行为之上，因此它在其他平台上的表现取决于 DMA 落点和 cache 行为是否与论文里的 Intel 平台接近。实现本身也围绕 AF_XDP 的 busy-poll 模式设计；论文明确承认，若换成 interrupt mode，就必须加入更强的同步来规避 producer/consumer 竞争。驱动策略还依赖启发式参数，特别是 `k = 10` 和 50% 的链路利用率阈值；虽然敏感性实验显示这组参数附近都还算稳定，但它们毕竟不是严格证明得到的最优控制。

工作负载覆盖面也存在边界。对 compute-bound 的 decryption，以及需要走发送路径的 L2Fwd，收益明显更小，因为前者本来就不强依赖 packet I/O cache locality，后者虽然受益于更快回收，但又要承担更小 TX batch 带来的额外代价。实验主要还是单机、单 NIC、且以单核为主；多核扩展展示的是“每核一个 RX ring 的复制式扩展”，而不是更复杂的异构部署。最后，论文并没有说明这套机制在其他内核版本、其他 NIC 厂商、更复杂的多租户软件栈里是否还能保持同样效果。

## 相关工作

- _Tootoonchian et al. (NSDI '18)_ — ResQ 主张把 RX 资源缩到能装进 LLC，而 Toasty 保持较大的配置容量，却在运行时动态压缩活跃工作集。
- _Pismenny et al. (OSDI '23)_ — ShRing 依靠 smart NIC 支持在多核间共享 receive ring 来缩小 I/O 工作集；Toasty 则用纯软件在 commodity NIC 上追求类似的 cache 目标。
- _Alian et al. (MICRO '23)_ — IDIO 通过微架构支持减少 network I/O 导致的无效写回，而 Toasty 通过在缓冲变冷前尽快复用它们来软件化地削减这类浪费。
- _Liu et al. (SIGCOMM '25)_ — CEIO 通过硬件 credit 管理重构 NIC-CPU 数据路径，而 Toasty 完全不改硬件，只在软件里改变 RX ring 的回填策略。

## 我的笔记

<!-- empty; left for the human reader -->
