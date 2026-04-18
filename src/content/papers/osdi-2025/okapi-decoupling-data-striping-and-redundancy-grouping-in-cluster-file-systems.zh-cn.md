---
title: "Okapi: Decoupling Data Striping and Redundancy Grouping in Cluster File Systems"
oneline: "Okapi 将 stripe width 与 EC group width 解耦：前者按 IO 模式选，后者按耐久性选，从而减少 seeks 和转换 IO，且无需重写数据。"
authors:
  - "Sanjith Athlur"
  - "Timothy Kim"
  - "Saurabh Kadekodi"
  - "Francisco Maturana"
  - "Xavier Ramos"
  - "Arif Merchant"
  - "K. V. Rashmi"
  - "Gregory R. Ganger"
affiliations:
  - "Carnegie Mellon University"
  - "Google"
conference: osdi-2025
code_url: "https://github.com/Thesys-lab/okapi"
tags:
  - filesystems
  - storage
  - fault-tolerance
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Okapi 认为 stripe width 应该按 IO 行为选择，而 erasure-code group width 应该按 durability 与空间效率选择。它保留普通的 cell striping，但对独立选择的连续 block group 计算 parity，并用 group 推导与 partial parity 让这件事真正可实现。在 HDFS 上，它带来最高 80% 的读吞吐提升，并把 EC transition IO 大致砍半，而 Namenode heap 增幅不到 1%。

## 问题背景

论文研究的是以 HDD 为主、主要靠 erasure coding 保存冷数据的 cluster file system。在 HDFS、Ceph、Lustre、Colossus 这类系统里，同一个 `k` 同时决定 stripe width 和 redundancy-group width。这会把两个本来应该分开调优的问题绑死。stripe width 关心的是性能：窄 stripe 更适合小到中等请求，能减少 fan-out、seeks 和 tail latency；宽 stripe 更适合超大顺序读。group width 关心的则是空间开销、修复成本和可靠性。耦合设计迫使应用在这些目标之间做并不自然的折中。

它还让 EC transition 代价很高。文件因为数据变冷或磁盘故障率变化而切换编码时，系统不仅要重算 parity，还要把整个文件重新 striping，也就是把所有 data block 重新读写一遍。论文的判断是，这已经不是偶发操作，而是现代大集群里的高频后台任务。

## 核心洞察

Okapi 的核心洞察是：stripe boundary 和 redundancy-group boundary 没必要重合。只要 stripe 和 group 都满足 failure-domain 的放置约束，文件完全可以按最适合常见读取模式的方式 striping，同时按另一套更适合 durability 的边界来计算 parity。

让它可落地的关键，是把 redundancy group 定义成文件里连续的 data block。只要给 block 编上逻辑顺序号，block `x` 就属于 `ceil(x / stripe_width)` 对应的 stripe，也属于 `ceil(x / group_width)` 对应的 group。这样 group membership 就能从现有 stripe map 推导出来，而不需要再维护第二套完整 metadata。

## 设计

Okapi 保留了 striped DFS 原本的 block-and-cell 布局：文件仍被切成固定大小的 block，1 MB cell 仍按 round-robin 方式分布到 stripe 内各 block 上。不同之处在于 parity 现在按文件里每连续 `k` 个 data block 计算，即便这些 block 跨越了 stripe boundary。于是一个文件可以为了读效率采用 4-wide striping，同时为了耐久性采用 6-of-8 grouping。

最大的问题首先是 metadata。Okapi 把 HDFS 原本的 striped block group 拆成 data-stripe object 和 parity-group object，再根据 stripe width 与 EC scheme 推导两者关系。第二个问题是顺序写入。若 group width 大于 stripe width，朴素做法会让客户端缓存很多尚未受保护的数据。Okapi 用 partial parity 缓解这一点：每个 data block 一到，就立刻计算它对 parity 的贡献，把 partial parity 暂存在内存里，最后再合并成完整 parity。这样既控制了缓存，又不改变原有 durability 语义。

第三个问题是 degraded read 与 transition。某个缺失 block 的 reconstruction group 可能和当前读取的 stripe 不对齐，因此 Okapi 会缓存 degraded read 中已经取回的数据，避免重复读取。对 EC transition，Okapi 直接利用解耦布局：文件从 `k1-of-n1` 变到 `k2-of-n2` 时，只需按新的连续 group 重算 parity，而保留原有 striping。除非 failure-domain 约束要求额外搬移 block，否则只需要重写 parity。HDFS prototype 也尽量复用了现有 block-manager 和 recovery pipeline，而不是另起一套控制面。

## 实验评估

实验平台是一个修改后的 HDFS prototype，运行在 20 节点 HDD 集群上，使用 8 MB block、1 MB cell 和 40 GbE 网络。最核心的结果正好对应论文的主张：在 6-of-9 grouping 固定时，只要把 stripe width 调到更匹配请求大小的位置，读吞吐就能比 coupled 6-wide striping 最高提升 80%，同时 seeks/s 最多降低 70%。对 12-of-15 这类更宽的编码，论文给出了最高 115% 的吞吐提升。

Google-derived read-only workload 更能说明端到端价值。在那组请求上，Okapi 持续吞吐提高 55%，总 seeks 数降低 65%，整体完成时间缩短 36%。EC transition 也明显更便宜：对从 6-of-9 切到更宽方案、再切回来的 1 GB 文件，regrouping 相比 read-re-encode-write，大约把 disk 和 network IO 减半。论文建模的 Google 紧急切换场景里，总 transition IO 约下降 45%；用 Backblaze 故障数据驱动的 disk-adaptive redundancy 仿真里，平均 transition IO 约下降 38%。

开销方面，Okapi 让 Namenode 总 heap 只增加 0.74%，当 stripe width 与 group width 一致时，正常读写吞吐几乎不变。主要副作用出现在 degraded mode：某些不理想的 stripe/group 组合下，24 MB degraded read 会比 coupled baseline 慢 33%。

## 创新性与影响

Okapi 的新意不在于新的编码公式，而在于新的 file-system abstraction。它把 stripe width 变成纯粹的性能旋钮，把 group width 留给 durability 与容量效率。这个分离看起来简单，但大多数已部署 DFS 和不少 redundancy-management 方案都还默认继承旧有耦合。

它的价值也不仅是架构上的。对 DFS 设计者来说，论文说明 HDFS 风格系统可以用很小 metadata 成本完成解耦。对做 adaptive redundancy 的系统来说，它把 EC transition 从“重写整文件”尽量变成“只重写 parity”，直接改变了运维成本。

## 局限性

Okapi 最适合 HDFS 风格的工作负载：顺序写入、之后反复读取、几乎不再修改。对通用可变存储，它的说服力要弱很多。它的收益也主要来自 HDD 环境里 seek 成本很高这一现实；如果底层主要是 SSD，优势会明显变小。

它也没有消除所有 trade-off。stripe width 仍然需要认真 benchmark，选错会同时伤害正常读和 degraded read。论文自己的结果也表明，某些 decoupled 组合会让 degraded mode 的 tail latency 变差。此外，为了保持 failure-domain 分离，regrouping 有时仍需搬动 block，而实验毕竟只是 prototype 评估，不是生产部署报告。

## 相关工作

- _Shvachko et al. (MSST '10)_ - HDFS 是 Okapi 直接修改的 coupled baseline，也说明解耦可以嵌入现有 DFS 架构。
- _Kadekodi et al. (FAST '19)_ - HeART 证明了按磁盘可靠性调整 redundancy 的价值；Okapi 则降低这种调整带来的读路径与 transition 成本。
- _Kadekodi et al. (OSDI '22)_ - Tiger 推动了更灵活的 disk-adaptive redundancy，而 Okapi 让 striped DFS 里的 group-width 变化更便宜。
- _Kim et al. (SOSP '24)_ - Morph 降低 parity conversion 的成本，Okapi 则进一步去掉了 transition 时重写 file data 的必要。

## 我的笔记

<!-- 留空；由人工补充 -->
