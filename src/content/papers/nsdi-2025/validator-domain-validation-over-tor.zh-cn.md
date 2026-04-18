---
title: "ValidaTor: Domain Validation over Tor"
oneline: "ValidaTor 通过随机选择的 Tor exit node 执行 HTTP 域名验证，把固定 CA validator 变成不可预测的验证池，同时提升路径多样性并保持可部署吞吐。"
authors:
  - "Jens Frieß"
  - "Haya Schulmann"
  - "Michael Waidner"
affiliations:
  - "National Research Center for Applied Cybersecurity ATHENE"
  - "Technische Universität Darmstadt"
  - "Goethe-Universität Frankfurt"
conference: nsdi-2025
code_url: "https://github.com/jenfrie/tova"
tags:
  - security
  - networking
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`ValidaTor` 用 Tor 的 exit node 来执行基于 HTTP 的域名验证。它真正解决的问题不是“再多加几个 vantage point”，而是把 validator 的选择变成随机且难以提前锁定的过程。作者的原型显示，这样做既能相对 Let’s Encrypt 的固定部署显著降低路径重叠，又能在 5 个 validator 时把中位验证时延控制在约 2 秒，并且在整个 Web PKI 规模下只消耗 Tor 剩余带宽的约 `0.11%`。

## 问题背景

域名验证是 Web PKI 中最脆弱但又不可绕过的一步。CA 在签发证书前，必须先确认请求者真的控制目标域名，常见方式是让对方在 DNS 或 HTTP 上放置 challenge response。问题在于，这个验证过程本身运行在保护不完整的基础设施之上: DNS 可能被污染，BGP 可能被劫持，而一旦攻击者把 CA 的查询导向自己控制的基础设施，就可能骗取伪造证书。

社区早已认识到单点 validator 不够安全，所以 Let’s Encrypt 和 ACME 才引入 multi-vantage validation。但论文指出，validator 数量变多并不等于问题真正解决，只要 validator 集合仍然很小且位置固定，攻击者就仍然拥有明显的规划优势。已有工作表明，攻击者可以提前针对固定的验证节点发动攻击，甚至把它们共同导向攻击者指定的 nameserver，使得分布式防御再次退化为少数几个可预测的薄弱点。

根本障碍在于部署成本。理论上，CA 可以自己建设几十个全球分布的 validator，但那意味着持续维护昂贵的专用基础设施。作者认为，DV 真正需要的是一个足够大的 validator 池，让“提前把它们全部锁定并攻击”这件事在经济和操作上都变得不现实，同时又不能因为引入新机制而要求 CA 重写整个系统。

## 核心洞察

论文最重要的判断是，DV 不仅需要多个 vantage point，更需要不可预测性。如果攻击者在某次验证开始前根本不知道哪些 validator 会被选中，那么像预先布设的 BGP hijack、DNS 操纵这类 targeted attack 就会困难得多。

Tor 恰好提供了这个缺失条件。作者并不是把 Tor 主要当作匿名通信系统，而是把它当作一个现成的大规模分布式代理网络来使用。在测量时，Tor 提供了 2200 多个 exit node、1221 个唯一出口 IP、280 个去聚合后的 BGP origin。这样一来，CA 可以为每次验证随机抽取一组全新的 validator，而不必自己在这些位置部署服务器。又因为 DNS 解析发生在 exit node 一侧，攻击面不只是 HTTP 请求路径被多样化，resolver 这一侧也获得了额外分散。

不过，光有随机还不够，必须避免“随机到了彼此高度相关的节点”。所以 `ValidaTor` 把随机选择、前缀感知的去相关，以及 k-out-of-n 一致性结合在一起: 每次选择的 validator 来自不同网络前缀，系统先用 `k` 个节点验证，如果响应不一致再逐步增加直到 `n`。它真正依赖的是两个效应叠加: 攻击者无法提前知道要打谁，而能同时出现在所有验证路径上的强势 AS 也显著减少。

## 设计

`ValidaTor` 的原型是一个容器化服务，内部包含 Tor daemon、定制的 circuit management service、web server，以及负责验证逻辑的 Flask application。CA 或 ACME client 把 challenge URL 发给 `ValidaTor`，后台 worker 再通过 Tor 并发抓取目标资源，并对返回结果做聚合。

系统最关键的工程问题是 circuit 控制。Tor 默认的策略是为匿名性服务的，它并不保证“同一次域名验证必须走不同 exit node”。因此作者使用 Tor 的 `stem` 控制接口手动构建 circuit，并把请求流精确绑定到这些 circuit 上。出口节点从带 `EXIT` 标记、且未被标记为 `BADEXIT` 的 relay 中均匀随机抽样；为了让同一次验证的节点在网络层面更分散，系统还会排除与已选节点共享某个可配置 `/8` 前缀的节点。为了在选择空间和稳定性之间折中，原型维护大约 50 到 60 条并发 circuit，并每 3 分钟重建一次。

作者还把 Tor 默认的三跳路径缩短成两跳。由于 CA 不需要隐藏自身身份，系统只保留一个 guard 和一个 exit，以降低时延。入口节点从同时带 `GUARD` 和 `FAST` 标记的 relay 中选择，并根据可用带宽以及与服务器自身前缀的接近程度加权。验证逻辑则基本延续 Let’s Encrypt 的模式: 先从 `k` 个 validator 获取 challenge body，如果结果不一致，再继续增加 validator，直到最多 `n` 个；只要其中至少有 `k` 个响应内容一致，就把该值返回给 CA，否则验证失败。

还有两个很实际的设计点。第一，CA 现有基础设施几乎无需修改，只需要把原本直接发往目标域名的 challenge 请求改为发往 `ValidaTor` 服务，因此部署门槛较低。第二，当前系统只能支持 HTTP/HTTPS challenge，而不能支持 DNS TXT challenge，因为 Tor 目前不提供所需的 TXT 查询能力。

## 实验评估

这篇论文的实验有说服力，是因为它同时覆盖了系统性能与安全收益。性能方面，单个容器在 `k=3` 时达到 `2.7` 次验证/秒，在 `k=5` 时达到 `2.1` 次/秒，在 `k=7` 时达到 `1.6` 次/秒。横向扩展效果也比较干净: 使用 3 个容器并设置 `k=5` 时，吞吐提升到 `6.5` 次/秒；使用 10 个容器时则达到 `11.9` 次/秒。在 5-validator 配置下，中位验证时延约为 2 秒，至少 95% 的验证能在 6 秒内完成，已经与 `certbot` 处于相近的操作量级。

带宽结果同样关键，因为这决定了方案是否真的可部署。作者根据实际测得的流量和证书签发速率外推，估计如果整个 Web PKI 都改用 `ValidaTor`，Tor 网络总共只需额外承担约 `635.2 Mbit/s`，其中落在 exit node 上的是 `317.6 Mbit/s`。这分别只占 Tor 剩余总带宽的 `0.11%` 和 exit node 剩余带宽的 `0.15%`。也就是说，这个方案不仅在安全上成立，而且在它所依赖的共享网络上看起来也负担得起。

安全评估主要拿 Let’s Encrypt 当前的 MultiVA 部署做比较。可用 perspective 的差距非常明显: 作者观测到 Let’s Encrypt validator 只有 7 个去聚合后的 BGP origin，而 Tor exit node 有 280 个；Let’s Encrypt 的 DNS resolver 对应 9 个 origin，而 Tor 至少有 174 个。基于路径模拟的结果显示，相比 Let’s Encrypt，平均路径重叠大约下降了 50%。更直接地说，能够同时截获某个域名所有 validator 的 AS 数量，在 3 个 validator 时下降 `21%`，在 7 个 validator 时最高下降 `27%`。关于恶意 exit node 的分析也较为乐观: 在 staged `k`-out-of-`n` 选择与前缀感知约束下，即便攻击者控制了大约四分之一的 Tor exit node，只要 `k=7`，伪造验证成功的概率仍可压到 1% 以下。

不过，实验也暴露了一个现实问题: 大约 20% 的验证请求会失败，因为目标域名自己屏蔽了来自 Tor 的流量。作者进一步证明，这些失败在不同 validator 之间高度相关，因此更像是 destination 侧的统一封锁，而不是 transit AS 系统性拦截。这并不推翻其安全主张，但确实说明该方案的即时可部署性会受到一部分站点策略的限制。

## 创新性与影响

这篇论文的新意既在体系结构，也在问题重构。体系结构上，`ValidaTor` 给出了一个今天就能被 CA 实现的 DV 系统，把手动 Tor circuit 选择、分布式 validator 抽样，以及 k-out-of-n 结果聚合组合成了可运行方案。问题重构上，它把 Tor 从“匿名通信工具”重新定义为“可共享的 PKI 加固基础设施”。

因此，这篇论文的价值不只是“再加更多 validator”。它指出当前 DV 真正缺少的是一个足够大、足够分散、又无法提前预测的 validator 池。我预计这项工作会对 CA 运维者、ACME 设计者，以及研究如何抵抗 BGP 操纵的证书签发系统的人都有影响，因为它把长期存在的部署障碍变成了一个相对可操作的系统设计问题。

## 局限性

最大的限制是覆盖范围。`ValidaTor` 目前只能支持基于 HTTP 的验证，因为 Tor 无法满足 DNS TXT challenge 所需的查询能力。既然 DNS-based DV 在现实中依然常见，这就意味着它还不能直接替代所有验证模式。

安全分析与真实攻击之间也存在距离。路径多样性的结论建立在真实测量结合 BGP 路径模拟之上，而不是来自持续观测中的真实对抗者；恶意 exit node 的结论同样依赖概率模型和前缀分布假设。这些方法是合理的，但仍然是模型而非现场证据。

最后，Tor 并不是零摩擦底座。实现上，当并发 circuit 超过大约 70 到 80 条时系统会变得不稳定；目标站点对 Tor 的封锁会让大约五分之一的验证失败；恶意 exit node 依然是残余风险，只能依靠 Tor 现有监测机制以及更保守的 `k` 配置来压低概率。所以这篇论文证明的是一个很强的加固机制，而不是“DV over Tor 已经没有部署约束”。

## 相关工作

- _Brandt et al. (CCS '18)_ - `Domain Validation++` 旨在提升 DV 对中间人攻击的抵抗力，但它仍然建立在更传统的 validator 部署方式上，而不是像 `ValidaTor` 这样利用大规模随机公共代理网络。
- _Birge-Lee et al. (USENIX Security '18)_ - `Bamboozling Certificate Authorities with BGP` 说明了可预测的 multi-vantage validation 仍可被绕过，而 `ValidaTor` 试图消除的正是这种“可提前规划攻击”的优势。
- _Cimaszewski et al. (USENIX Security '23)_ - 这项测量研究量化了当前 multiple-vantage-point DV 的实际韧性；`ValidaTor` 则进一步提升了 validator 与 DNS resolver 两侧的多样性。
- _Frieß et al. (HotNets '24)_ - `ADDVent` 也追求大规模分布式验证，但它依赖广告网络去众包浏览器客户端，而 `ValidaTor` 复用的是 Tor 现成的 relay 生态，并避免了对广告平台的信任假设。

## 我的笔记

<!-- 留空；由人工补充 -->
