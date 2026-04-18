---
title: "An Efficient Cloud Storage Model with Compacted Metadata Management for Performance Monitoring Timeseries Systems"
oneline: "CloudTS 把标签元数据全局去重，再用压缩 TTMapping 和分组 TSObjects 做两段式查询，在生产环境里把 Cortex 查询提速 1.43x。"
authors:
  - "Kai Zhang"
  - "Tianyu Wang"
  - "Zili Shao"
affiliations:
  - "The Chinese University of Hong Kong, China"
  - "Shenzhen University, China"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - databases
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CloudTS 的核心做法，是把云端监控 TSDB 的“文件内元数据”改造成“全局元数据 + 分组数据对象”。它用全局 `TagDict` 去重标签，用压缩的 `TTMapping` 把标签过滤快速映射到 timeseries ID，再只并行抓取相关的 `TSObjects`。论文把它集成进 Cortex 并跑在 EC2 + S3 上，在选定的生产式工作负载中把查询平均提速 `1.43x`。

## 问题背景

这篇论文抓住的是一个很实际的错位：Prometheus、Cortex 这类监控 TSDB 的本体设计，默认建立在本地时间分区文件之上；而 Amazon S3 之类云对象存储提供的是高延迟对象访问，而不是廉价的块级随机读取。在传统 layout 里，一个时间分区会把 metadata 和 data chunks 一起打进 block。把这个 block 直接搬到 S3 之后，即使查询只需要少量 timeseries，也往往得先把更大的对象取回、解析 index，再丢掉大部分 payload。也就是说，真正先发生的不是“算得慢”，而是“拿错了东西”。

性能监控 workload 还把这个问题进一步放大。容器和微服务会让 timeseries 高基数化，而且生命周期很短，今天存在的 series 明天就可能消失。论文引用的 ByteDance 例子里，每天要处理超过一百亿个 distinct timeseries。这样的环境下，标签信息不只是辅助描述，而是 metadata 的主体：论文称 tags 能占到总 metadata 大小的 `80%` 以上，其中约 `73%` 会重复出现。现有工作往往擅长压缩数据点，却不擅长消除标签冗余，也不擅长避免跨时间分区反复读取这些标签。

直接套用现成云格式也不够。把 Cortex block 原样映射成 cloud object，会保留原有的 read amplification。Apache Parquet 虽然能压缩文件，但针对某个 series 和某个时间范围的查询，仍可能拖回无关的行或列。JSON Time Series 把每个 series 单独存起来，避开了一部分 block 级放大，却让 tag-based query 退化成大量对象扫描。CloudTS 真正想回答的，是监控 TSDB 在 object storage 上应该怎样重排 metadata 与 data，才能让“按标签过滤的历史查询”变得天然适合云。

## 核心洞察

论文最关键的判断是：在 cloud object storage 上，查询慢的主因往往不是 chunk 解压，而是系统在知道“哪些 chunk 值得拿”之前，就已经为重复 metadata 支付了远程访问代价。只要 metadata 仍然分散在每个时间分区 block 里，系统就会反复走一遍“取回对象、解析元数据、筛掉无关数据”的长路径。因此，真正该全局化优化的是 metadata，而不是只在 data layout 上做小修小补。

CloudTS 把这个想法拆成三层。第一层，标签不再在每个分区重复存，而是进入全局去重后的 `TagDict`。第二层，每个时间分区维护一个紧凑且可查询的标签到 timeseries 映射，让系统能在触碰 data object 之前先缩小候选集。第三层，真实 chunk 数据被组织成既保留时间局部性、又避免“大对象”和“单 series 小对象”两个极端的 `TSObjects`。这样一来，查询路径就从“先把块拉回来再筛”变成“先查 metadata，再精确拉对象”，这正是 object store 更擅长支持的模式。

## 设计

CloudTS 首先把存储模型拆成“全局元数据”和“分区局部数据对象”两部分。第一个关键结构是 `TagDict`，它是一个类似 Patricia trie 的全局字典，统一管理 metric name、tag key 和 tag value。每个 tag pair 在叶子节点拿到一个全局唯一编码，同时保存双向指针：查询规划时可由 tag pair 找到编码，返回结果时又能从编码恢复成人类可读的 tag。对于每个时间分区，CloudTS 还维护一个 local tag array，只保留该分区真正出现过的 tags，从而避免把无关词汇反复带进查询路径。

第二个关键结构是 `TTMapping`。它针对一个时间分区维护一个二维 bitmap：行是 timeseries ID，列是 tag 编码，`1` 表示这个 series 带有这个 tag。这样一来，传统 TSDB 中分散在 symbol table、posting 和 series metadata 里的信息，被压缩成一个既能回答“这个 series 有哪些 tags”，又能回答“这些 tags 对应哪些 series”的统一结构。考虑到这类矩阵通常非常稀疏，论文进一步提出 `TMMC` 压缩方法，只保留置位位置和每行偏移，也就是 `ind` 与 `ptr` 两个数组。这样既保留了查询友好性，也显著减小了元数据体积。

在 `TTMapping` 之上，CloudTS 还做了 timeseries grouping。理想状态下，互斥标签会把整个矩阵拆成几个互不重叠的子块；现实监控数据当然没这么干净。于是论文转而利用 tag frequency 和共享 tag name 来构造“足够有用”的 group：有些 tags 选择性很强，适合过滤；有些 tags 很常见，不适合过滤，但能帮助把 series 归到便于并行访问的小组里。这部分设计没有前两项那么漂亮，却很符合系统论文的风格，因为它正面承认 workload 分布并不规整，而优化要围绕实际分布来做。

真正的数据存储单元是 `TSObject`。对一个时间分区里的一个 timeseries group，CloudTS 把压缩后的 chunks 按 timeseries ID 和时间顺序组织到同一个 object 里。这个布局试图在两个坏极端之间取平衡：对象太小，会放大 metadata lookup 成本；对象太大，又会加剧 read amplification。后台 daemon `CloudWriter` 会在本地 block 变成 immutable 后被唤醒，更新 `TagDict`，构建 `TTMapping`，再按时间顺序读取 chunks 并生成 `TSObjects` 上传，而不会阻塞前台监控服务。查询则由 `CloudQuerier` 执行：它先缓存或拉取相关分区的 local tag array 与 `TTMapping`，把标签谓词解析成 timeseries ID，然后只对需要的 `TSObjects` 和目标时间窗口发起并行对象请求。

## 实验评估

这篇论文的评估，对一个 storage-format 方案来说算比较完整。作者用 Go 实现了原型，并把它集成到 Cortex `1.16.0` 中，运行环境是 EC2 Ubuntu 服务器加 Amazon S3。生产式实验里，一台 EC2 节点监控十台 Debian 服务器，而每台服务器上跑十个 Node Exporter，总共 `100` 个 targets。系统连续采集 `48` 小时之后，再对 `cpu_avg` 和 `memory_usage_avg` 发起近期历史查询。结果是 CloudTS 相比原始 Cortex 平均提速 `1.43x`；同时吞吐曲线显示，后台 `CloudWriter` 每两小时上传一次数据，并不会明显干扰并发查询。

更有说服力的是合成 workload 实验。作者采集了 `24` 小时、共 `500K` 条 timeseries，并跑了八种 TSBS 查询模式，覆盖低基数区间查询、阈值过滤以及跨主机聚合等场景。Table 4 中 CloudTS 在全部模式里都是最快的：例如 `1-8-1` 从 `0.1452s` 降到 `0.1258s`，`high-all` 从 `0.2351s` 降到 `0.1884s`，`cpu-all-8` 从 `0.2549s` 降到 `0.2331s`。但比延迟数字更关键的，是它真正减少了“拿回来的无关数据”：在 `high-all` 上，访问数据量从 `626.29 MB` 降到 `305.73 MB`；在 `cpu-all-8` 上，则从 `695.65 MB` 降到 `352.49 MB`。这组结果很好地支持了论文的中心论点：CloudTS 的收益主要来自更少的对象读取，而不是更花哨的解压技术。

后续实验基本都在强化同一件事。并行 cloud requests 越多，查询越快，尤其是大范围扫描；在 `high-all` 上，CloudTS 的平均网络吞吐达到 `230.735 MB/s`，而 baseline 只有 `102.472 MB/s`。CPU 与内存开销也更低：`high-all` 场景下，CloudTS 的 CPU 利用率是 `45.7%`，内存是 `3.35 GB`，而 Cortex 分别是 `60.4%` 和 `5.21 GB`。论文还补充了对 InfluxDB `3.x` 的比较，在更重的历史查询上有 `15.5%` 和 `6.8%` 的优势；另外在长时间保留与高 label churn 场景下，每分区 metadata 内存仍保持在可控范围内，前者平均约 `21 MB`，后者低于 `30 MB`。

## 创新性与影响

这篇论文的创新点，不是提出某种新的 chunk 压缩算法，也不只是说“监控数据可以上云”。它真正的贡献，是把四个设计动作绑定成一个完整的 cloud storage model：全局去重的标签字典、分区局部的压缩标签到 series 映射、按 group 组织的 chunk objects，以及“先查 metadata、再读 data”的查询路径。相比单纯把 Parquet、JSON 或 Cortex block 搬到对象存储里，这是一套更明确、更系统的重构。

这会对长保留周期监控系统、cloud-native TSDB，以及研究 metadata-heavy storage workload 的系统研究者都有参考价值。论文尤其重要的一点，是把“metadata redundancy”而不只是“chunk layout”定义成 object storage 上历史监控查询的主矛盾。即使真实系统不完整照搬 CloudTS，它也给出了一个很明确的工程信号：如果想把云端监控查询做快，首先要优化的是 metadata 路径。

## 局限性

这篇论文最强的是读路径设计，对系统其他生命周期环节的覆盖则弱一些。`CloudWriter` 被描述成后台 daemon，但论文没有系统性量化写路径额外成本、故障恢复代价，以及 `TagDict` 或 `TTMapping` 在损坏、丢缓存之后要花多大代价重建。它的核心数据模型也建立在 immutable partition 之上，因此和 Prometheus/Cortex 这类 block pipeline 非常契合，但对更新语义更重的系统未必自然适配。

评估也存在边界。Parquet 和 JTS 的对比，是把这两种格式嵌进修改后的 Cortex，而不是和各自独立优化过的完整系统正面对比，因此这些结果更像“格式层面对照”而不是产品层面对照。InfluxDB 的比较更接近真实竞争者，但仍然集中在 CloudTS 最擅长的历史扫描场景。最后，高 label churn 实验也表明，当每个分区注入数百万短生命周期 timeseries 时，查询延迟和 metadata 内存都会上升；作者的缓解手段是把分区缩细到 `15` 分钟并频繁 flush，这说明设计虽然能把每分区内存压住，却仍然对 workload 调参比较敏感。

## 相关工作

- _Shi et al. (SoCC '20)_ — ByteSeries 在内存型监控 TSDB 中同时压缩 metadata 和 datapoints；CloudTS 则面向 cloud object storage，并把标签去重提升到跨时间分区的全局层次。
- _Jensen et al. (ICDE '21)_ — ModelarDB+ 通过模型压缩和分组相关 series 来节省存储；CloudTS 的重点则是重排 metadata 与 object layout，服务于 tag-based 的云端查询。
- _An et al. (FAST '22)_ — TVStore 关注用 time-varying compression 限制存储增长，而 CloudTS 主攻 metadata redundancy 与远程读取放大。
- _Xue et al. (IPDPS '22)_ — TagTree 为 time-series database 提供全局 tagging index；CloudTS 把相近思路放进按分区组织的 cloud-object layout，并与 `TSObjects` 绑定起来。

## 我的笔记

<!-- empty; left for the human reader -->
