---
title: "ONCache: A Cache-Based Low-Overhead Container Overlay Network"
oneline: "ONCache把 overlay 网络里跨层且稳定的处理结果缓存到 eBPF fast path 中，在保留容器 IP 灵活性的同时绕过重复的 veth、过滤、路由与封装开销。"
authors:
  - "Shengkai Lin"
  - "Shizhen Zhao"
  - "Peirui Cao"
  - "Xinchi Han"
  - "Quan Tian"
  - "Wenfeng Liu"
  - "Qi Wu"
  - "Donghai Han"
  - "Xinbing Wang"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Broadcom"
conference: nsdi-2025
pdf_url: "https://www.usenix.org/system/files/nsdi25-lin-shengkai.pdf"
code_url: "https://github.com/shengkai16/ONCache"
tags:
  - networking
  - kernel
  - ebpf
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ONCache 保留了标准容器 overlay 作为失败安全的回退路径，但把连接跟踪、过滤、路由和封装里那些会重复出现的结果缓存起来，让后续数据包绕过大部分 overlay 慢路径。它基于 eBPF、实现很小，却能在不放弃 container IP 灵活性和兼容性的前提下，把性能拉近到 bare metal。

## 问题背景

这篇论文关心的是容器网络里一个长期存在但很难同时满足的三角约束。Host network、bridge、Macvlan/IPvlan、SR-IOV 这些方案都可能很快，但它们往往要求共享主机 IP、协调端口、限制容器放置位置，或者要求 underlay 直接理解 container IP。Overlay network 恰恰解决了这个部署问题：容器地址空间和物理网络解耦，Kubernetes 集群可以更自由地调度、迁移和扩缩容。

代价是每个包都要多走很多内核路径。作者没有只说“overlay 有额外开销”，而是把 Antrea 和 Cilium 相对 bare metal 的差距拆开：veth 穿越、OVS 或等价处理、conntrack、过滤、VXLAN 封装与解封装都会贡献成本。在他们的实验里，隧道式 overlay 让单流 TCP 吞吐下降大约 11%，TCP request-response 事务率下降大约 29%，同时 CPU 利用率更高。真正棘手的点在于，这些开销分散在多层 datapath 里，不是优化一个模块就能把损失全部拿回来。

已有工作的覆盖面也不够完整。Slim 用 socket replacement 降低开销，但天然不支持 UDP、ICMP、容器 live migration，也可能和依赖隧道头的 underlay 策略冲突。Falcon 这类工作靠多核并行化提升 ingress 处理能力，却没有减少 overlay 本身必须做的工作，还可能增加 CPU 消耗。于是论文把问题重新表述为：能不能保留标准 overlay 的灵活性与兼容性，同时把那些重复劳动真正绕过去？

## 核心洞察

核心洞察是：overlay 的很多“额外工作”在一个流建立之后其实会稳定下来。只要 conntrack 已经看到双向通信，连接状态就稳定；一旦过滤器在 established 状态下放行这个流，判定通常也稳定；目的容器确定后，主机内路由结果稳定；而隧道外层头部里大部分字段对同一目的地的数据包来说同样稳定。

因此，应该缓存的不是某一层的局部结果，而是跨层的整体处理结果。ONCache 把 conntrack、过滤、主机内转发和外层头构造的稳定结果一次性记下来，后续就用几次 map lookup 加少量头字段更新，替代反复穿过 veth、过滤逻辑、路由逻辑和封装逻辑。论文最重要的论断是：overlay 的额外成本并不是“每包都必须重新计算”的，而是足够可复用，因而可以被 memoize。

## 设计

ONCache 不是替换整个 CNI，而是叠加在现有 overlay 之上的一个插件，已经在 Antrea 和 Flannel 上验证过。它的 fast path 由四个挂在 TC 上的 eBPF 程序、三个每主机的 eBPF map，以及一个 userspace daemon 组成。三个 cache 是设计中心。Egress cache 记录“发往这个 container dIP 的包，应该走哪个 host、使用哪些外层头、如何改写内层 MAC”。为了节省内存，它被拆成两级：先从 container dIP 找到 host dIP，再从 host dIP 找到 outer headers、inner MAC rewrite 和 host interface index。Ingress cache 则记录目标容器的主机内转发结果，即 `container dIP -> destination MAC + veth index`。Filter cache 相当于 established flow 的白名单。

初始化过程很保守。发生 cache miss 时，ONCache 不猜，而是给包打上 miss mark，然后把它交回标准 overlay 去处理。具体实现上，作者在 inner IP header 的 DSCP 里保留两个 bit，一个表示 miss，一个表示 established。回退 overlay 在发现流进入 established 状态后写入 est mark；随后两个初始化程序分别在 host interface 和 container-side veth 观察这些包，把已经由 overlay 权威地算好的路由、头部和过滤结果写入 cache。换句话说，ONCache 是“先让原系统算一遍，再把结果拿来复用”。

命中 cache 后，fast path 是对称的。Egress 程序先检查 filter cache，然后做一次 reverse check，确认反向流也已经准备好 cache，从而避免单边驱逐导致后续无法重新初始化。之后它改写 inner MAC，重建 outer headers，更新可变的 IP/UDP 字段，并把包重定向到 host interface。Ingress 程序则先验证包的目标确实是本机，再查询 filter cache 和 ingress cache，剥掉 outer headers，恢复 inner MAC，然后用 `bpf_redirect_peer` 直接把包送到目标 veth。

整个设计明确强调 fail-safe。任何 miss 或前提不满足都不会丢包，而是回退到标准 overlay。Userspace daemon 负责 cache coherency：在容器删除、迁移或策略变化时删除相关 cache，再让 overlay 重新初始化。作者还给出了大规模集群下的内存估算，认为开销可接受：每主机大约 1.56 MB 的 egress cache、2.2 KB 的 ingress cache 和 20 MB 的 filter cache。

## 实验评估

实验设计基本对准了论文的中心论点。测试环境是在 CloudLab 上搭建的 Kubernetes 1.23.6 集群，三台 c6525-100g 节点、100 Gb 网卡、Ubuntu 20.04、Linux 5.14，ONCache 以 Antrea encap mode 插件方式部署。对比基线包括 Antrea、Cilium、bare metal，以及代表两类既有思路的 Slim 和 Falcon。这个基线集合是合理的：既覆盖主流 overlay，也覆盖“替换 socket”和“并行化处理”两种替代方向。

微基准最能说明问题。TCP 方面，ONCache 在 1-flow 和 2-flow 下比 Antrea 提升 11.53% 和 13.96% 的吞吐；更关键的是 request-response 事务率提升 35.81% 到 40.91%，同时每个 RR 的 CPU 开销下降 26.02% 到 32.03%。UDP 也获益明显：低并行度下吞吐提升 19.68% 到 31.76%，UDP RR 提升 34.13% 到 39.12%。Table 2 的底层分解和端到端结果一致：ONCache 的网络栈时延是 17.49 us，明显低于 Antrea 的 22.97 us，已经接近 bare metal 的 16.57 us。作者还做了 cache interference、cache scalability、rate limiting、packet filter 和“模拟 live migration”等实验，说明 fast path 至少没有靠牺牲功能完整性换数字。

应用实验说明收益并不只存在于 toy benchmark。Memcached 的平均延迟下降 22.71%，吞吐提升 27.83%；PostgreSQL 的平均延迟下降 22.34%，吞吐提升 29.40%；Nginx 的 HTTP/1.1 延迟下降 21.53%，吞吐提升 27.43%。这些负载上的 CPU 开销也显著下降。最弱的一组结果是 HTTP/3：CPU 仍然下降，但时延和吞吐在不同网络之间几乎没差别。作者把这一点归因于 Nginx 的实验性 QUIC 支持。我认为这个处理是加分项，因为它说明论文没有把所有结果都硬解释成机制成功。

## 创新性与影响

这篇论文真正的新意不是“用了 cache”，而是把 cache 放到了跨层结果上。OVS 早就缓存 flow matching，先前工作也分别尝试过 socket replacement 或 packet processing 并行化，但 ONCache 是把 overlay 开销看成一个跨越多层内核 datapath 的复合结果：如果只缓存单层结果，剩余层的成本依然在；只有把这些结果一起缓存，才可能把 bare metal 与 overlay 之间的差距整体缩小。

它的潜在影响偏工程落地。ONCache 维持了 tunneling 语义，支持 TCP 和 UDP，可以与 live migration、data-plane policy、service mesh 等环境共存，还能作为现有 CNI 的附加插件部署。对研究者而言，它提供了一个很清晰的系统论证：overlay 的性能损失并非不可避免，而是部分来自重复计算。对集群运营者而言，它说明“要灵活就一定慢”并不是必须接受的结论。

## 局限性

ONCache 不是对所有流量都有效。它只加速 inter-host container traffic；intra-host、container-to-host、container-to-external-IP 等流量仍然走回退路径。它也不是首包就生效，cache 初始化前仍然要付出正常 overlay 的成本，所以连接建立阶段的收益有限，CRR 结果也反映了这一点。

它依赖的稳定性假设也有边界。ONCache 天然适合 established 状态后判定稳定的过滤器；对于依赖 overlay packet hash 的过滤器，或者没有稳定 established 状态的特殊 stateful filter，模型就不成立。实现上它还要求在 DSCP 中保留两个 bit 作为 miss 和 est 标记；如果生产网络严格依赖全部 DSCP 位做差异化服务，这会增加部署摩擦。

另外，默认设计仍然留下了一些已知残余开销。Egress 方向的 namespace traversing 没有完全消掉；论文提出的 `bpf_redirect_rpeer` 和 rewriting-based tunneling protocol 虽然能进一步逼近 bare metal，但需要内核或协议修改。对于已经把 TC eBPF 深度嵌入 datapath 的 Cilium、Calico 之类 CNI，ONCache 也不是直接插上就能用，而是需要重新实现。换言之，它非常强，但还不是“零改动、零代价”的通用 overlay。

## 相关工作

- _Zhuo et al. (NSDI '19)_ - `Slim` 通过 socket replacement 避开 TCP overlay 开销，而 ONCache 保留标准隧道语义，并继续支持 UDP、ICMP 和 live migration。
- _Lei et al. (EuroSys '21)_ - `Falcon` 通过多核并行化提高 packet processing 吞吐，而 ONCache 的路线是直接减少需要处理的工作量。
- _Dalton et al. (NSDI '18)_ - `Andromeda` 在 VM 网络虚拟化里缓存路由和过滤结果；ONCache 则把 conntrack、veth 和 tunneling 一起纳入跨层 cache。
- _Pfaff et al. (NSDI '15)_ - `Open vSwitch` 缓存的是 flow matching，但 ONCache 表明仅做单层缓存，仍然保留了 overlay 其余 datapath 的大量成本。

## 我的笔记

<!-- empty; left for the human reader -->
