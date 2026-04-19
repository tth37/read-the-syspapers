---
title: "Chrono: Meticulous Hotness Measurement and Flexible Page Migration for Memory Tiering"
oneline: "Chrono不用粗粒度计数器，而是用页的 idle time 来判断冷热，再自适应调节升降迁移，把真正该留在DRAM的页挑出来。"
authors:
  - "Zhenlin Qi"
  - "Shengan Zheng"
  - "Ying Huang"
  - "Yifeng Hui"
  - "Bowen Zhang"
  - "Linpeng Huang"
  - "Hong Mei"
affiliations:
  - "Department of Computer Science and Engineering, Shanghai Jiao Tong University"
  - "MoE Key Lab of Artificial Intelligence, AI Institute, Shanghai Jiao Tong University"
  - "Intel"
  - "Shanghai Jiao Tong University"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717462"
code_url: "https://github.com/SJTU-DDST/chrono-project"
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

Chrono把页冷热判断从计数器改成了 Captured Idle Time，也就是一次扫描把页标成不可访问之后，到下一次缺页触发之间的时间差。这样一来，热度分辨率不再绑死在扫描强度上，系统能在 base-page 粒度把 hot page 和 warm page 分开，并把阈值、升迁速率和降迁策略一起在线调节。论文在 DRAM 加 Optane PMem 的平台上报告，Pmbench 吞吐最高比 Linux NUMA balancing 高 216%，平均和 P99 延迟最高分别下降 68% 和 79%。

## 问题背景

今天的数据中心越来越常见的形态，是用 DRAM 搭配更大但更慢的字节可寻址内存层，例如 Optane PMem，以及作者明确提到会到来的 CXL memory。难点不在于系统会不会迁页，而在于它能不能把真正值得留在 fast tier 的页挑出来。Linux 自带的 NUMA balancing 原本是为跨 socket 本地性设计的，把 slow tier 视作没有 CPU 的 NUMA node 之后，任何一次访问都像是 promotion 信号，这更接近 MRU，而不是频率驱动的 tiering。

论文对现有方法的批评很集中。Auto-Tiering 和 TPP 靠 page-fault counter，Multi-Clock 靠 accessed bit 和 LRU 近期性；这些方法知道页最近碰没碰过，却很难把每分钟几十次访问和几百次访问分开。PEBS 路线例如 Memtis 更接近真实频率，但采样预算有限，落到 4 KB base page 时统计会变稀，热区还会被 huge page 粒度放大。作者的动机实验说明了为什么这不是小误差：NVM 上平均每页仍有 20-40 次每分钟访问，最热的 10% 页还能达到平均值的 5.5 倍。只靠粗粒度计数，迁页策略天然会失真。

## 核心洞察

Chrono真正抓住的是一个替换测量基元的思路：别去数一页被访问了多少次，而是去看它在下一次被访问前空闲了多久。系统记录扫描时刻，再记录同一页下一次 page fault 的时刻，两者相减就是 CIT。CIT 越短，说明这页越热；CIT 越长，说明它更冷。关键在于，这个信号来自 timer，而不是访问计数，所以频率分辨率和扫描频率解耦了。哪怕扫描周期仍是 60 秒，系统照样能借助毫秒级 CIT 去区分亚秒级热度差异。

而且 Chrono 没把更细的测量单独拿来用。它把两轮筛选、迁移限速、跨 tier 热度统计和主动 demotion 组合成一个闭环控制。论文最重要的命题其实是：精细测量和自适应控制必须一起设计。

## 设计

Chrono建立在 Linux 的 NUMA tiering 框架里，核心有三块。第一块是 Ticking-scan。它像 NUMA balancing 一样周期性扫描进程地址空间，把页临时标成 `PROT_NONE`，但对 slow-tier 页额外记录扫描时间戳。下次访问触发 fault 时，内核再记下 fault 时间，两者相减得到 CIT。作者说这套元数据每页只多 4 字节，用毫秒级 timer 就能把测量上界推到 1000 次每秒访问。之后系统用全局 CIT threshold 判定哪些页值得 promotion。

第二块是条件式 promotion。Chrono认为一次很短的 CIT 还不够可靠，因为扫描时刻和应用访存时刻可能偶然对齐，所以它用了两轮筛选。第一轮把低于阈值的页放进 XArray 管理的 candidate set；下一轮扫描再看一次，只有连续两轮都满足条件的页，才进入异步 promotion 队列。同时队列还有 rate limit，避免 DRAM 被短时间塞满，也避免迁页吞掉太多带宽。

第三块是自适应调参。半自动模式里，用户给出 promotion rate limit，Chrono根据队列入队速率回调 CIT threshold。默认的全自动模式则使用 Dynamic CIT Statistic Collection：它在不同 tier 上随机抽样 0.003% 的页，走同样的两轮 CIT 流程，再把结果汇总成 28 个 bucket 的 heat map。系统比较 slow tier 的 hot 页和 fast tier 的 cold 页，得到 misplacement signal，并据此同时调整 threshold 和 promotion rate。降迁这边，Chrono在 Linux 原有 high watermark 之上再加一个 `pro` watermark，提前把 DRAM inactive list 中的冷页 demote 到 slow tier；如果刚 demote 的页很快又变成 promotion candidate，就记作 thrashing，并在下一轮把 promotion rate 直接减半。论文还把同一套统计口径扩展到了 huge page。

## 实验评估

原型基于 Linux 5.18，实现规模大约 1.9k SLOC。实验机是一颗 Intel Xeon Gold 6348，fast tier 是 64 GB DDR4 DRAM，slow tier 是挂成 CPU-less NUMA node 的 256 GB Optane PMem。对比对象包括 Linux NUMA balancing、Auto-Tiering、Multi-Clock、TPP 和 Memtis。

最有说服力的是 Pmbench。50 个进程、每个进程 5 GB working set 的配置下，Chrono 相比 Linux-NB 提升 216%，相比 Auto-Tiering 提升 152%，相比 Multi-Clock 提升 92%，相比 TPP 提升 90%，相比 Memtis 提升 102%。这不只是端到端吞吐更高，过程指标也对得上论文的论点：fast-tier memory access ratio 从 49% 拉到 77%，平均和 P99 延迟最高分别下降 68% 和 79%。

控制开销确实存在，但和收益相比还算克制。Chrono比 Linux-NB 多出 2.1 个百分点 kernel time，其中 1.8 个百分点来自 DCSC。Graph500 在不同内存压力下，相对 Linux-NB 给出 2.49 倍、2.29 倍和 2.05 倍加速。多 cgroup 的冷热梯度实验里，Chrono会把几乎全部 DRAM 让给最热的进程，而不是像其他方案那样逼近平均分配。参数轨迹也能说明控制环在工作：有一个基准里，CIT threshold 最终收敛到约 200 ms，作者把它解释成大约 300 次每分钟访问。不过论文也没有把自己说成所有场景都赢。在 huge-page 配置下，Memtis 还能比 Chrono 快 1.03 倍。

## 创新性与影响

Chrono的创新点不在于又发明了一条迁移规则，而在于它先换掉了热度测量的基本单位。此前这些 Linux 侧的 tiering 工作，不管是 page fault、accessed bit 还是 PEBS，归根到底都在围绕计数、近期性或采样预算做折中；Chrono改成了用 idle time 反推访问频率，再把这个信号接进 promotion、demotion 和调参控制环里。这不是简单把阈值调得更聪明，而是把问题的观测方式变了。

它的影响面也比较明确。尤其在 base-page 场景里，论文展示了 huge-page 方案容易把热区放大，而传统 counter 又太粗；Chrono把 CIT 作为中间信号后，给后续 Linux tiering 系统留下了一条很清晰的路线。

## 局限性

Chrono并没有绕开 page fault 成本。它仍然依赖周期性扫描和故意触发 fault 的路径，因此不可能瞬时响应 phase 变化，额外 kernel time 也主要花在 DCSC 这样的控制逻辑上。

另一个边界来自实验平台。论文评估的是 Optane PMem 组成的 NUMA slow tier，而不是真实的 CXL memory pool，所以它证明了策略适用于慢速字节可寻址内存，却没有直接证明在 fabric-attached memory 上也同样稳定。再加上 huge-page 设置下 Memtis 还能小幅领先 1.03 倍，说明 Chrono并不是所有页粒度场景都占优；而且它覆盖的是一组代表性的 Linux 内核迁页方案，不是所有近期设计。

## 相关工作

- _Kim et al. (USENIX ATC '21)_ - Auto-Tiering 同样从内核扫描出发，但它的 page-fault counter 建立在分钟级窗口上，很难把 warm page 和真正的 hot page 分开。
- _Al Maruf et al. (ASPLOS '23)_ - TPP 把 page fault 和 LRU recency 结合起来面向 CXL 风格 tiering，不过它的迁移判据仍然比 Chrono 的 CIT threshold 粗得多。
- _Lee et al. (SOSP '23)_ - Memtis 用 PEBS 加动态页大小，统计性比纯 page-fault 方法更强，但最适合 huge page，在 base-page workload 上会出现热度碎片化问题。

## 我的笔记

<!-- 留空；由人工补充 -->
