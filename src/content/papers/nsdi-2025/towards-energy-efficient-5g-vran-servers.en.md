---
title: "Towards Energy Efficient 5G vRAN Servers"
oneline: "RENC turns low-load 5G vRAN periods into a safe energy-saving mode by measuring deadline slack and coupling CPU frequency changes with MAC rate limiting."
authors:
  - "Anuj Kalia"
  - "Nikita Lazarev"
  - "Leyang Xue"
  - "Xenofon Foukas"
  - "Bozidar Radunovic"
  - "Francis Y. Yan"
affiliations:
  - "Microsoft"
  - "MIT"
  - "University of Edinburgh"
  - "Microsoft and UIUC"
conference: nsdi-2025
tags:
  - energy
  - networking
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

RENC saves CPU energy in commercial 5G vRAN servers by creating explicitly safe low-load intervals, then lowering core and uncore frequency only inside those intervals. It measures deadline slack without source code by combining kernel eBPF hooks for interrupt-driven threads with light binary instrumentation for busy-polling PHY threads. In the authors' testbed, that cuts CPU power by up to 45% and whole-server power by 29% during low traffic.

## Problem

The paper starts from an uncomfortable fact about virtualized RAN deployments: the DU server is a large energy consumer, but operators cannot simply reuse ordinary CPU power-management policies. A commercial 5G DU has hard realtime deadlines tied to the 500 us transmission time interval. Missing them is not a soft slowdown; it can cause dropped calls, malfunction, or even crash the vRAN software. At the same time, the load is bursty at sub-millisecond timescales. Two adjacent TTIs can go from almost idle to worst-case work because of a traffic burst or a control-plane event.

General-purpose CPU mechanisms are a bad fit for that regime. Deep sleep states such as C6 have a 600 us residency time and 170 us wakeup latency on the paper's Ice Lake platform, which already exceeds the 5G TTI budget. Firmware-driven P-state control is also too slow: Intel HWP reacts in roughly 60 ms for core frequency and around 10 ms for the uncore, while the DU needs decisions at millisecond scale. This is why production vRAN deployments often keep CPUs at high frequency all the time.

The second obstacle is organizational rather than algorithmic. Commercial vRAN stacks are usually proprietary binaries, so the operator cannot freely insert instrumentation or rewrite scheduling logic inside every vendor implementation. Existing energy-aware realtime techniques assume more code visibility than operators actually have. The authors also show that low utilization is common enough to matter: in their LTE traces, more than half of 50 ms windows in one busy cell and 60-80% in another stay below 1% of peak traffic. The challenge is therefore not finding opportunities, but exploiting them without violating deadlines in closed-source software.

## Key Insight

RENC's central claim is that vRAN energy management becomes feasible once the system isolates low-load intervals from the rare TTIs that consume nearly the whole deadline. If slack is measured across all time, a single spike drives the minimum slack close to zero and blocks any safe frequency reduction. If the system first carves out intervals with very low traffic and no expensive control operations, the remaining execution windows often have substantial slack and can tolerate lower CPU frequency.

That observation changes both the control policy and the measurement strategy. Instead of predicting exact per-TTI demand, RENC enforces a binary mode split. In high-load mode it does nothing clever and keeps frequency high. In low-load mode it actively protects the DU from new bursts, then measures whether threads still leave enough unused deadline fraction. Because most of the software is a black box, the paper's real insight is not just "lower frequency when idle," but "construct low-load intervals whose safety can be inferred mostly from external interfaces."

## Design

RENC is an external userspace agent plus a small in-kernel eBPF component. It needs only modest vendor cooperation: names and deadlines of realtime threads, signatures of key functions for busy-polling PHY threads, and access to standard DU telemetry and MAC control interfaces. For interrupt-driven threads such as MAC and RLC workers, RENC attaches an eBPF program to `sched_switch` and tracks when each core is active. Because Linux eBPF does not expose the DU's wall-clock notion of TTI boundaries, the paper defines a conservative "relaxed slack": the worst active fraction over any TTI-length window, not necessarily one aligned to a TTI. That makes the estimate safe even if the measurement window straddles TTI boundaries. For busy-polling PHY threads that never yield to the OS, RENC uses Dyninst plus userspace eBPF probes on a few top-level functions.

Traffic classification is equally pragmatic. RENC estimates uplink demand from per-UE buffer status reports, which arrive before the actual uplink data, and downlink demand from CU-to-DU throughput. It enters low-load mode only if all traffic samples in the last 50 ms stay below 1% of the measured per-direction maximums; it returns to high-load mode as soon as the latest sample crosses that threshold. During low-load operation, it caps the MAC scheduler to 10% of resource blocks so a sudden burst cannot arrive while the CPU is still slow.

The crucial engineering detail is transition ordering. To go from low to high load, RENC first raises CPU frequency and marks the eBPF load type as high, waits until those changes take effect, and only then removes the MAC rate limit. To go from high to low load, it applies the rate limit first, waits for that to become effective, and only then lowers core and uncore frequency. This coupling is what turns best-effort traffic shaping into a deadline-safety mechanism. RENC also handles control-plane spikes separately: it intercepts FAPI random-access messages and F1AP UE-context release messages, then temporarily forces high-load mode because those events are known to trigger expensive state setup and teardown work.

Frequency tuning itself is iterative. RENC collects low-load slack samples for an observation period, uses a 10% slack threshold, lowers the uncore first if all cores still have headroom, and then lowers individual cores. The paper prioritizes uncore because it is a major power sink and a single knob affects the whole package.

## Evaluation

The evaluation uses a commercial-grade setup rather than a toy stack: an HPE DL110 Gen10 telco server with a Xeon 6338N, Intel FlexRAN PHY, CapGemini DU/CU software, two 5G 100 MHz 4x4 cells, and up to nine commercial 5G UEs. That matters because the paper's thesis is specifically about black-box, production-style vRAN software rather than open-source prototypes.

The strongest result is idle and low-traffic power. With nine attached but idle UEs, enabling C1 plus RENC reduces CPU power from 119 W to 66 W and server power from 225 W to 160 W, i.e., 45% and 29% savings relative to the C1 baseline. Intel HWP still draws 123 W of CPU power because the realtime threads wake often enough to trick the firmware into choosing high frequencies. The performance story is also reasonably clean: SpeedTest throughput and ping are essentially unchanged with RENC, with 486-520 Mbps downlink and 29.6-29.7 Mbps uplink without RENC versus 499-520 Mbps downlink and 29.7 Mbps uplink with it, and average ping moving only from 27.1 ms to 27.9 ms.

The dynamic experiments show that RENC is not just an idle-mode hack. With nine video-streaming UEs, average CPU power falls from 121 W to 83 W because buffered video creates repeated gaps that RENC exploits. On a more mixed workload, it drops from 121 W to 109 W. The microbenchmarks also validate the mechanism: transfer time under RENC is within 2% of a static 100% RB allocation for short file transfers, and low-load slack on key threads jumps from 0-8% without RENC to 64-79% with it. Table 6 is especially useful for attribution: lowering uncore frequency alone reduces CPU power from 117 W to 80 W, and adding core scaling brings it to 67 W. The evidence supports the paper's central claim for low-load intervals, though it does not claim comparable savings at high load.

## Novelty & Impact

The paper's novelty is not a new DVFS algorithm in isolation; it is the combination of three ideas that prior vRAN energy work treated separately: externally measuring deadline slack in mostly closed-source software, explicitly creating safe low-load intervals, and coupling MAC rate limiting with frequency transitions so the low-power state is actually safe. Relative to CRT and vrAIn, RENC is much more explicit about deadline safety under commercial DU constraints. Relative to general realtime DVFS literature, it solves the missing-observability problem that operators face in practice.

This makes the paper useful to two audiences. vRAN operators and vendors get a deployable blueprint for saving energy without redesigning the PHY. Systems researchers get a more general pattern: if hard realtime software is bursty but opaque, isolating "safe intervals" and measuring conservative slack externally may be easier than trying to infer exact worst-case execution at all times. That is a real mechanism contribution, not just a measurement study.

## Limitations

RENC only optimizes low-load periods. When traffic is genuinely high, it simply retreats to the conservative baseline of maximum frequency, so the paper leaves high-load energy efficiency for future work. The thresholds are also heuristic: 1% traffic for entering low-load mode, 10% RBs while rate-limited, and a 10% slack threshold for further frequency reduction. The paper shows these are workable, but not obviously universal across hardware and radio configurations.

The claimed transparency is partial rather than absolute. RENC still needs thread names, deadlines, key function signatures for polling threads, and low-latency access to MAC telemetry/control. One busy-polling thread type in their DU is not fully instrumented and is instead manually validated at minimum frequency. The experiments are also small-scale, and the paper does not provide RU-side power measurements, so the end-to-end RAN energy story remains incomplete. Finally, comparisons to prior open-source systems are conceptual rather than same-hardware head-to-head artifact evaluations.

## Related Work

- _Pawar et al. (GLOBECOM '21)_ - CRT statically maps MAC-layer conditions to CPU frequencies, while RENC measures slack online and couples frequency changes with enforced low-load intervals.
- _Ayala-Romero et al. (MobiCom '19)_ - vrAIn jointly tunes radio and compute resources with learning-based control, but it does not target hard deadline safety in commercial black-box DUs.
- _Foukas and Radunovic (SIGCOMM '21)_ - Concordia predicts PHY execution time to let vRAN cores share compute with other workloads; RENC instead spends comparable slack on energy reduction.
- _Garcia-Aviles et al. (MobiCom '21)_ - Nuberu redesigns the PHY to better tolerate interference, whereas RENC assumes missed deadlines remain unacceptable and works with largely unmodified commercial software.

## My Notes

<!-- empty; left for the human reader -->
