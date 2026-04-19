---
title: "SuperFE: A Scalable and Flexible Feature Extractor for ML-based Traffic Analysis Applications"
oneline: "SuperFE compiles feature policies into switch-side metadata batching plus SmartNIC-side streaming reduction, letting ML traffic-analysis pipelines keep up with multi-100Gbps links."
authors:
  - "Menghao Zhang"
  - "Guanyu Li"
  - "Cheng Guo"
  - "Renyu Yang"
  - "Shicheng Wang"
  - "Han Bao"
  - "Xiao Li"
  - "Mingwei Xu"
  - "Tianyu Wo"
  - "Chunming Hu"
affiliations:
  - "Beihang University"
  - "Tsinghua University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696081"
tags:
  - networking
  - smartnic
  - ml-systems
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SuperFE compiles feature-extraction policies into switch-side grouping plus SmartNIC-side streaming reduction. Its MGPV format stores packet metadata once at the coarsest group and carries an index to finer-grained keys, so multi-granularity extractors do not duplicate switch state. The prototype rewrites ten prior extractors in 9-101 lines, cuts switch-to-NIC traffic by over 80%, keeps Kitsune feature error below 4%, and reports nearly two orders of magnitude more throughput than software extractors.

## Problem

The paper's starting point is that the detector side of ML-based traffic analysis has advanced faster than the feature extractor in front of it. In many deployments, the extractor is still a software pipeline based on port mirroring, packet storage, and server-side reconstruction of the features the model needs. That is flexible, but it scales poorly to multi-100Gbps links because it duplicates traffic, stores too much of it, and spends CPU turning packets back into statistics.

Pure hardware offload does not solve the problem either. Existing switch- or NIC-based designs often target one feature family or one fixed model, while real applications span website fingerprinting, botnet detection, covert-channel detection, and intrusion detection, each with different grouping and feature requirements. The missing piece is a feature extractor that keeps hardware-scale throughput without giving up application generality.

## Key Insight

SuperFE's core claim is that feature extraction should be expressed as grouped stream processing and then split by hardware capability. `groupby` and `filter` are simple, fixed, and highly effective at shrinking traffic, so they belong on the programmable switch. `map`, `reduce`, `synthesize`, and `collect` need richer arithmetic and state, so they belong on the SmartNIC.

The crucial detail is the boundary between the two. Sending raw packets to the SmartNIC would recreate the original bottleneck, while fully computing features on the switch would exceed switch limits. SuperFE instead batches only the packet metadata required downstream, preserves enough information to recover multiple grouping granularities later, and lets the SmartNIC finish the feature vector with memory-efficient streaming algorithms.

## Design

SuperFE exposes a high-level policy language over packet tuples, where tuples combine parsed header fields with switch-generated metadata. The same operators can describe per-flow statistics, histograms, or direction sequences.

The central switch-side mechanism is Multi-granularity GPV. Instead of storing one packet-vector copy per grouping granularity, MGPV groups packets at the coarsest granularity, stores each packet's metadata once, and attaches an index into a synchronized table of finest-granularity keys. Short and long buffers match the long-tail distribution of flow sizes, and entries are evicted on collision, buffer fill, or timeout; an aging mechanism driven by recirculated internal packets reclaims inactive state in the data plane.

The SmartNIC executes the remaining operators with streaming algorithms rather than exact multi-pass computations. Mean and variance use Welford's online update, cardinality uses a HyperLogLog-style estimator, and histogram-derived features such as `ft_hist`, `ft_percent`, and `f_cdf` are maintained from per-group bins. The implementation also exploits NFP hardware details by reusing the switch-computed hash, hiding memory latency with hardware threads, reducing expensive division, and placing state across CLS, CTM, IMEM, and EMEM with an ILP-based layout.

## Evaluation

The prototype uses a 3.3 Tb/s Intel Tofino switch and two 40Gbps Netronome NFP-4000 SmartNICs, with real-world MAWI, enterprise, and campus traces plus four public application traces. For TF, N-BaIoT, NPOD, and Kitsune, the paper reports multi-100Gbps raw-traffic support and roughly Gbps feature-vector output, summarized as nearly two orders of magnitude more throughput than software extractors.

The mechanism-level results support the design. Policy rewrites stay compact at 9-101 lines. MGPV reduces both the packet rate and throughput sent to the SmartNIC by over 80%, while avoiding GPV's linear resource growth as more grouping granularities are used. On the SmartNIC, streaming algorithms keep memory use within device limits, scale almost linearly to 120 cores across two NICs, and gain up to 4x throughput when all low-level optimizations are enabled. For fidelity, Kitsune feature error stays below 4% and the downstream detector remains accurate across datasets.

## Novelty & Impact

The novelty is the decomposition, not the individual devices. SuperFE combines a policy language that targets switch and NIC, a metadata format that supports multi-granularity grouping without duplication, and a SmartNIC runtime built around streaming reduction rather than exact offline reconstruction. That is a concrete template for building reusable traffic-analysis pipelines on heterogeneous network hardware.

## Limitations

MGPV assumes the relevant granularities can be arranged as a dependency chain; the paper leaves more general dependency graphs to future work. SuperFE also accelerates only the feature extractor, not the downstream detector, so a deployment still needs enough backend compute to consume the emitted vectors.

The evaluation is strong but not completely production-like. The lab setup replays traffic at up to 40Gbps and uses switch-side packet amplification to study larger traffic volumes, so the multi-100Gbps claim is not shown on a native multi-100Gbps end-to-end testbed. The system also accepts approximation inside the extractor through streaming summaries and histogram binning, which is reasonable for the hardware budget but not exact equivalence to a full software reconstruction.

## Related Work

- _Barradas et al. (NDSS '21)_ - FlowLens accelerates packet-distribution features in the data plane, while SuperFE aims to cover a broader feature space.
- _Siracusano et al. (NSDI '22)_ - N3IC centers the pipeline on Neural Network Interface Cards, whereas SuperFE keeps the detector open and focuses on reusable feature extraction.
- _Dong et al. (USENIX Security '23)_ - HorusEye is a targeted IoT malicious-traffic detector; SuperFE is a general feature-extraction substrate.
- _Yan et al. (NSDI '24)_ - Brain-on-Switch pushes learned analysis deeper into the switch, while SuperFE preserves more flexibility by splitting work across switch and SmartNIC.

## My Notes

<!-- empty; left for the human reader -->
