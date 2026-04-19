---
title: "Moko: Marrying Python with Big Data Systems"
oneline: "Moko compiles ordinary Python data-science scripts into domain-aware IR, bridges proprietary formats with trait lifting, and dispatches each task to the best big-data backend."
authors:
  - "Ke Meng"
  - "Tao He"
  - "Sijie Shen"
  - "Lei Wang"
  - "Wenyuan Yu"
  - "Jingren Zhou"
affiliations:
  - "Alibaba Group"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3696100"
tags:
  - compilers
  - pl-systems
  - databases
  - graph-processing
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Moko is a Python-compatible execution framework that lifts mixed data-science scripts into MLIR dialects for SQL, graphs, learning, and alignment, rewrites recognizable idioms, and then searches jointly over backend systems and conversion paths. The paper reports up to 11x faster end-to-end applications, up to 28x lower data-alignment overhead, and 2.5x speedup over a hand-stitched multi-system implementation.

## Problem

Python is the language people actually use for data science because one script can mix Pandas, Torch, and NetworkX with arbitrary control flow. Once data no longer fits on one machine, however, each phase wants a different distributed system with its own API, programming model, and proprietary format, so the single-process illusion disappears.

Prior fixes all stop short. Wrappers preserve syntax but lock users into one ecosystem; compilers speed up local code but do not orchestrate distributed tables, graphs, and tensors; workflow optimizers search across engines but assume static DAGs rather than open-ended Python. The industrial fallback is hand stitching: pick the best engine per stage and serialize or convert everything in between. The paper argues that this glue, not the compute itself, often dominates runtime.

## Key Insight

The key claim is that Python-to-big-data execution should be optimized as whole-program semantic lowering plus data-format search. By lifting recognizable regions into domain-aware IR and modeling format capabilities as composable traits, the planner can jointly choose systems, rewrites, and conversions. That lets it trade off a faster engine against a more expensive output format, rewrite repeated graph queries into one multi-source primitive, and still leave unrecognized code in Python.

## Design

Moko has four components: an IR layer, a generator, an optimizer, and a runtime. The IR layer compiles Python into MLIR dialects for SQL, graphs, learning, and alignment; the generator groups IR into tasks and emits driver code for candidate backends.

Idiom recognition matches control patterns and then data patterns on that IR. A loop over repeated `nx.shortest_path` calls can be rewritten into one multi-source shortest-path operation if the backend supports it; otherwise the code stays raw Python. Data alignment uses traits: formats advertise capabilities, and Moko searches a trait-lifting path made of either method sharing or physical conversion tasks such as sort, transpose, repartition, and layout building.

The optimizer uses `g` for compute cost and `h` for execution-frame load/store cost, both calibrated offline from operator profiling. Online it enumerates physical plans and re-optimizes after each task using observed runtime and cardinality. The runtime dispatches to existing systems such as Spark, Dask, GRAPE, GraphX, Torch, and TensorFlow, with Vineyard or external storage serving as the execution frame.

## Evaluation

The prototype is about 38 KLoC of C++ and is evaluated on a 16-node AliCloud Kubernetes cluster, with 16 cores and 32 GB RAM per node.

The strongest evidence comes from three application pipelines. On fraud detection, Moko uses Spark for feature extraction, Torch for RGCN inference, and GRAPE-style graph methods on Spark dataframes, fusing repeated SSSP calls into one multi-source shortest-path operation. The result is 11x faster than plain Python and 2.5x faster than hand stitching, at 142.3% of the baseline memory. On image-based recommendation, Moko adds Dask to pre-sort KNN edges before graph construction, yielding 8.5x and 1.5x speedups over Python and hand stitching, with 100.8% of baseline memory. On who-to-follow, it keeps common-neighbor computation inside Dask instead of exporting graph data to another engine, yielding 3.5x and 1.4x speedups with 122% of baseline memory.

The microbenchmarks tell the same story. There is no universal best backend: Dask and ClickHouse win TPC-H `Q6`, Presto wins `Q17`, and graph and ML winners vary by input. Vineyard removes filesystem I/O and serialization from round trips, fusion cuts about 70% of alignment overhead, and choosing the right graph layout saves up to 42% runtime on BFS. At larger scale, Moko beats hand stitching by 31%, 39%, and 44% on 100 GB, 300 GB, and 1 TB LDBC SNB datasets, and it beats RHEEM/Musketeer by 5x/27x on cross-community PageRank plus 2.9x/3.2x on AML. What the paper does not measure directly is cost-model error for `g` and `h`.

## Novelty & Impact

Moko is not just another Python wrapper or another workflow DSL. Its novelty is the combination of domain-aware MLIR dialects, idiom-level rewriting, trait-based format alignment, and a planner that searches jointly over engines and conversions. That makes it a useful reference point for cross-engine data platforms, MLIR-based programming systems, and systems that want to keep Python as the front-end language without paying the full hand-stitching tax.

## Limitations

The prototype is still narrow. It supports only three domains and mainly three Python package families: `pandas`, `networkx`, and `torch`. Classes, generator expressions, `try`/`except`, decorators, and `async` all fall back to the Python interpreter, so the fraction of a real application that benefits is workload dependent.

The integration burden is also nontrivial. Each backend needs wrappers, equivalent operators, code templates, and cost calibration. The paper says integrating one backend took 1-5 hours and the full evaluated set took 27 hours. The strongest comparisons are also against author-built hand-stitched baselines and a small set of workflow-manager workloads, so the speedups are persuasive but not yet universal.

## Related Work

- _Agrawal et al. (VLDB '18)_ - RHEEM searches across multiple data-processing platforms, but it assumes workflow-style plans rather than open Python code with dynamic control flow and explicit proprietary-format alignment.
- _Gog et al. (EuroSys '15)_ - Musketeer also maps one logical workflow to many engines, whereas Moko starts from ordinary Python and makes data conversion part of the optimization space.
- _Spiegelberg et al. (SIGMOD '21)_ - Tuplex compiles Python UDF-heavy analytics to native code, but it does not orchestrate separate distributed systems for relational, graph, and learning tasks.
- _Palkar et al. (CIDR '17)_ - Weld offers a common runtime and IR for high-performance data analytics, while Moko keeps existing backend systems and optimizes the dispatch and alignment among them.

## My Notes

<!-- empty; left for the human reader -->
