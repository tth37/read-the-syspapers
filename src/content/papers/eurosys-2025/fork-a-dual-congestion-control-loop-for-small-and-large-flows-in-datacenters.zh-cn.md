---
title: "Fork: A Dual Congestion Control Loop for Small and Large Flows in Datacenters"
oneline: "Fork 把数据中心传输拆成两个环路：<=100 KB 小流走发送端高优先级控制，大流走接收端 credit 控制，再把 ECN 压力迁移给大流。"
authors:
  - "Yuan Liu"
  - "Wenxin Li"
  - "Yulong Li"
  - "Lide Suo"
  - "Xuan Gao"
  - "Xin Xie"
  - "Sheng Chen"
  - "Ziqi Fan"
  - "Wenyu Qu"
  - "Guyue Liu"
affiliations:
  - "Tianjin Key Laboratory of Advanced Networking, Tianjin University"
  - "Huaxiahaorui Technology (Tianjin) Co., Ltd."
  - "Peking University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696101"
tags:
  - networking
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Fork 的判断很直接：数据中心里的 mice 和 elephants 不该继续被同一个拥塞控制环路绑在一起。它让 <=100 KB 的小流进入发送端主导、最高优先级的 SCP，用目的端分组和多流 ACK-clocking 继承历史拥塞信息；>100 KB 的大流则进入接收端主导的 LCP，靠 credit 控制速率，并在必要时把小流看到的 ECN 压力迁移给大流。论文在 100 Gbps 测试床和大规模仿真里都表明，这种拆分能显著降低小流 FCT，同时不牺牲大流完成时间。

## 问题背景

这篇论文抓住的是一个老问题里最常被忽略的结构性矛盾。作者考察的五类重尾数据中心负载中，89.77% 到 99.57% 的字节来自大流，但小流在空载 100 Gbps 网络上平均只需要最多 3 个 RTT 就能完成，大流却要 13.3 到 178.4 个 RTT。也就是说，对小流而言，多出来 1 个 RTT 往往就是灾难；对大流而言，同样的额外时延常常只是边角料。

现有方案却普遍把两类流量绑在同一套反馈链路里。DCTCP 这类 sender-driven 方案让小流和大流一起看 ECN；Homa、Aeolus 这类 receiver-driven 方案则让它们一起吃 credit 调度，而且 Homa 还允许每个新流在第一个 RTT 里直接打出 1 BDP 的 unscheduled 数据。结果是拥塞信号失去归因能力：小流一旦看到排队，就会误把大流制造的拥塞当成自己该承担的反馈，从而主动降速。

作者还把两条看似自然的替代路线一并排除了。第一条是 pFabric 这类优先级调度思路，但它仍共享交换机 buffer 和同一控制实体，所以小流与大流的控制仍然缠在一起。第二条是给高低优先级队列静态切 buffer，这又会把资源切得过死，一边空闲时另一边借不到，一旦 burst 也无法弹性互补。

## 核心洞察

Fork 的核心洞察不是「给小流更高优先级」这么简单，而是小流和大流从根上就需要两种不同的控制时钟。小流承受不起 receiver-side 调度多出来的那个 RTT，因此必须由发送端直接控制；大流本来就要跑几十到上百个 RTT，更适合由接收端用 credit 去平滑调速。

不过，拆成两条环路还不够，关键是要让它们彼此补位而不是彼此隔离。Fork 围绕这个目标守住两个不变量。其一，小流必须尽量像「网络里没有大流」一样前进。其二，大流不能被永久压着，它们应该在小流不用带宽的时候把剩余容量吃满。作者为此补了两块机制：一块是让同一目的端的小流共享最近的拥塞历史，避免新来的小流从盲态起步；另一块是当网络里确实有活跃大流时，把小流身上观察到的 ECN 解释为大流导致的拥塞，并把减速责任转移到大流控制环路。

## 设计

Fork 在流到达时先按 100 KB 阈值分类。小流进入 SCP。SCP 的第一步是按目的端聚合，把从同一发送端发往同一接收端的小流放进一个 flow group。理由很现实：现代数据中心里这类并发流经常能达到数百到数千条，它们经过的路径和拥塞状态高度相关，因此一个新小流完全可以借用前面那些已完成或正在进行的小流留下来的窗口信息，而不必自己慢慢试探。

SCP 的第二步是多流 ACK-clocking。接收端对每个数据包回 ACK，并在包被 CE 标记时回显 ECN-Echo。发送端不按 RTT，而是按 ACK 更新组级 `cwnd`，并把连续两个 ACK 的 ECN 状态视为一个四态机：`00` 和 `10` 都执行 `cwnd += 1`，`01` 执行 `cwnd -= 1` 并把累计拥塞计数 `alpha` 置为 1，`11` 则继续增加 `alpha` 并按 `alpha` 更激进地下调窗口。这样做的目的，是让小流在几个 RTT 之内也能获得足够快的反馈，而不是像 DCTCP 那样按窗口节奏慢吞吞调整。SCP 的第三步是用 SRPT 在组内分配窗口，把剩余数据量最小的流优先发完。

大流进入 LCP。LCP 借了 Homa 的 receiver-driven 架构，但把启动方式和控制律都改了。新大流只发 request，不会在第一个 RTT 里直接喷出 1 BDP 数据；真正的数据发送要等接收端 credit。接收端维护授予的大流 credit 数 `GC`，并按包更新：若当前没有检测到由大流导致的拥塞事件，则 `GC += 1/GC`；若检测到大流拥塞，则 `GC -= 1/2`。这对应一个 receiver-side 的 additive increase / multiplicative decrease。

最关键的是拥塞诊断与 ECN migration。若一个被 ECN 标记的数据包本身来自大流，那它当然算大流拥塞。若它来自小流，接收端就继续判断：当前是否存在活跃大流？若没有，就把这次标记留给小流自己处理；若有，再看大流当前的 `GC` 是否已经降到最小值 1。只有在没有活跃大流，或者大流已经慢到不能再慢时，小流才真正回显这个 ECN。否则，接收端会压下这次小流的 ECN-Echo，并把这次标记计入大流侧，迫使 `GC` 下降。换句话说，只要大流是更可能的肇因，Fork 就把拥塞代价记到大流账上。

实现上，Fork 只改主机栈，不改网络 fabric。原型基于 DPDK，大约 2200 行代码；交换机只需要 ECN 和 strict priority queue，这些都是现成能力。

## 实验评估

论文的证据链分成两层。第一层是真实系统：8 台服务器、100 Gbps 链路、基线 RTT 约 3 微秒的测试床。第二层是 8 个 leaf、8 个 spine、64 台服务器的 leaf-spine 仿真。两层都覆盖 Web Server、Cache Follower、Web Search、Facebook Hadoop 和 RPC Read 五种重尾工作负载，因此实验确实打在论文声称的痛点上，也就是 mixed mice-elephant 场景中的启动 burst 与共享瓶颈竞争。

在测试床上，Fork 对小流的优势非常明显。相对 Homa，小流平均 FCT 降低 27.5% 到 65.1%，tail FCT 最多降低 97.9%；相对 Aeolus，平均 FCT 降低 33.1% 到 67.7%，tail FCT 最多降低 82.9%。与此同时，大流平均 FCT 也没有被拿去祭天，反而相对 Homa 降低 5.3% 到 36.3%，相对 Aeolus 降低 5.7% 到 36.0%。论文还统计了丢包数，在三类代表性负载上，Fork 比 Homa 少 42.9% 到 83.9%，比 Aeolus 少 98.2% 到 99.8%。

仿真把结论扩展到了更宽的负载区间。相对 Homa、Aeolus 和 dcPIM，Fork 的小流平均 FCT 最多分别下降 81.4%、67.3% 和 66.3%，tail FCT 最多分别下降 99.9%、67.6% 和 90.1%。大流平均 FCT 在多数情况下也更好，最多比 Homa、Aeolus、dcPIM 分别低 35.9%、50.4% 和 40.1%。队列长度数据也支撑了机制解释：平均队列长度与 Homa、Aeolus 大致相当，但最大队列长度降到 239 KB，在作者重点比较的场景里比 Homa 低 33.6%，比 Aeolus 低 10.5%。

不过这套评估并非没有瑕疵。基线选择是合理的，作者也用了各自公开的模拟器，但跨模拟器比较毕竟不如单一代码栈那样严密。Aeolus 的结果还受到 overcommitment 参数设置的影响，论文自己就承认把 Homa 的 overcommitment 设为 2 会改变丢包行为。尽管如此，测试床与仿真结论方向一致，足以让中心论点成立。

## 创新性与影响

Fork 真正的新意，不是再造一个高优先级小流传输，而是把「小流必须快」和「大流必须补位」这两件事拆进两条不同的控制闭环里，同时又让它们通过 ECN migration 和 credit 调节重新耦合。SCP 解决的是 sender-side 控制在小流启动阶段最难处理的「信息空窗」问题；LCP 解决的是 receiver-side 大流如何在给小流让路的同时，不把剩余带宽浪费掉。

这使得 Fork 很可能成为后续数据中心传输论文的一个参照点。以后再讨论单一 sender-driven 算法、纯 receiver-driven 设计，或者在一个反馈信号里同时兼顾 mice 与 elephants 时，都得先回答 Fork 提出的这个问题：为什么你不把它们拆开？

## 局限性

Fork 最现实的限制，是它假设流大小在到达时就已知。论文给出的论据主要来自 Hadoop、机器学习、数据迁移这类可以提前知道数据规模的场景，也提到可以借助历史统计和学习模型去估计，但对许多由用户行为驱动的在线业务，这个前提依然不稳。

第二个限制，是 100 KB 阈值与「小流就是时延敏感」这两个判断都不是普适真理。作者在讨论里已经指出，实时视频和语音可能本身就是大流，但同样对时延敏感。另一方面，一旦阈值抬得太高，超过大约 2 BDP 后，SCP 会开始吞下太多本应走 LCP 的大流，性能随之变差。

最后，系统证据还不算完全硬。原型只在 8 节点测试床上实现，大规模结论主要来自仿真；对于离散到达、非对称路径下 ECN 状态抖动，以及 flow group 历史保留超时如何调参，论文都把它们留在了未来工作里。

## 相关工作

- _Montazeri et al. (SIGCOMM '18)_ - Homa 是最接近的 receiver-driven 基线，但它仍用同一套 credit 逻辑控制 mice 和 elephants，而且第一个 RTT 就会发送 unscheduled 数据。
- _Hu et al. (SIGCOMM '20)_ - Aeolus 试图通过 selective dropping 修补 Homa 的 first-RTT 问题；Fork 则直接取消大流首 RTT 的数据喷发，并把拥塞压力通过 ECN migration 转嫁给大流环路。
- _Cai et al. (SIGCOMM '22)_ - dcPIM 同样是 proactive 的 receiver-coordinated transport，但它仍围绕一套共享调度来安排所有流，而不是给小流和大流各自独立的控制闭环。
- _Alizadeh et al. (SIGCOMM '10)_ - DCTCP 是典型的单一 ECN sender-side 方案，也正因为如此，它构成了 Fork 反对「同一个反馈信号统治所有流量」的主要反例。

## 我的笔记

<!-- 留空；由人工补充 -->
