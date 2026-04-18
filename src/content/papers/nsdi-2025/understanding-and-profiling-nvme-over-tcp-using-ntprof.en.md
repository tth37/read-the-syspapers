---
title: "Understanding and Profiling NVMe-over-TCP Using ntprof"
oneline: "ntprof treats NVMe/TCP as a chain of software switches and combines kernel tracepoints with probe commands to localize latency, contention, and hardware bottlenecks with low overhead."
authors:
  - "Yuyuan Kang"
  - "Ming Liu"
affiliations:
  - "University of Wisconsin-Madison"
conference: nsdi-2025
code_url: "https://github.com/netlab-wisconsin/ntprof"
tags:
  - storage
  - networking
  - observability
  - disaggregation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`ntprof` is a profiling system for Linux NVMe-over-TCP that treats the storage path like a lossless switched network. By attaching tracepoint-based profiling agents to each software stage and querying them with TPP-like probe commands, it can break down latency, isolate software and hardware bottlenecks, and diagnose cross-tenant interference while adding little overhead.

## Problem

The paper starts from a practical gap: NVMe/TCP is getting deployed, but developers still lack a first-class profiler for understanding how requests actually move through the protocol stack. In Linux, an I/O traverses the block layer, the initiator-side `nvme-tcp` transport, the TCP/IP stack, the target-side `nvmet-tcp` transport, the target block layer, and finally the NVMe device. Each layer has its own queues, concurrency policy, and scheduling behavior, and the critical path spans two hosts.

That makes ad hoc diagnosis weak. A developer can combine application benchmarks, `perf`, `blktrace`, `iperf3`, `qperf`, and SSD utilities, but each tool only reports one slice of the system. The paper's motivating example is telling: once the target SSD is loaded, throughput drops from `1441.0 MB/s` to `625.0 MB/s` and average latency rises from `867.1 us` to `1999.6 us`, yet `perf` shows nearly identical top functions in both cases and network tools only say the link has enough bandwidth. The operator learns that the system is slower, but not where the queue buildup starts or which stage is responsible.

The hard part is not just instrumentation volume. NVMe/TCP workloads vary in size, read/write mix, access pattern, and concurrency. Linux also exposes multi-queue block interfaces, multi-connection sessions, and per-core execution that can remap requests as load changes. So the paper's real target is a profiler that follows an I/O horizontally across hosts and vertically across software layers, while staying cheap enough to co-locate with the workload being studied.

## Key Insight

The central insight is to stop thinking of NVMe/TCP as an opaque storage stack and instead model it as a lossless switched network. In that view, the initiator sends request "packets," the target returns responses, and every on-path module behaves like a buffered software switch with its own queueing discipline. Once the path is expressed that way, latency attribution and bottleneck localization become telemetry problems rather than post hoc log correlation problems.

That reframing gives the authors two useful abstractions. First, each layer can be modeled with a small queueing family, such as centralized FCFS, split FCFS, or processor-sharing. Second, each I/O can carry a profiling record that accumulates timestamps as it crosses those stages. The paper's claim is that this is rich enough to reconstruct end-to-end latency breakdowns, interference, and congestion points without instrumenting every line of code or forcing developers to manually stitch together unrelated tools.

## Design

`ntprof` has four main pieces. The first is a profiling task specification. A user tells the system what I/Os matter, such as request type and size, which NVMe/TCP session to watch, how the application and queues are configured, whether profiling is online or offline, the sampling frequency, and what report should be produced. This is important because the paper is not building a single canned report; it is building a queryable profiling substrate.

The second piece is the path model. The paper maps the NVMe/TCP request/response path into nine logical stages, from `blk_mq` on the initiator to the target SSD, and treats each stage as a queueing switch. That lets `ntprof` reason about queue occupancy and delay even when direct timestamps are only available at key transitions. The model is deliberately higher level than the kernel call graph, but low level enough to separate issues such as transport-queue contention, target-core saturation, TCP stack delay, and SSD service delay.

The third piece is the programmable profiling agent. The implementation adds tracepoints to both `nvme-tcp` and `nvmet-tcp`, then registers callbacks that create or update one profiling record per I/O. Each record stores request metadata plus an event list of timestamped stage transitions. Predicates derived from the task specification filter out irrelevant I/Os, so a run can focus on, for example, only 4 KB reads or only one session. The paper reports per-I/O record sizes on the order of a few hundred bytes depending on the request type.

The fourth piece is a query path inspired by Tiny Packet Programs. `ntprof` defines special `ProbCmd` and `ProbResp` capsules that travel through the existing NVMe/TCP machinery. A probe carries simple load, store, and reset instructions naming the software switch and statistic of interest. Each switch executes the instructions relevant to it, can duplicate the probe toward all egress paths, and replies directly with profiling results. A user-space analyzer then calibrates timestamps, validates queueing estimates against occupancy and concurrency information, and runs a map-reduce-style aggregation pipeline to produce JSON reports. The implementation is about `10K` lines across kernel patches, a new module, and a user-space utility.

## Evaluation

The evaluation is framed as six case studies rather than a single benchmark score, which fits the paper's goal. On CloudLab testbeds, the first result is fine-grained latency decomposition. For 4 KB random reads, increasing `iodepth` from `1` to `32` makes the combined network-adjacent stages `S3-S5(S+C)` grow from `14.3 us` to `127.0 us`; at the highest depth, those stages account for `92.2%` of total latency. For 128 KB sequential writes, the dominant cost shifts to `S6-S9(S+C)`, which rises from `79.2 us` to `2234.9 us`, with `95.9%` of that time on the target side. This is the kind of answer ordinary CPU profilers do not provide.

The second result is bottleneck localization. In a target-core bottleneck scenario, throughput rises only from `252.4 MB/s` to `284.9 MB/s` while latency jumps from `238.7 us` to `431.0 us`. The paper introduces Latency Amplification Degree, or `LAD`, to identify which stage's delay grows most under load, and uses it to pinpoint the overloaded completion-side target stage. In a separate TCP connection bottleneck experiment, consolidating more jobs onto too few connections drives the `S1` `LAD` as high as `51`, which correctly identifies insufficient connection parallelism at the initiator.

The third result is that the same machinery can distinguish hardware bottlenecks and interference patterns. When a local writer contends for the target SSD, remote bandwidth falls to `627.2 MB/s` and latency rises to `1984.6 us`, with the target-side storage stages showing the highest `LAD`. When `16` `iperf3` clients contend for the NIC, read latency grows from `834.9 us` to `2803.5 us`, and the transport-stack stages show a `4.5` `LAD`. In a mixed 4 KB and 128 KB read experiment, throughput of the latency-sensitive 4 KB flow drops by `26.7%`, `71.5%`, and `73.1%` across three sharing patterns, and `ntprof` can tell whether the culprit is a shared target queue or shared initiator transport state. The real-application case studies on Apache IoTDB and F2FS make the same point: the profiler surfaces when one session, a busy NIC, or a busy SSD is the true limiter. Overhead is modest, with CPU usage increasing by `0.6%` for read cases and `2.9%` for write cases, and memory rising by at most `17 MB`.

The evidence supports the paper's core claim that `ntprof` is a useful diagnosis tool. It does not prove that every modeled delay is exact in an absolute sense, but it does show consistent, actionable attribution across synthetic and application workloads.

## Novelty & Impact

This paper's novelty is mostly in observability, not in a new storage protocol. Relative to active-network telemetry systems such as TPP, it transports the idea of programmable in-band querying into a host software stack whose path crosses the block layer, network stack, and remote SSD. Relative to Linux performance tools such as `perf`, it gives a request-centric, end-to-end view instead of per-function hotspots. Relative to remote-storage systems such as `i10`, it does not redesign the datapath; it makes the existing Linux NVMe/TCP datapath inspectable.

That positioning matters. Researchers working on storage disaggregation, host-stack bottlenecks, or NVMe/TCP scheduling can use `ntprof` as a measurement substrate. Operators can use it to answer practical questions about queue depth, session count, interference, and hardware saturation. The paper is likely to be cited not because `ntprof` is the final profiler, but because it defines a concrete methodology for turning a layered storage protocol into a queryable telemetry surface.

## Limitations

The system is tightly tied to the Linux in-kernel NVMe/TCP implementation, specifically the code paths and tracepoints added around kernel `5.15.143`. The paper discusses an eBPF-based variant and an SPDK extension, but those are future directions rather than evaluated artifacts. If a deployment uses kernel bypass or a heavily modified vendor stack, the implementation does not carry over directly.

The attribution quality also depends on the queueing model and the chosen tracepoints. `ntprof` timestamps many important boundaries, but not every internal transition, so some delay accounting is reconstructed through calibration rather than observed directly. That is a reasonable engineering tradeoff, yet it means the profiler is best understood as a structured diagnostic system, not a perfect ground-truth recorder.

The evaluation is convincing but still limited in scope. Most experiments use two-node CloudLab setups and curated contention scenarios. The paper shows low overhead, but it does not exhaustively quantify how probe frequency, buffer size, and long-running online monitoring interact at larger scales. It also notes that executing a probe temporarily blocks the local profiling agent, so there is still a measurement-versus-intrusion tradeoff to manage.

## Related Work

- _Jeyakumar et al. (SIGCOMM '14)_ - `TPP` provides the active, in-band query model that `ntprof` adapts from packet switches to the NVMe/TCP I/O path.
- _Hwang et al. (NSDI '20)_ - `i10` redesigns remote TCP storage for lower overhead, while `ntprof` keeps the existing Linux NVMe/TCP stack and focuses on explaining where time is spent.
- _Haecki et al. (NSDI '22)_ - `NSight` diagnoses end-host network latencies at fine granularity, whereas `ntprof` extends that style of reasoning across block, transport, and storage-device stages.
- _Liu et al. (NSDI '23)_ - `Hostping` localizes intra-host RDMA bottlenecks; `ntprof` targets NVMe/TCP and adds per-I/O records plus in-band query support across initiator and target.

## My Notes

<!-- empty; left for the human reader -->
