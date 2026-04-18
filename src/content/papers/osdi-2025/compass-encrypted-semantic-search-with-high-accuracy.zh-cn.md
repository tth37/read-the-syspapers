---
title: "Compass: Encrypted Semantic Search with High Accuracy"
oneline: "Compass 用方向量化提示、投机式图预取和面向遍历的 ORAM 协同设计，把加密语义检索做到接近明文语义检索的准确率与可用时延。"
authors:
  - "Jinhao Zhu"
  - "Liana Patel"
  - "Matei Zaharia"
  - "Raluca Ada Popa"
affiliations:
  - "UC Berkeley"
  - "Stanford University"
conference: osdi-2025
code_url: "https://github.com/Clive2312/compass"
tags:
  - security
  - databases
  - ml-systems
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Compass 讨论的是一个很直接的问题：加密检索能否不再退回到关键词匹配，而是保留现代语义检索的准确率。它把 HNSW 风格的图索引放到加密嵌入之上运行，并用量化方向提示、投机式图预取，以及针对多跳遍历改造过的 Ring ORAM，把查询时真正需要付费的远程访问压到最少。结果是在四个数据集上，Compass 保住了明文 embedding search 的检索质量，同时在论文设定的慢速跨区域网络下把用户感知延迟控制在 0.57-1.28 秒。

## 问题背景

这篇论文切中的不是“如何让加密搜索存在”，而是“如何让它在今天的检索质量标准下仍然有意义”。过去的大量 encrypted search 工作主要围绕 lexical search 展开，用倒排索引在不泄露明文的前提下支持关键词查询。这条路线的安全性可以很强，但准确率通常落后于现代 semantic search，因为它无法像 embedding-based retrieval 那样理解查询语义。另一类方案虽然支持更强的搜索能力，却往往在系统假设上让步，比如泄露访问模式、依赖 TEE，或假设多个互不串通的服务器。Compass 想要的点位更苛刻：用户把自己的私有文档加密后放在云端，服务端即使被完全攻破，也不该知道数据、查询、结果集以及访问模式。

难点在于，最自然的实现方式根本跑不动。今天高准确率的 semantic retrieval 往往依赖 HNSW 这类 graph ANN 索引，因为它们在高维嵌入上效果极强。但 HNSW 默认是在本地内存里做贪心多跳遍历：访问一个节点、检查它的全部邻居、选出更接近查询的候选，再继续下一跳。如果把“访问一个节点”替换成一次远程 ORAM 访问，整个搜索过程就会被拉长成一串高延迟 client-server 往返。论文指出，一个高质量 HNSW 查询通常要评估几十到上百个候选节点，而每个节点又有几十到上百个邻居；朴素地把 HNSW 直接架在 ORAM 上，单个查询就可能需要取回上千个节点的数据，并产生几十到上百轮网络往返。FHE 或 GarbledRAM 虽然能从密码学上掩盖这种访问，但代价更高。真正的问题因此变成：如何重写图遍历和远程存储的配合方式，让 ORAM 只为“值得访问”的节点买单。

## 核心洞察

Compass 的核心判断是：只要客户端手里有一个足够便宜、足够粗糙、但能表达“朝哪个方向继续走”的局部几何近似，graph ANN 就仍然可以在加密环境里维持高准确率。也就是说，系统不该把 ORAM 当成一个黑盒，再把原封不动的 HNSW 硬搬上去；正确的做法是把图遍历和 ORAM 协同设计。

这个判断成立的原因在于，查询端本来就运行在客户端。客户端完全可以本地持有一个压缩过的图几何摘要，用它先对邻居做近似排序，再只为最有希望的几个节点发起精确 ORAM 访问。量化提示只负责“筛选”，不负责最终判定，因此不会像直接在压缩向量上做搜索那样明显掉精度。同样的思路也可以用来压低延迟：如果搜索前沿里的下一个几个节点大概率可预测，就可以把这些访问投机式地并进一个 batch；如果 ORAM 中不在关键路径上的工作能推迟到查询结束之后再做，用户看到的延迟就会明显下降。

## 设计

Compass 的总体结构是：服务器保存加密后的 embedding 与 HNSW 图，客户端持有搜索逻辑。每个 ORAM block 对应 HNSW 图中的一个节点，内部同时存放该节点的完整 embedding 和 neighbor list。客户端维护常规的 ORAM 状态、HNSW 元数据、ORAM tree 的树顶缓存，以及 HNSW 上层若干层的本地缓存。除此之外，它还维护一个新结构 Quantized Hints：对每个节点保存一个 product-quantized 版本的 embedding，用节点 ID 映射到一个很便宜的近似坐标。

第一项机制是 Directional Neighbor Filtering。面对当前待扩展节点时，客户端先在本地查它所有邻居的 quantized embedding，用近似距离把这些邻居排个序，只从中挑出最有希望的前 `efn` 个，再通过 ORAM 拉取这些节点的精确坐标和邻接信息。这里的 quantized hint 只承担过滤职责，不参与最终结果判定。这样做的关键价值是：如果直接在压缩向量上跑 ANN，准确率会明显下降；但若只把压缩向量当作方向提示，就能把带宽大致压到 `M / efn`，同时保留全精度距离比较的最终判断。

第二项机制是 Speculative Neighbor Prefetch，它主要优化 round trip 数而不是带宽。原始 HNSW 会在前沿里每次只处理一个最优候选；Compass 则一次性从 candidate list 里取出前 `efspec` 个候选，把它们下一跳需要访问的邻域一起打包拉回。客户端再对返回节点做精确评估，更新 frontier。虽然这是“投机”访问，但 candidate list 本身已经按与 query 的距离排序，所以猜测并不盲目。按论文的分析，这能把搜索批次数大致缩减到原来的 `1 / efspec`。

第三项机制是 Graph-Traversal Tailored ORAM。Compass 把一个节点的 coordinates 和 neighbor list 放在同一个 block 里，避免先拿到节点再额外发一次请求读取邻接表。它对 ORAM 访问做 batching，把 bucket metadata 缓存在客户端，并把 eviction 推迟到查询结束之后再统一做，也就是 multi-hop lazy eviction。因为 Ring ORAM 中用户真正感受到的是在线读取成本，而 eviction 更偏后台工作，这一步把不少代价从关键路径挪走了。为了不让这种“按图遍历优化 ORAM”的改造反过来泄露图结构，Compass 又要求每个节点的度数被 padding 到统一大小、每一层搜索步数固定、batch access 也做填充。面对 malicious server，系统还在 ORAM tree 之上叠了 Merkle tree，并在每个 bucket 内部再加一层次级 Merkle tree，用来检测篡改和 replay。

## 实验评估

实现大约 5k 行 C++，底层用 Faiss 构建 HNSW 与 Product Quantization，用 OpenSSL 提供 AES-256-CBC 和 SHA-256。实验环境是 Google Cloud 上一台 client 和一台 server，网络分别模拟 3 Gbps / 1 ms 的同区域链路，以及 400 Mbps / 80 ms 的跨区域慢链路。数据集覆盖 LAION、SIFT1M、TripClick 和 MS MARCO，参数选择目标是 Recall@10 至少达到 0.9。

最核心的结果是，Compass 在不牺牲准确率的前提下把加密语义检索做到了可用。论文显示它在四个数据集上都能匹配 brute-force embedding search 的质量，因此也基本追平了明文 HNSW 的检索效果；同时，它明显优于两类安全基线，一个是 lexical 的 Inv-ORAM，一个是基于同态加密聚类的 HE-Cluster。延迟上它当然还比不过明文系统，论文给出的结论是大约比 Plaintext-HNSW 慢 6-10 倍；但相对“直接把 HNSW 架在 ORAM 上”的朴素方案，它最高快 920 倍，相对两个安全基线也快了几个数量级。慢网络下，用户感知延迟从 LAION 的 0.57 秒到 MS MARCO 的 1.28 秒。论文还表明，lazy eviction 把用户感知延迟相对完整延迟降低了 1.5-5.6 倍，而消融实验里，仅 batching ORAM request 这一项就带来了 12-20 倍的延迟下降。

不过它的可扩展性边界也写得很清楚。服务端内存开销是明文 embedding 加图结构的 3.2-6.8 倍，因为 ORAM 需要 dummy 容量来控制 stash 和 reshuffle。客户端内存对个人规模数据还算友好，比如 LAION 只要 5.49 MB，SIFT1M 是 35.84 MB；但到 MS MARCO 就涨到 498.65 MB。正因为如此，作者把 Compass 定位成 personal private search 和 encrypted RAG retrieval，而不是 web-scale search engine。好的一面是，服务端负担主要是存储和轻量 XOR，在 LAION 上，25 个并发客户端时服务器做到 436 QPS，CPU 利用率只有 26%。

## 创新性与影响

相对于 _Mishra et al. (S&P '18)_ 的 Oblix，Compass 不是在 lexical search 上继续做 oblivious index，而是把问题推进到 embedding-based semantic retrieval，并解决图遍历在强隐私约束下如何运行。相对于 _Henzinger et al. (SOSP '23)_ 的 Tiptoe，它处理的是私有加密语料，而不是可公开预处理的 public corpus。相对于 _Chen et al. (USENIX Security '20)_ 的 SANNS，它没有叠加更重的密码学工具链，而是围绕一次精心改造的 ORAM 图遍历做系统协同设计。

所以这篇论文的贡献形态，不是新的密码学原语，也不是新的 ANN 图结构，而是一种很系统的 co-design。它最可能影响的方向，是 private cloud search 和 encrypted RAG：任何未来想在“不信任服务器硬件”的前提下保住 semantic retrieval 质量的系统，都会碰到同样的“如何在隐藏访问模式的同时做图搜索”问题，而 Compass 给出了一个可信的第一代答案。

## 局限性

Compass 很明确地说明了它不隐藏什么。服务器仍然能看到操作类型、公开搜索参数、用户大致数据规模，以及基于时间的侧信道。系统还假设客户端能可靠保存本地状态；如果客户端磁盘损坏，只能依赖服务器返回 checkpoint，那么恶意服务器可能回放陈旧状态而不被发现。

第二个限制是规模。论文自己就明确说它还不适合 global web search，而 MS MARCO 约 498.65 MB 的客户端内存占用已经解释了原因。即使在延迟上，也要区分“用户感知延迟”和“完整延迟”：前者大约是一秒级，因为 eviction 被推迟了；但在大数据集上，完整延迟仍是数秒。更新代价也不低。论文给出的例子是，在 MS MARCO 上，当插入使用大小为 160 的 candidate list 时，慢网络下一次插入要 19.2 秒。这更适合个人数据异步索引，而不是高频共享更新。

## 相关工作

- _Mishra et al. (S&P '18)_ — Oblix 面向的是 lexical retrieval 的 oblivious index，而 Compass 面向 embedding-based semantic search，因此需要隐藏的是图遍历而不是关键词列表访问。
- _Dauterman et al. (OSDI '20)_ — DORY 通过分布式信任实现 encrypted search；Compass 则坚持单服务器设定，不接受“至少有一个信任域诚实”的假设。
- _Chen et al. (USENIX Security '20)_ — SANNS 也支持 secure approximate nearest-neighbor search，但依赖更重的密码学组合；Compass 则把 graph ANN 与 Ring ORAM 细致协同，换取更实用的时延。
- _Henzinger et al. (SOSP '23)_ — Tiptoe 通过聚类让 public corpus 上的 private query 更高效；Compass 处理的是 private encrypted data，并为保住高语义准确率接受更复杂的遍历设计。

## 我的笔记

<!-- 留空；由人工补充 -->
