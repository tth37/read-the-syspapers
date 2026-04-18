---
title: "Pie: A Programmable Serving System for Emerging LLM Applications"
oneline: "Pie replaces the fixed LLM serving loop with inferlets that directly control KV pages, generation steps, and tool I/O inside one serving runtime."
authors:
  - "In Gim"
  - "Zhiyao Ma"
  - "Seung-seob Lee"
  - "Lin Zhong"
affiliations:
  - "Yale University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764814"
code_url: "https://github.com/pie-project/pie"
tags:
  - llm-inference
  - caching
  - scheduling
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pie argues that emerging LLM applications are not well served by a closed prefill-decode loop. It exposes LLM serving as fine-grained handlers that user programs, called inferlets, can compose to control KV-cache state, decoding steps, and external I/O inside one runtime. On standard text completion this costs only 3-12% latency, while on more complex workflows it enables 1.1x-2.4x lower latency and 1.3x-3.4x higher throughput.

## Problem

The paper starts from a mismatch between modern LLM applications and the serving stacks that dominate today. Systems such as vLLM and TGI assume that each request is one prompt that should move through a monolithic prefill-and-decode loop under global policies. That design works for straightforward text completion, but it becomes restrictive once the application wants to reason with branching structures, manipulate attention state directly, or interleave generation with tool calls and other computations.

The authors isolate three concrete failures. First, KV-cache management is implicit and system-wide, which makes techniques such as Graph-of-Thought, Recursion-of-Thought, beam search, and attention-sink style masking hard to express without patching the serving system itself. Second, the prediction and sampling loop is structurally fixed, so speculative decoding, grammar-constrained decoding, or stateful search procedures cannot be customized per request. Third, tool-using and agentic workflows must bounce out to the client between steps; that adds network round trips and often forces the server to discard state and re-prefill context on the next request.

## Key Insight

Pie's central claim is that the unit the serving system should host is a program, not a prompt. If the engine exposes the right low-level primitives, then the application can keep its own control logic outside the core inference backend without losing efficiency. In Pie, the application receives explicit control over resources such as `KvPage` and `Embed`, and over operations such as embedding, forward passes, sampling, communication, and network I/O.

This works because Pie separates programmability from execution efficiency. Inferlets decide what should happen next, but the system still observes their API calls, virtualizes resources, and batches compatible GPU work across many inferlets. The result is a programmable interface that is strong enough to express custom decoding and cache policies, yet structured enough for the serving system to remain a shared high-throughput backend.

## Design

Pie organizes the LLM forward path into three API categories: embed, forward, and sample. Around them it defines two primary resources: `Embed`, which holds token embeddings, and `KvPage`, which stores contiguous chunks of KV cache following a PagedAttention-style organization. Inferlets allocate and deallocate these resources explicitly, and can export or import KV pages to share cache state across inferlets.

The programming model is single-threaded and event-driven, with asynchronous API calls for concurrency. A command queue accompanies GPU-bound calls so the runtime can infer dependencies and priorities. This matters because Pie's scheduler batches work in two ways: horizontally across queues and vertically across consecutive compatible commands inside one queue. The paper positions this as the key trick that preserves throughput even though the monolithic decode loop has been dismantled.

The system itself has three layers. The application layer runs inferlets inside WebAssembly via wasmtime, which provides lightweight sandboxing and low startup cost. The control layer handles non-GPU APIs directly, virtualizes `Embed` and `KvPage` objects, manages queue priorities, and adaptively dispatches batched GPU work with a work-conserving policy. The inference layer executes those batches through specialized handlers, currently implemented with PyTorch and FlashInfer, with a native C++/CUDA version also described. Pie exposes 42 APIs in total, 18 of them directly tied to LLM execution, and uses a trait system so models can advertise which API families they support. A Rust support library then rebuilds common patterns such as autoregressive generation, sampling policies, and fork-join logic on top of these low-level calls.

## Evaluation

The evaluation is convincing because it tests both expressiveness and cost. Pie runs on a GCP `g2-standard-32` instance with one NVIDIA L4 GPU and Llama 3 1B, 3B, and 8B models in BF16. The baselines are vLLM, SGLang, LMQL, and StreamingLLM where appropriate, and the authors intentionally use FlashInfer across Pie, vLLM, and SGLang to reduce confounding from backend kernel differences.

On expressiveness, Table 2 is already informative: plain text completion takes 38 lines of inferlet code, while more advanced techniques such as speculative decoding, beam search, Tree-of-Thought, Graph-of-Thought, and several agentic workflows fit in tens to a few hundred lines. On performance, Pie's gains are largest when the application really needs programmability. For agentic workflows, Pie reduces latency by up to 15% and improves throughput by up to 30% on ReACT, with reported absolute results of 4.27 s and 29.94 agents/s for ReACT, 3.18 s and 40.18 agents/s for CodeACT, and 6.14 s and 5.21 agents/s for Swarm. For a synthetic agent workflow that exploits application-specific cache retention, early API firing, and KV dropping, the stacked optimizations reach 3.5x higher throughput than the vLLM baseline. Deliberate prompting strategies such as ToT, RoT, GoT, and SKoT see up to 28% lower latency and 34% higher throughput. Pie also matches or approaches state-of-the-art systems on features they already support, and for attention sink it outperforms the original StreamingLLM implementation by 1.5x lower latency and more than 30x higher throughput.

The cost of programmability is real but modest. The paper reports 3-12% latency overhead on standard text completion. On 8B Llama 3, time per output token rises from 64.06 ms in vLLM to 65.59 ms in Pie, a 2.39% increase; on 1B it rises from 16.83 ms to 18.75 ms, an 11.41% increase. The largest single source of overhead is losing the monolithic pipeline that overlaps embedding and sampling with the forward pass, not the Wasm runtime or layer crossings themselves.

## Novelty & Impact

Pie's novelty is not a better attention kernel or a faster cache allocator. Its contribution is architectural: it turns LLM serving into a programmable substrate whose abstractions are low-level enough to express genuinely new behavior. The paper is therefore both a mechanism paper and a reframing paper. It introduces concrete machinery such as inferlets, command queues, and handler-level batching, but its bigger claim is that modern LLM applications should not be forced to masquerade as plain prompt completion.

That matters for at least three groups of follow-on work: LLM serving systems that need per-application policies, agentic frameworks that currently pay round-trip and re-prefill costs, and researchers exploring new decoding or attention schemes who do not want to fork a serving engine for every experiment. If Pie's interface or philosophy is adopted, future work can compete on inferlet design rather than invasive backend modifications.

## Limitations

The paper's own limitations are substantial. Pie is centered on Transformer-style LLMs and the implementation support is currently strongest for the Llama family. The evaluated deployment is also essentially single-backend and single-node; the paper discusses multi-GPU or multi-node scale-out only as future work, so it does not demonstrate how `KvPage` locality, global scheduling, or SLO enforcement would behave in a distributed setting.

There are also important systems concerns. Security gets harder once user-provided inferlets can perform network I/O and inspect token distributions. Resource contention is handled by a simple FCFS-style policy that may terminate recently created inferlets to free capacity, which is clearly not the last word on fairness. Finally, the Python inference layer introduces measurable deserialization overhead, and the fine-grained API structure gives up some monolithic optimizations, especially pipelined sampling and embedding. The paper quantifies these costs honestly, but they imply that Pie is best read as a flexible substrate whose overhead is acceptable for many workloads, not as a universal drop-in replacement for the fastest closed-loop text generation path.

## Related Work

- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention makes KV-cache management efficient, but keeps the serving loop monolithic and applies cache policy at the system level rather than per application.
- _Lin et al. (OSDI '24)_ - Parrot introduces semantic variables to improve cache reuse for LLM applications, whereas Pie exposes lower-level execution and cache primitives that let the application define the workflow itself.
- _Gim et al. (MLSys '24)_ - Prompt Cache shows that modular attention reuse can lower latency; Pie generalizes that idea by making cache export, import, and masking application-programmable.
- _Beurer-Kellner et al. (PLDI '23)_ - LMQL programs output constraints and generation semantics, while Pie programs the serving process itself, including resource management, control flow, and I/O.

## My Notes

<!-- empty; left for the human reader -->
