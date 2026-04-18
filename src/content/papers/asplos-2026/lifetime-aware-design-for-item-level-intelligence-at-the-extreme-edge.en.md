---
title: "Lifetime-Aware Design for Item-Level Intelligence at the Extreme Edge"
oneline: "FlexiFlow picks the lowest-carbon flexible processor for each disposable edge workload by co-optimizing lifetime, execution frequency, memory, and datapath width."
authors:
  - "Shvetank Prakash"
  - "Andrew Cheng"
  - "Olof Kindgren"
  - "Ashiq Ahamed"
  - "Graham Knight"
  - "Jedrzej Kufel"
  - "Francisco Rodriguez"
  - "Arya Tschand"
  - "David Kong"
  - "Mariam Elgamal"
  - "Jerry Huang"
  - "Emma Chen"
  - "Gage Hills"
  - "Richard Price"
  - "Emre Ozer"
  - "Vijay Janapa Reddi"
affiliations:
  - "Harvard University, Cambridge, Massachusetts, USA"
  - "Qamcom Research & Technology, Karlstad, Sweden"
  - "Pragmatic Semiconductor, Cambridge, England, UK"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790182"
code_url: "https://github.com/harvard-edge/FlexiFlow"
tags:
  - hardware
  - energy
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

FlexiFlow argues that for disposable, trillion-scale edge devices built with flexible electronics, lifetime matters more than raw performance. The paper contributes a benchmark suite, a family of tiny RISC-V processors, and a carbon model that together choose when a smaller core is better because embodied carbon dominates and when a wider core is better because operational energy accumulates over time.

## Problem

The paper studies item-level intelligence (ILI): putting computation directly into products like food packaging, medical patches, and smart textiles. This is not just "smaller IoT." The target scale is trillions of devices per year, the power budget is in microwatts to milliwatts, the chips must be cheap enough for disposable goods, and product lifetimes vary from a single use to many years. Those assumptions break the default optimization logic of embedded systems, where designers often chase performance, energy, or area in isolation.

Flexible electronics are attractive because they can be fabricated on native flexible substrates at much lower cost and carbon than conventional silicon, but they come with severe limits: kHz clocks, thousands rather than billions of transistors, and very small memories. That makes conventional benchmarks and processor design points poor guides. More importantly, the authors argue that lifetime is the missing systems variable. A spoilage sensor used for a week and an air-quality monitor used for four years may run similar code, yet the right architecture changes because embodied carbon is paid once while operational carbon accumulates. Without a lifetime-aware method, large-scale deployment can lock in the wrong design and multiply that mistake across enormous volumes.

## Key Insight

The central proposition is that sustainable extreme-edge design should optimize total carbon footprint over an application's expected lifetime, not standalone PPA metrics. Once lifetime and execution frequency become first-class inputs, architecture selection stops looking like a universal ranking and becomes a boundary problem: small cores win when one-time fabrication cost dominates, while wider and more efficient cores win when repeated execution makes operational energy the larger term.

That insight also applies above the hardware level. Because the workloads are simple and long-lived in very different ways, software choices that look equivalent by accuracy or functionality can have very different carbon costs. The paper therefore frames ILI as a stack-wide co-design problem, not merely a new processor datapoint.

## Design

The work has three connected parts. First, FlexiBench is an 11-workload suite spanning 10 UN Sustainable Development Goals, from water-quality monitoring and food spoilage detection to HVAC control and tree tracking. The suite is designed to expose the heterogeneity the paper cares about: memory ranges from about `0.3 KB` to `240 KB`, dynamic work spans more than seven orders of magnitude, and deployment lifetimes range from days to years.

Second, FlexiBits is a family of tiny RISC-V processors derived from SERV. The baseline SERV core uses a 1-bit serial datapath; the authors add QERV with a 4-bit datapath and HERV with an 8-bit datapath. The design idea is simple but useful: keep the control plane largely constant and scale the datapath width to trade area against execution energy. Under the target FlexIC process, QERV and HERV cost `1.26x` and `1.54x` more area than SERV and `1.19x` and `1.41x` more power, but they reduce energy per program execution by `2.65x` and `3.50x` because they finish much sooner.

Third, FlexiFlow ties workloads and cores together with a carbon model. Users provide a workload, expected lifetime, execution frequency, and energy source. The framework profiles runtime, area, and power; models operational carbon as power times runtime times invocation count over lifetime; and models embodied carbon from die area and foundry life-cycle data. The output is not "the fastest core," but the core with minimum total carbon for that deployment. The implementation also includes memory in the system footprint and validates that the processor family can be fabricated on a flexible-electronics PDK, including a 30.9 kHz open-source tape-out.

## Evaluation

The evaluation matches the paper's thesis reasonably well because it asks exactly when architectural choices flip. Across FlexiBench, all three FlexiBits cores can run 8 of the 11 workloads today; gesture recognition, arrhythmia detection, and tree tracking remain out of reach without algorithmic or ASIC-level changes. That is a useful grounding point: the paper is not claiming flexible electronics can already do everything.

The strongest result is the lifetime-aware phase diagram in Figure 5. For every workload, the optimal core changes with lifetime and task frequency; there is no globally best design. The paper's cardiotocography example makes this concrete: SERV is carbon-optimal for about a one-week deployment, but HERV becomes optimal for the full nine-month scenario in the benchmark table, and using SERV there would raise total carbon by `1.62x`. That directly supports the main claim that lifetime-aware architecture selection matters.

The software study is arguably even more striking. For food spoilage detection, a large KNN model reaches `98.9%` accuracy while logistic regression reaches `98.2%`, yet the KNN option emits `14.5x` more carbon over a one-year deployment. This is a good example of the paper's broader point: once devices scale to trillions, "slightly better accuracy" and "much worse footprint" become a real systems trade-off rather than a footnote.

I found the evaluation convincing for relative design guidance, but less complete as a full environmental accounting. The main FlexiFlow model intentionally excludes sensors, batteries, and packaging because they are constant across processor choices; the larger at-scale analysis later reintroduces those pieces with conservative estimates. That is a fair scope choice for architecture selection, but it means the paper is strongest on comparative decisions, not on precise absolute lifecycle totals.

## Novelty & Impact

Relative to _Bleier et al. (ISCA '22)_, which showed low-footprint flexible microprocessors, this paper adds the missing deployment methodology: real workloads, multiple architecture points, and a carbon model that selects among them. Relative to _Ozer et al. (Nature '24)_, which established a bendable non-silicon RISC-V processor, FlexiFlow broadens the question from "can we build one?" to "which one should we build for this application?" Relative to _Raisiardali et al. (MICRO '25)_, which explores instruction-subset processors for the extreme edge, the novelty here is keeping a standard ISA and making lifetime-aware carbon optimization the main objective.

That makes the paper important less as a single hardware mechanism than as infrastructure for a new design space. Researchers working on flexible electronics, TinyML-like sensing applications, and sustainable computing can use it as a benchmark-and-selection framework; practitioners get a clearer argument that disposable intelligence should not inherit silicon-era design instincts unchanged.

## Limitations

The main limitation is that the paper's conclusions depend on an analytical carbon model whose inputs are partly technology-specific. The embodied-carbon data come from Pragmatic Semiconductor's process, static power dominates because of the chosen logic family, and the results may shift for different flexible-electronics stacks. The authors are transparent about this, but it narrows how far one should generalize the exact boundaries in Figure 5.

There are also capability limits. The memory requirements of some workloads exceed what current FlexIC memories comfortably support, and three workloads are still impractical on the proposed processors. The framework therefore helps choose among feasible designs, but it does not remove the need for better memories, better algorithms, or specialized accelerators. Finally, the at-scale sustainability analysis is intentionally approximate, especially for sensors and end-of-life waste, so the strongest takeaway is directional: lifetime-aware co-design can materially reduce footprint, not that the paper has fully closed the lifecycle-accounting problem for ILI.

## Related Work

- _Bleier et al. (ISCA '22)_ — FlexiCores introduced field-reprogrammable flexible microprocessors, while FlexiFlow adds a workload suite and a lifetime-aware carbon-selection method on top of flexible CPU design.
- _Ozer et al. (Nature '24)_ — Flex-RV demonstrates a bendable non-silicon RISC-V processor; this paper uses that style of processor as a building block inside a broader benchmark and optimization framework.
- _Raisiardali et al. (MICRO '25)_ — RISSPs studies instruction-subset processors for the extreme edge, whereas FlexiBits keeps a standard 32-bit ISA and explores datapath width under carbon-aware deployment constraints.
- _Bleier et al. (DATE '23)_ — prior lifetime-aware work on flexible-electronics encryption exploited short application lifetimes, but it focused on one security use case rather than an end-to-end item-level intelligence stack.

## My Notes

<!-- empty; left for the human reader -->
