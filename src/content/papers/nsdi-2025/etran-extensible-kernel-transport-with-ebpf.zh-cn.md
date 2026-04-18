---
title: "eTran: Extensible Kernel Transport with eBPF"
oneline: "eTran 为 eBPF 增加 egress、packet generation 和 pacing 原语，让新传输协议把状态留在内核里，同时拿到接近用户态传输的性能。"
authors:
  - "Zhongjie Chen"
  - "Qingkai Meng"
  - "ChonLam Lao"
  - "Yifan Liu"
  - "Fengyuan Ren"
  - "Minlan Yu"
  - "Yang Zhou"
affiliations:
  - "Tsinghua University"
  - "Nanjing University"
  - "Harvard University"
  - "UC Berkeley & UC Davis"
conference: nsdi-2025
code_url: "https://github.com/eTran-NSDI25/eTran"
tags:
  - ebpf
  - kernel
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

eTran 通过给 eBPF 增加 `XDP_EGRESS`、`XDP_GEN` 和 `PKT_QUEUE`，把内核改造成一个 transport substrate。这些扩展让 transport state 继续留在内核里接受保护，同时仍能把 Linux TCP 和 Linux Homa 的吞吐最多提升到 `4.8x` 和 `1.8x`，并把延迟最多降到 `3.7x` 和 `7.5x`。

## 问题背景

数据中心 transport 的演化速度远快于 Linux 的吸收速度。DCTCP 花了多年才进入主线，MPTCP 接近十年，Homa 到论文发表时仍是 out-of-tree module。RPC、存储和 ML workload 需要的是不同的 transport policy。

kernel bypass 是常见逃逸路径，但会削弱保护：应用或 NIC firmware 会更直接地影响 transport 行为，debugging、telemetry 和多租户隔离也更难做。留在内核里可以保住 protection，但现有 eBPF hook 又不足以承载完整 transport：XDP 只看 ingress，不能生成 ACK 或 credit packet，也没有 pacing buffer。真正的挑战因此是让 kernel transport 变得可扩展，同时不丢掉 kernel safety 和大部分用户态 transport 的性能收益。

## 核心洞察

论文的核心判断是：只要内核补上三个缺失原语，绝大多数 transport logic 就能继续留在 kernel eBPF 里，只把别扭的部分推给 privileged daemon。daemon 负责程序挂载、AF_XDP 资源创建、连接建立与拆除、需要 floating point 的复杂 congestion control，以及 timeout 恢复。

真正 timing-critical 的部分仍在内核里：state machine、header 处理、ACK 或 credit 生成、pacing，以及 packet 校验。用户态库只负责通过 AF_XDP 搬运 packet data 并恢复应用可见的抽象，不能直接修改 transport state。

## 设计

eTran 分成 control path 和 data path。control path 是 root daemon，负责挂载 transport-specific eBPF program、创建 AF_XDP socket 与 UMEM，并处理 slow-path control operation。data path 则横跨 kernel eBPF 和一个很薄的用户态库；这个库负责消息重组，并暴露 POSIX 风格或 RPC 风格接口，但 transport state 留在 eBPF map 里。为了覆盖多个 NIC queue，eTran 还构建了带 DRR 调度的 virtual AF_XDP socket。

真正的系统创新在内核扩展本身。`XDP_EGRESS` 挂在 AF_XDP 发送路径上，让 eBPF 能填 header、用 `umem_id` 做所有权校验、立即发送、缓存或丢弃 packet。`XDP_GEN` 在 NAPI poll 结束时运行，使 ingress 逻辑可以先把 metadata 入队，再批量生成 ACK 或 credit packet。`BPF_MAP_TYPE_PKT_QUEUE` 与扩展 BPF timer 结合后，构成同时支持 rate-based 和 credit-based 调度的 pacing engine。

两个 case study 说明这套 substrate 并不只适合 TCP。对带 DCTCP 的 TCP，eTran 把 connection state 放进 hashmap，把 congestion-control state 放进可被 daemon `mmap` 的数组，在 `XDP` 上校验 packet，并在窗口受限时使用 pacing queue。对 Homa，它把 RPC state 放进 eBPF，用 `bpf_rbtree` 实现 receiver-driven credit scheduling，新增 `bpf_rbtree_lower_bound` kfunc 来模拟 priority search，再用 tail call 拆开逻辑以适应 verifier 的 instruction limit。

## 实验评估

在 25 Gbps 的 CloudLab 机器上，eTran Homa 把 32B RPC 的 median latency 从 `15.6 us` 降到 `11.8 us`，把 1 MB 吞吐从 `14.5` 提升到 `17.7 Gbps`，并把客户端和服务端 RPC rate 从 `1.7/1.8` 提升到 `2.9/3.3 Mops`。在 10 节点 cluster workload 中，它把短消息主导负载的 P99 latency 再降低了 `3.9x-7.5x`。

对 TCP，eTran 也在作者的 echo 与 key-value benchmark 中持续优于启用 DCTCP 的 Linux TCP。在 key-value store 上，它最高达到 Linux 的 `4.8x` 吞吐，并把无负载时的 P50/P99 延迟从 `64.2/89.3 us` 降到 `17.2/27.5 us`。不过它仍慢于 TAS，这很合理：TAS 用 dedicated core 做 busy polling，并绕开了更多内核路径。

支撑性实验也让 substrate 论点更可信。`PKT_QUEUE` 做 rate limiting 时与目标值的偏差保持在 `0.4%` 以内；一个空的 `XDP_EGRESS` hook 带来 `6.6%` 吞吐损失；eTran 还把 TCP 每请求 CPU 成本从 `12.51` 降到 `4.37` kcycles，把 Homa 从 `17.43` 降到 `5.48`。主要局限是范围仍窄：一种 NIC 家族、一个 driver，以及两种 transport 实现。

## 创新性与影响

这篇论文的新意不在于某一个 transport algorithm，而在于一个可复用的 kernel transport substrate。`eTran` 的核心主张是：与其把每个 transport 分别合入 Linux，不如一次性把 eBPF 教成“如何承载 transport”。

这使它同时对 transport 研究者、希望保留内核侧 protection 的云运维者，以及思考 XDP/AF_XDP 应该演化到哪里的内核开发者有参考价值。它把“受保护的内核内 fast path”这条中间路线具体化了。

## 局限性

eTran 最大的现实限制是部署摩擦。`XDP_EGRESS`、`XDP_GEN`、`PKT_QUEUE`、新的 timer mode，以及 tree-search kfunc 都要求修改内核，因此这条路线依赖 upstreaming 和持续的安全审查。

性能也不是处处最优。TCP 仍慢于 TAS，eBPF 依然缺少 floating point 与丰富的同步原语，thread scheduling 会伤害 tail latency，而论文里的 mlx5 配置也缺少 TSO 或 multi-buffer 这类 AF_XDP 特性。更进一步说，它的安全性仍建立在对 kernel 与 verifier 生态的信任之上；新增 kfunc 被谨慎限制，但本文并没有对其做形式化验证。

## 相关工作

- _Kaufmann et al. (EuroSys '19)_ - `TAS` 把 transport 作为 microkernel 风格的用户态服务来做，而 `eTran` 把 fast path 拉回 kernel eBPF，以换回 protection 和 Linux stack 的 coexistence。
- _Fried et al. (NSDI '24)_ - `Junction` 关注如何让 kernel bypass 在云环境中变得实际可用，`eTran` 则选择了另一端：牺牲一部分峰值性能，换取内核内隔离与 state protection。
- _Zhou et al. (NSDI '23)_ - `Electrode` 把 distributed protocol logic 下沉到 kernel eBPF，而 `eTran` 进一步扩展 eBPF 自身，使 transport protocol 能直接建立在其上。

## 我的笔记

<!-- 留空；由人工补充 -->
