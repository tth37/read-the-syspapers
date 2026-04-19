---
title: "R AKIS: Secure Fast I/O Primitives Across Trust Boundaries on Intel SGX"
oneline: "R AKIS 用一层经过验证的 enclave-side fast path 把 XDP 和 io_uring 接到 SGX 里，让未修改程序跨 trust boundary 也能做 exit-less UDP、TCP 和 file I/O。"
authors:
  - "Mansour Alharthi"
  - "Fan Sang"
  - "Dmitrii Kuvaiskii"
  - "Mona Vij"
  - "Taesoo Kim"
affiliations:
  - "Georgia Institute of Technology"
  - "Intel Corporation"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3696090"
code_url: "https://github.com/sslab-gatech/RAKIS"
project_url: "https://zenodo.org/records/13800030"
tags:
  - confidential-computing
  - security
  - networking
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

R AKIS 的判断是，SGX 要想安全吃到 Linux fast I/O 的红利，不能把 shared ring state、offset 和 buffer 直接信进 enclave，而要在 enclave 内维护一份经过验证的 shadow state。它把 XDP 和 io_uring 封装成小型的 FastPath Module 与 Service Module，再把能力还原成普通 UDP、TCP 和 file syscalls，因此未修改程序也能获得 exit-less I/O 的收益：相对 Gramine-SGX，UDP 吞吐最高提升到 `4.6x`，`fstime` 写入性能提升到 `2.8x`。

## 问题背景

SGX 把计算保护进 enclave，却把 I/O 成本抬得很高。一次普通的 `send`、`recv`、`read` 或 `write`，都要先把参数拷到 enclave 外，执行 `EEXIT`，让不可信 OS 代跑 syscall，再 `EENTER` 回来；论文引用的最小 enclave-exit 成本是 `8200` CPU cycles，而 I/O-intensive 的 SGX workload 最多会慢到 `5x`。像 Gramine 这样的 LibOS 能让未修改程序继续运行，但 syscall 热路径依旧要频繁出 enclave。

另一条思路是把更激进的 bypass stack 搬进 enclave，不过代价并不小。先前方案往往把 DPDK、SPDK 这一类 user-space I/O stack 拉进 TCB，不仅默认不少 OS-side helper 可以合作，还带来更重的部署要求。更麻烦的是，XDP 和 io_uring 暴露出来的是 shared-memory rings 和更底层的接口语义：host 一旦恶意篡改 index、offset 或 pointer，enclave 内的代码就可能被带偏；而这些接口本身也和未修改程序期待的 POSIX syscall 语义对不上。

## 核心洞察

R AKIS 最值得记住的一点，是把可信边界缩到 Linux fast-I/O primitive 本身的交界面，而不是在 enclave 里再塞一套庞大的 trusted user-space I/O stack。只要 enclave 内保存 ring control state 的 trusted shadow，对 host 提供的 pointer、index、offset、status code 全部先验证再使用，并且所有数据都先从 shared untrusted memory 安全搬进 enclave，再交给上层处理，那么 XDP 和 io_uring 就可以留在 hot path 上，而不必让每次 I/O 都触发 enclave exit。

有了这条窄边界之后，再往上补一层薄薄的 service 即可。R AKIS 在 XDP 之上接一个 UDP/IP stack，在 io_uring 之上接一个同步 `SyncProxy`，于是应用看到的仍是 `send`、`recv`、`read`、`write`、`poll`。这两层缺一不可：只有 fast path，接口太低，不足以承载未修改程序；只有 syscall 兼容层，又回到了高开销的旧路。

## 设计

整套系统分成四块。enclave 内的 FastPath Module（FM）是唯一直接碰 shared untrusted FIOKP state 的部分。启动时，它检查 file descriptor 是否有效，并确认 XSK 的四个 rings、UMem，以及 io_uring 的 rings 互不重叠且完全位于 enclave 外。运行时，FM 在 enclave 里维护每个 ring 的 trusted producer 和 consumer shadow，持续保证 `0 <= (P_t - C_t) <= S_t`。对 XDP，它还维护每个 UMem frame 的 ownership map，来自 `xRX` 或 `xCompl` 的 frame 只要不符合预期，就直接拒绝并前移 consumer；对 io_uring，它会核对 completion offset 和 status code。作者没有把 `libxdp` 或 `liburing` 放进 TCB，因为前者连同依赖超过 `130K` 行代码，后者也超过 `35K` 行，而且它们默认 host OS 值得信任。

Service Module（SM）负责把这些低层 primitive 重新包装成 syscall 语义。UDP 路径上，作者把 LWIP 从 `80K+` 行裁到 `5K` 行以内，并把单一全局锁改成更细的读写锁，让 XSK FM 线程在 UMem、trusted memory 与 socket queue 之间搬运 packet。TCP 和 file I/O 则交给 per-thread 的 `SyncProxy`，它把同步请求转给对应的 io_uring FM，再等待完成。集成在 Gramine 里的 API shim 负责把支持的 I/O syscalls 重定向到这些服务，所以应用本身不用改。

enclave 外还有一条 Monitor Module（MM）线程，持续盯着 shared memory 中的 producer 值，并在需要时替 FM 发 `recvfrom`、`sendto` 或 `io_uring_enter`，把少数唤醒型 syscall 留在 enclave 外。由于这条 cross-boundary 路径仍然敏感，R AKIS 还专门配了一个 Testing Module（TM）：FM 用 KLEE 做 model checking，UDP/IP stack 用 AFL++ 做 fuzzing。

## 实验评估

实验全部在一台 `48`-core Xeon Gold 6312U、`64 GB` RAM、`25 Gbps` loopback NIC 的机器上完成，对比 `Native`、`Gramine-Direct`、`Gramine-SGX`、`Rakis-Direct`、`Rakis-SGX` 五种环境。最能说明问题的是 UDP。`iperf3` 里，`Gramine-SGX` 相比 `Gramine-Direct` 吞吐平均掉 `78%`，相对 native 掉 `83%`；`Rakis-Direct` 平均反而比 native 高 `11%`，而 `Rakis-SGX` 基本不比 `Rakis-Direct` 更慢。QUIC `Curl` 下载里，`Gramine-SGX` 平均要花 native 的 `2.5x` 时间，而 R AKIS 不论在 SGX 内外都接近 native。UDP `Memcached` 上，R AKIS 在 `1` 到 `4` 个 server threads 下都能贴住 native，并且相对 `Gramine-SGX` 带来 `4.6x` 的吞吐提升。

TCP 和 file I/O 的收益就没这么干脆，但主结论仍站得住。`fstime` 里，`Rakis-SGX` 仍比 `Gramine-SGX` 快 `2.8x`，只是同步写入要绕过 asynchronous `io_uring`，再叠加 enclave 到 shared memory 的 copy，所以离 native 还有距离。`Redis` 上，`Rakis-SGX` 比 `Gramine-SGX` 快 `2.6x`，但相对 native 仍有大约 `40%` 开销；`MCrypt` 则只比 native 多 `3%`，同时比 `Gramine-SGX` 少 `10%` 的执行时间。就验证论文核心论点而言，这组实验是有说服力的：Native、Direct、SGX 三层拆开之后，enclave exit 的代价被单独照出来了。真正的缺口在横向比较和环境广度上，作者没有和另一个 SGX fast-I/O 系统正面比，也只做了单机 loopback 测试。

## 创新性与影响

这篇论文的创新点，不在于发明了新的 kernel primitive，而在于给现有 primitive 划出一条足够小、又能被验证的 trusted boundary。和把 DPDK 整包搬进 enclave 的方案相比，R AKIS 只信最小的一段 cross-boundary wrapper；和通用的 switchless syscall 方案相比，它又利用 XDP、io_uring 的 ring 结构，把 index、offset 和 ownership 的检查做得很具体。对做 confidential-computing runtime、LibOS 或 secure network service 的人来说，这篇论文给出了一条比巨型 enclave I/O stack 更务实的路。

## 局限性

限制也很明确。R AKIS 自身不保证 I/O payload 的 confidentiality 或 integrity，应用仍要依赖 TLS、WireGuard 等更高层协议。XDP 路径只覆盖 UDP，没有把完整 TCP stack 放进 enclave；当前实现也不支持 `epoll`，所以 `Redis` 只能改用 `select`。此外，系统需要额外 helper threads 和 shared buffers，资源成本并不是零。

安全验证方面，结论也不是封顶式的。KLEE 不能真实建模 host interaction，也不理解 trust-aware memory semantics；AFL++ 的 fuzzing 还是单线程的，覆盖率是 `84%` line 和 `76%` branch，因此 race bug 或未覆盖状态仍可能残留。最后，最强的性能收益主要出现在 UDP；io_uring 这条路径对 native 依然有可见差距。

## 相关工作

- _Thalheim et al. (EuroSys '21)_ - Rkt-Io 把 DPDK 放进 SGX 做 direct I/O，R AKIS 则把 Linux 的 XDP 和 io_uring 留在 trust boundary 外，只验证共享控制面和数据面。
- _Orenbach et al. (EuroSys '17)_ - Eleos 通过 switchless OS services 减少 enclave exit，但没有像 R AKIS 这样围绕具体 fast-kernel primitives 构建 certified wrappers。
- _Tsai et al. (ATC '17)_ - Graphene-SGX 代表未修改程序在 SGX 中运行的 LibOS 路线，R AKIS 是沿着这条路线把 I/O 快路径单独重做了一遍。
- _Poddar et al. (NSDI '18)_ - SafeBricks 关注 SGX middlebox 与 direct packet I/O，R AKIS 面向的是更一般的未修改 UDP、TCP 和 file applications。

## 我的笔记

<!-- 留空；由人工补充 -->
