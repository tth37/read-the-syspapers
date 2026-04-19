---
title: "R AKIS: Secure Fast I/O Primitives Across Trust Boundaries on Intel SGX"
oneline: "R AKIS wraps XDP and io_uring in enclave-side validated fast paths, letting unmodified SGX applications use exitless UDP, TCP, and file I/O without importing huge bypass stacks."
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

R AKIS argues that SGX enclaves can use Linux fast I/O primitives safely if the enclave never trusts shared ring state, offsets, or buffers directly. It wraps XDP and io_uring in small enclave-resident modules that keep trusted shadow state, validate every cross-boundary transition, and re-expose ordinary UDP, TCP, and file syscalls to unmodified applications, yielding up to `4.6x` higher UDP throughput than Gramine-SGX and `2.8x` faster file writes on `fstime`.

## Problem

SGX protects computation but makes kernel I/O expensive. A normal `send`, `recv`, `read`, or `write` from inside an enclave copies arguments to untrusted memory, executes `EEXIT`, lets the OS perform the syscall, then re-enters with `EENTER`; the paper cites a minimum enclave-exit cost of `8200` CPU cycles and notes that I/O-intensive SGX workloads can slow down by up to `5x`. LibOSes such as Gramine preserve compatibility with unmodified applications but still pay this exit tax on the hot path.

The obvious performance alternative is to bypass the kernel more aggressively, but prior SGX work typically imports DPDK- or SPDK-style user-space stacks into the enclave. That increases TCB size, assumes trusted OS-facing helper code, and often adds deployment constraints. XDP and io_uring look attractive because they already exist in Linux, but they expose shared-memory rings and low-level semantics that a malicious host can tamper with, and they do not match the POSIX interfaces expected by unmodified applications.

## Key Insight

The paper's central claim is that the trusted boundary should be a tiny, certified wrapper around the Linux fast-I/O primitives themselves, not a large trusted user-space I/O stack. If the enclave keeps trusted copies of ring control state, validates every host-supplied pointer, index, offset, and status value before use, and takes responsibility for moving data from shared untrusted memory into enclave memory, then XDP and io_uring can sit on the enclave hot path without forcing enclave exits.

Once that narrow boundary is in place, a second thin layer can rebuild the higher-level contract applications actually want. R AKIS places a UDP/IP stack above XDP and a synchronous proxy above io_uring, so existing programs can keep using `send`, `recv`, `read`, `write`, and `poll` unchanged. The combination is the point: exitless fast paths alone are too low-level for unmodified applications, while syscall compatibility alone is too slow.

## Design

R AKIS has four modules. Inside the enclave, the FastPath Module (FM) is the only code that directly touches shared untrusted FIOKP state. At initialization it validates file descriptors and checks that the XSK rings, UMem region, and io_uring rings are non-overlapping and entirely outside enclave memory. During execution it maintains trusted shadow copies of each ring's producer and consumer indices and enforces the invariant `0 <= (P_t - C_t) <= S_t`. For XDP, it also tracks ownership of every UMem frame, refusing unexpected or overlapping frames returned through `xRX` or `xCompl`; for io_uring, it validates completion offsets and status codes. The authors deliberately avoid `libxdp` and `liburing`, noting that those libraries assume a trusted OS and would add more than `130K` lines of code plus dependencies and more than `35K` lines of code, respectively.

The Service Module (SM) translates those low-level primitives back into syscall-compatible services. On the UDP side, the authors trim LWIP from over `80K` lines to under `5K`, replace its global lock with finer-grained read/write locks, and let XSK FM threads move packets between UMem, trusted memory, and socket queues. For TCP and file I/O, a per-thread `SyncProxy` forwards synchronous requests to a per-thread io_uring FM and blocks until completion. An API shim integrated into Gramine reroutes supported I/O syscalls into these services, so applications stay unmodified.

Outside the enclave, a Monitor Module (MM) watches producer indices in shared memory and issues the occasional `recvfrom`, `sendto`, or `io_uring_enter` needed to wake the kernel-side processing of XDP and io_uring. That keeps these wakeup syscalls off the enclave hot path. Because this boundary remains security-sensitive, R AKIS also includes a Testing Module (TM): the FM is model-checked with KLEE against ring-state and memory-access constraints, and the UDP/IP stack is fuzzed with AFL++.

## Evaluation

Evaluation runs on a single `48`-core Xeon Gold 6312U machine with `64 GB` RAM and a `25 Gbps` looped-back NIC, across five environments: Native, Gramine-Direct, Gramine-SGX, Rakis-Direct, and Rakis-SGX. The UDP results provide the cleanest evidence for the paper's core claim. In `iperf3`, Gramine-SGX loses `78%` throughput versus Gramine-Direct and `83%` versus native because every UDP operation exits the enclave. Rakis-Direct, by contrast, is on average `11%` faster than native, and Rakis-SGX adds no measurable extra overhead over Rakis-Direct because both use shared-memory fast paths. In QUIC `curl`, Gramine-SGX takes `2.5x` longer than native to download files, while R AKIS inside and outside SGX stays close to native. In UDP `Memcached`, R AKIS matches native across `1` to `4` server threads and improves throughput by `4.6x` over Gramine-SGX.

The TCP and file-I/O story is more mixed but still favorable to the paper's main comparison target. In `fstime`, Rakis-SGX remains `2.8x` faster than Gramine-SGX, yet still trails native because synchronous writes are forced through asynchronous `io_uring` plus enclave-to-shared-memory copies. In `Redis`, Rakis-SGX is `2.6x` faster than Gramine-SGX but still carries about `40%` overhead versus native; `MCrypt` is within `3%` of native and reduces execution time by `10%` relative to Gramine-SGX. The workloads do exercise the stated bottleneck, and the Native/Direct/SGX split makes enclave-exit costs visible. The main evaluation gap is breadth: the authors do not compare against another SGX fast-I/O system and only test on a single-machine loopback setup.

## Novelty & Impact

R AKIS is novel less because it invents new kernel mechanisms than because it defines a minimal trusted boundary for existing ones. Compared with DPDK-in-enclave designs, it refuses to pull a whole bypass stack into SGX; compared with generic switchless-syscall approaches, it uses the specific structure of XDP and io_uring to validate ring indices, offsets, and ownership precisely. That makes it a strong reference point for confidential-computing runtimes, LibOS authors, and system builders who want Linux fast paths without paying for a massive enclave TCB.

## Limitations

Several limitations are explicit. R AKIS does not itself provide confidentiality or integrity for I/O payloads; applications still need TLS, WireGuard, or similar protocols. The XDP path only supports UDP, not a full in-enclave TCP stack, and the current implementation lacks `epoll`, forcing Redis to use `select`. The design also needs extra helper threads and shared buffers, so it is not free in resource terms.

The assurance story is also partial. KLEE cannot model real host interactions or trust-aware memory semantics, and the AFL++ campaign is single-threaded with `84%` line coverage and `76%` branch coverage, so race bugs or uncovered parser states could remain. Finally, the strongest gains appear on UDP; the io_uring path still leaves visible overhead versus native execution.

## Related Work

- _Thalheim et al. (EuroSys '21)_ - Rkt-Io uses DPDK inside SGX for direct I/O, whereas R AKIS keeps Linux XDP and io_uring outside the enclave boundary and validates only the shared control and data path.
- _Orenbach et al. (EuroSys '17)_ - Eleos reduces enclave exits with switchless OS services, but it does not build certified wrappers around specific fast-kernel primitives for unmodified POSIX applications.
- _Tsai et al. (ATC '17)_ - Graphene-SGX represents the LibOS path for running unmodified applications in SGX, and R AKIS plugs into that style of stack while rebuilding only the I/O fast path.
- _Poddar et al. (NSDI '18)_ - SafeBricks shields network functions with SGX and direct packet I/O, while R AKIS targets more general unmodified UDP, TCP, and file applications with a smaller enclave-resident code footprint.

## My Notes

<!-- empty; left for the human reader -->
