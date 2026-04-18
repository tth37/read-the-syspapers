---
title: "Getting the MOST out of your Storage Hierarchy with Mirror-Optimized Storage Tiering"
oneline: "MOST 只为一小部分热点数据保留跨层镜像，再通过动态路由与写入分配而不是大规模迁移来平衡两层设备负载。"
authors:
  - "Kaiwei Tu"
  - "Kan Wu"
  - "Andrea C. Arpaci-Dusseau"
  - "Remzi H. Arpaci-Dusseau"
affiliations:
  - "University of Wisconsin–Madison"
  - "Google"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - storage
  - caching
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

MOST 在经典两层存储分层之上增加了一个很小的热点镜像类。它不再主要依赖块迁移来平衡负载，而是根据哪一层当前端到端延迟更低，直接调整请求路由和新写入的落点。论文将其实现为 CacheLib 中的 Cerberus，结果显示它既比完整 caching 或 mirroring 更接近 tiering 的空间效率，又能在静态和突发工作负载上稳定超过此前的 tiering 与 caching 基线。

## 问题背景

像 Optane、快速 NVMe SSD、SATA SSD，甚至 NVMe over Fabrics 暴露出来的远端设备，已经不再构成一个清晰的“快层绝对快、慢层绝对慢”的金字塔。它们的延迟和带宽区间开始重叠，而且有效性能比会随着请求大小、读写比例和并发度变化。传统的层次管理方法默认设备差距稳定，但现代设备并不是这样。

单副本 tiering 的优点是省空间，但它只能靠层间迁移来重新分配负载，因此对突发流量反应慢、设备写入量高，而且后台迁移会干扰前台 I/O。多副本方法则在另一端失衡：完整 mirroring 太浪费容量，基于 caching 的设计又常常无法真正利用容量层，尤其是在写密集负载下。论文的核心问题是，如何既利用两层设备的带宽，又不承担 tiering 的迁移成本或 mirroring 的复制成本。

## 核心洞察

MOST 的关键洞察是：存储层次不需要在“纯 tiering”和“完整 mirroring”之间二选一。只要把最热的一小部分数据做成跨层双副本，就足以把冗余变成快速调节负载的控制面。一旦热点同时存在于两层设备上，系统就能立刻调整读流量，甚至部分写流量，而不是等待迁移慢慢收敛。

它的优化目标也很直接：让 performance device 和 capacity device 的端到端延迟尽量接近。如果 performance device 仍然更快，就把镜像数据流量留在那里；如果它变慢，就把一部分镜像请求和一部分新分配写入转到 capacity device。这样，大部分数据依旧保持单副本，容量效率接近经典 tiering，但系统已经拥有了快速反应负载变化的能力。

## 设计

MOST 把整个存储空间分成两个类。镜像类中的数据在两层设备上都保留副本；分层类中的数据只保留一个副本，其中 warm data 留在 performance device，cold data 留在 capacity device。Cerberus 以 2 MB segment 为粒度统计热度，用每段的访问计数来决定哪些 segment 值得进入镜像类。论文实验里，镜像类最多占总容量的 20% 就足够了。

系统的核心控制量是 `offloadRatio`，即把镜像请求或新写入直接送往 capacity device 的概率。Cerberus 每 200 ms 运行一次固定线程的优化器，从 Linux block layer 计数器估算各设备的端到端延迟，用 EWMA 平滑后，再以 0.02 为步长调节 `offloadRatio`。因此，在低负载下 MOST 看起来像普通 tiering，尽量把访问留在快层；在高负载下，它则把足够多的流量卸到容量层，使两层延迟重新接近。

迁移逻辑被刻意限制。如果镜像类过小，Cerberus 就把 performance tier 中最热的 segment 复制到 capacity device 上；如果镜像类已经满了，就用更热的分层段替换掉最冷的镜像段。它只会把数据从当前高延迟设备上移走，避免控制动作本身继续放大瓶颈。

论文里最有特色的部分是写路径。对于镜像类数据，Cerberus 不会每次都同时更新两个副本，而是只更新一个副本，并用 4 KB subpage 粒度的 invalid/location 位图跟踪哪些子页在哪一层仍然有效。这样，写入也能被分流，而不是被迫同时打到两层设备上。后台 cleaner 只会为 rewrite distance 足够大的块补齐副本，避免清理那些很快又会被覆盖的数据。论文还允许设置最大 `offloadRatio`，在容量层尾延迟明显更差时保护热点数据的 tail latency。

## 实验评估

作者在 CacheLib 中新增约 1.5K 行代码实现 Cerberus，并在同一框架里实现 HeMem、BATMAN、Colloid 和 Orthus 作为公平基线。实验机器是一台 40 核 Xeon、64 GB DRAM 的服务器，测试两种本地两层组合：750 GB Optane + 1 TB NVMe，以及 1 TB NVMe + 1 TB SATA。

静态实验基本支撑了论文主张。在合成工作负载上，Cerberus 相比文中基线最高获得 2.34x 吞吐提升，并把 P99 延迟最高降低 75%。与 Orthus 的对比尤其说明问题：在一个随机读负载里，Orthus 要保留 690 GB 的重复数据才能达到接近吞吐，而 Cerberus 只镜像 50 GB。与 Colloid 相比，Cerberus 的优势主要来自它不需要在设备延迟波动时触发大量迁移。

动态实验更强。对于突发负载，Cerberus 通过调整路由可以在 10 秒内完成适应；如果把 Colloid 的迁移速率限制在 100 MB/s，它可能需要 800 多秒才能完成同样的负载转移。在动态工作负载中，Cerberus 平均只向容量层镜像 86 GB 数据，而 Colloid 平均需要向 performance tier 迁移约 252 GB、向 capacity tier 迁移约 229 GB。论文进一步指出，这些额外写入会把容量层 SSD 的额定寿命从三年压缩到 129 天。

端到端的 CacheLib 评测也比较扎实。跨生产工作负载，Cerberus 的吞吐最高提高 1.86x，P99 GET 延迟最高降低 90%；按四个生产 trace 平均，它相对最佳基线把平均延迟再降 14%，把 P99 延迟再降 19%。这些结果覆盖了随机与顺序访问、写密集场景、动态 bursts 和真实 cache traces，但整体仍然主要是围绕两层、cache-oriented、单机平台展开。

## 创新性与影响

相对于 _Raybuck et al. (SOSP '21)_ 的 HeMem 和 _Vuppalapati and Agarwal (SOSP '24)_ 的 Colloid，MOST 并不是在单副本 tiering 里再找一个更聪明的迁移策略，而是直接改变布局，让少量稳态冗余本身变成快速调节负载的机制。相对于 _Wu et al. (FAST '21)_ 的 Orthus，它也不需要把整个性能层都拿来存重复副本，并且能够平衡写入而不仅是重定向读取。

因此，这篇论文提供的是一种新的 storage-hierarchy mechanism。它对 flash cache、tiered key-value store，以及位于应用与异构设备之间的 block layer 都有参考价值。更重要的是，它把跨层冗余重新定义成一种带宽管理原语，而不仅仅是可靠性或命中率工具。

## 局限性

论文明确只做了两层设计，多层扩展被留到未来工作。它的一致性方案也不完整：作者提到，若要让迁移引起的映射更新具备更强保证，可能需要额外的 write-ahead log，但论文没有实现或评估这部分。Cerberus 目前也工作在 block 层之下，并不知道请求属于哪个租户，因此没有提供跨应用的性能隔离或 QoS 机制。

实验层面也有边界。实现嵌在 CacheLib 的用户态存储层中，因此它最有说服力的对象仍是 cache-like workload，而不是一般性的 block 或 filesystem 栈。尽管动机部分讨论了远端与 disaggregated device，主体实验仍只使用本地 Optane、NVMe 和 SATA 组合。这个方案还默认一个较小的镜像类就能覆盖真正需要快速重路由的热点区域；如果 hot set 扩散，或者写入频繁让镜像副本不断失效，它的收益就会下降，而清理压力会升高。

## 相关工作

- _Raybuck et al. (SOSP '21)_ — HeMem 采用单副本、基于热度的 tiering，因此只能通过层间迁移来重新分配负载。
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid 同样试图平衡异构层之间的访问延迟，但它仍是单副本设计，所以在突发负载下要付出很重的迁移时间和写放大代价。
- _Wu et al. (FAST '21)_ — Orthus 用 non-hierarchical caching 在现代存储设备间重定向读流量，但它会占用性能层容量来保存重复副本，而且写路径处理较弱。
- _Xiang et al. (OSDI '24)_ — Nomad 在迁移期间保留临时双副本，而 MOST 则把选择性的稳态镜像直接做成主要的负载均衡机制。

## 我的笔记

<!-- 留空；由人工补充 -->
