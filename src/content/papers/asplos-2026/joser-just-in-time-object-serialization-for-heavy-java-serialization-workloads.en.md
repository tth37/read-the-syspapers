---
title: "JOSer: Just-In-Time Object Serialization for Heavy Java Serialization Workloads"
oneline: "Generates class-specific Java serializers at runtime, shares metadata once per class, and lets the JVM JIT turn repetitive serialization into hot optimized code."
authors:
  - "Chaokun Yang"
  - "Pengbo Nie"
  - "Ziyi Lin"
  - "Weipeng Wang"
  - "Qianwei Yu"
  - "Chengcheng Wan"
  - "He Jiang"
  - "Yuting Chen"
affiliations:
  - "Ant Group, Hangzhou, China"
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Alibaba Group, Shanghai, China"
  - "Ant Group, Shanghai, China"
  - "East China Normal University, Shanghai, China"
  - "Dalian University of Technology, Dalian, China"
  - "Shanghai Key Laboratory of Trusted Data Circulation and Governance, and Web3, Shanghai, China"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790179"
tags:
  - compilers
  - pl-systems
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

JOSer reframes Java object serialization as a JIT optimization problem instead of a fixed library problem. It generates class-specific serializers and deserializers at runtime, packs metadata once per class, and relies on the JVM to optimize those hot code paths over repeated workloads. On the paper's benchmarks it improves throughput by up to `83.7x` for serialization and `229x` for deserialization, then carries that gain into Flink and production search recommendation services.

## Problem

The paper starts from a pain point that looks mundane but is expensive in practice: large Java services spend a surprising amount of CPU time moving objects between memory, storage, and network boundaries. In the motivating Flink-based search recommendation pipeline, Kryo-backed serialization consumes more than `14%` of execution time and `22.45%` of CPU usage in a typical percentile task. That is large enough that serialization stops being background plumbing and becomes a first-order systems bottleneck.

Existing choices each fail in a different way. Static serializers such as Protobuf and FlatBuffers can be fast, but they require human-written schemas and explicit serializer invocation. That is acceptable for stable interfaces, but not for large Java codebases whose object definitions evolve quickly or are constructed dynamically at runtime. Dynamic serializers such as Java's built-in serialization, Kryo, FST, and Hessian are much more convenient, yet they rely on omni-functional serializer logic: reflection, type inspection, lookup-table dispatch, virtual calls, and many branches that must handle arbitrary object shapes.

The key argument is that these dynamic serializers are not just expensive on their own; they are also a poor fit for the JVM's optimizer. The JIT is excellent at shrinking and specializing hot, small methods, but much worse at giant serialization code paths full of polymorphism. The paper even points to concrete JVM thresholds: large methods are skipped or not inlined aggressively. So "just optimize Kryo harder" is not the same as producing a serializer that the JIT can fully digest. JOSer targets the heavy, repetitive regime where many instances of the same classes flow through long-running cloud and AI systems and where that mismatch between flexible serializers and JIT-friendly code is most costly.

## Key Insight

The core insight is that heavy Java serialization workloads are repetitive enough to justify synthesizing per-class code on demand. Once the system has seen a class, serialization no longer needs to look like "interpret an arbitrary object graph every time." It can look like "run a small, mostly straight-line program for this class again and again." That turns a flexible but branch-heavy runtime problem into a hot-code optimization problem the JVM already knows how to solve well.

Two sub-ideas make that practical. First, JOSer separates metadata from values, so the expensive class description for a type can be emitted once and reused across many objects in a stream. Second, it generates serializers that are deliberately JIT-friendly: class-specific, flat, and meta-free. "Why it works" is therefore not magic in the code generator itself, but the fact that the generator changes the optimization surface. The JIT now sees direct field accesses and small static helper methods instead of reflection-heavy generic logic. Over time, repeated invocations let the JVM inline, eliminate dead code, propagate constants, and pipeline instructions along a path tailored to one object layout.

## Design

JOSer has three main pieces. The first is a compact binary format with meta sharing. A serialized object stream stores metadata and values separately; values point to metadata entries in a metadata pool. For an object stream containing many instances of the same class, JOSer serializes the class description once and only appends values afterward. That matters both for throughput and for stream size, especially when the same schemas recur across thousands of objects.

The second piece is runtime generation of class-specific serializers. JOSer parses class metadata into an `ExprTree` that represents how to write the object's fields. Primitive writes become direct code blocks such as field loads plus buffer writes; nested custom classes recurse into more generated code. The resulting serializer is meant to be small-scale, flat, and meta-free: no reflection during the hot path, far fewer dynamic branches, and direct field access instead of generic dispatch. JOSer also keeps a serializer pool so that the first encounter with a class pays the generation cost and later encounters simply reuse the existing serializer.

The third piece is making generated code easy for the JVM to optimize. Because the JIT is sensitive to bytecode size, JOSer heuristically partitions a hot serializer into submethods so each block stays within the JVM's optimization threshold, reported as `325` bytes by default. It uses Janino to compile generated Java code into bytecode, loads the serializers at runtime, and then lets the JVM's JIT optimize them after enough invocations. Deserialization mirrors the same philosophy: JOSer generates per-class deserializers, caches them, and uses encoded field names and field types plus a two-cursor matching scheme to preserve reference integrity and schema compatibility when class layouts differ across environments.

## Evaluation

The evaluation is strong on the paper's chosen target: long-running repetitive serialization. JOSer is implemented in about `70K` lines of Java and evaluated with JMH on OpenJDK 11 against six baselines: Kryo, Hessian, FST, JDK serialization, Protobuf, and FlatBuffers. The benchmark suite covers primitive objects plus custom classes such as `Sample`, `MediaContent`, `Struct`, and `LongStruct`, and it adds two stress variants: self-references (`Benchmark R`) and schema inconsistencies during deserialization (`Benchmark I`).

The headline numbers are large. Across the eight core benchmarks, JOSer reaches `1.0E+7` to `1.4E+8` objects per second for serialization and `4.3E+6` to `8.2E+7` for deserialization. Relative to the best baseline on each workload, it improves throughput by `4.4x` on average for serialization and `2.3x` for deserialization; relative to the worst baselines, the gains rise to `83.7x` and `229x`. The paper also checks correctness-heavy cases rather than hiding behind easy workloads: on the reference-preserving and schema-evolving variants, JOSer still maintains the highest throughput, beating competitors by up to `77.6x` for serialization and `184.1x` for deserialization.

The ablation story also supports the design. Removing JIT optimization costs up to `3.95x`, while removing metadata sharing costs up to `1.49x`; removing both hurts even more. On object streams of `10K` schema-inconsistent objects, the metadata-packing format reduces size by `20.46%` relative to Kryo and `50.21%` relative to Hessian. The deployment results are what make the paper feel more than microbenchmark engineering: on Flink workloads, JOSer reduces serialization CPU usage by `35.32%` to `41.14%` and improves task throughput by up to `83.09x`; in a production search recommendation service, it cuts p99 latency from `350 ms` to `316 ms`, with serialization latency dropping from `50 ms` to `16 ms`. Those workloads are repetitive enough to exercise the paper's central claim fairly.

## Novelty & Impact

Relative to Kryo, Hessian, and Java's built-in serialization, JOSer is novel because it does not try to make one universal serializer less bad. It changes the unit of optimization from "a generic serialization framework" to "many tiny per-class programs that the JVM can specialize." Relative to static approaches such as Protobuf and FlatBuffers, it keeps schema-free flexibility while recovering much of the performance benefit usually associated with generated code. Relative to hardware work such as _Jang et al. (ISCA '20)_, it argues that a large part of the win can be recovered in software by aligning serialization with the JVM's existing optimization machinery.

That makes the paper likely to matter to two communities. JVM and compiler/runtime researchers can treat it as a case study in domain-specific JIT surfaces. Data-system builders can treat it as a practical recipe for reclaiming CPU in Java-heavy stream processing and service backends without rewriting everything around hand-maintained schemas. The mechanism is genuinely new in that it combines code generation, meta sharing, and JIT-aware partitioning into a serialization-specific software pipeline rather than presenting a measurement study alone.

## Limitations

The paper is candid about a few tradeoffs. JOSer caches generated serializers, so it spends extra metaspace memory to buy speed. It also keeps expensive features such as reference tracking and schema compatibility, but makes them configurable because they are not free. The security discussion notes the usual risk of dynamic deserialization; JOSer mitigates that with class registration and customizable checking policies, but the threat model does not disappear.

There are also regime limits. Primitive-type workloads benefit less because there is less complex logic for the JIT to optimize in the first place. More importantly, JOSer shines after serializers become hot. That means very short-lived or highly heterogeneous workloads should see smaller gains; this is an inference from the paper's runtime design and warmup behavior, not a number the paper quantifies directly. The evaluation is also centered on Java and repetitive cloud workloads, so it does not tell us much about mixed-language stacks, short jobs, or the operational overhead of very large class populations in one JVM.

## Related Work

- _Jang et al. (ISCA '20)_ — proposes a specialized hardware architecture for object serialization, whereas JOSer seeks similar gains in software by exposing JIT-friendly per-class code.
- _Nguyen et al. (ASPLOS '18)_ — Skyway avoids serialization by connecting managed heaps across distributed systems, while JOSer accelerates serialization itself for cases where bytes must still be materialized.
- _Taranov et al. (USENIX ATC '21)_ — Naos uses serialization-free RDMA networking, so it bypasses the problem rather than optimizing schema-free Java serialization.
- _Wu et al. (USENIX ATC '22)_ — ZCOT eliminates object transformation for analytics pipelines, complementing JOSer’s focus on retaining full serialization functionality while making it faster.

## My Notes

<!-- empty; left for the human reader -->
