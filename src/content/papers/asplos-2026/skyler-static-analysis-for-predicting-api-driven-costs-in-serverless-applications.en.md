---
title: "Skyler: Static Analysis for Predicting API-Driven Costs in Serverless Applications"
oneline: "Builds a serverless economic graph plus SMT pricing formulas to statically predict which API paths and inputs will dominate a serverless bill before deployment."
authors:
  - "Bernardo Ribeiro"
  - "Mafalda Ferreira"
  - "José Fragoso Santos"
  - "Rodrigo Bruno"
  - "Nuno Santos"
affiliations:
  - "INESC-ID / Instituto Superior Técnico, Universidade de Lisboa, Lisboa, Portugal"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790221"
code_url: "https://github.com/arg-inescid/Skyler.git"
tags:
  - serverless
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Skyler treats billable cloud APIs, not function runtime, as the center of serverless cost analysis. It builds a serverless economic graph from JavaScript plus IaC, attaches provider pricing rules, and uses SMT queries to predict dominant paths, dominant APIs, and input-sensitive bills before deployment.

## Problem

Provider calculators are only useful if developers already know invocation counts and payload sizes for each cloud service. In real serverless workflows, those quantities depend on branching, loops, asynchronous triggers, shared state, and payload-dependent billing rules. In the paper's running example, a `/createPost` request may stop after one read or expand into queueing, moderation, and database updates; because DynamoDB, SQS, and Comprehend all charge differently, the full moderation path can be `1368x` the minimal path, and increasing payload size from `1 KB` to `200 KB` can raise total cost by more than `50x`.

## Key Insight

The key move is to treat expensive API sites as first-class program objects, which the paper calls economic sinks. Skyler traces tainted inputs to those sinks across functions and resources, leaves request counts and object sizes symbolic, and postpones concrete "what if" questions to the solver. One static model can then answer path-level, input-sensitive, and cross-provider cost questions without redeploying code.

## Design

Skyler has three stages. First, it parses IaC templates and JavaScript code to build a serverless economic graph, or SEG. SEG extends MDG with event nodes, API-call nodes, loop nodes, resource nodes, and explicit control/data edges such as `CFG`, `DEP`, `TRIGGER`, and `USES`. That matters because Skyler needs more than a local call graph: it must know that an HTTP request triggers one function, that the function writes to a queue or bucket, and that the resource later triggers another function with transformed data. The construction combines intra-function object-dependency analysis with inter-function stitching from IaC-declared triggers and shared resources. The paper also notes that AWS is easier to recover statically because SDK calls often expose resource and payload information directly, whereas Azure and Google Cloud more often require provider-specific logic to resolve layered client/resource bindings.

Second, Skyler walks SEG and emits SMT-LIB constraints. It declares symbolic variables for request counts, payload sizes, loop counters, and costs; propagates counts through control flow and batching; propagates sizes through data flow; adds guard constraints from provider limits; and finally applies provider-specific pricing equations. Those equations live in pluggable service modules, so the same graph and solver can target AWS, Google Cloud, and Azure. Third, Skyler runs four query families over the symbolic model: dominant workflows, dominant APIs within a workflow, input-cost sensitivity, and cross-provider comparison. The prototype is about `5,800` lines of Python with `21` service plugins and Z3 as the solver.

## Evaluation

The evaluation goes beyond a toy case. The authors build a 16-application JavaScript benchmark suite, with 12 microbenchmarks and 4 end-to-end applications spanning storage, queues, databases, orchestration, and inter-function event chains. They deploy these workloads on AWS, Google Cloud, and Azure, isolate API-related billing entries from provider reports, and compare those bills against Skyler's symbolic predictions under fixed request profiles and `128 MB` functions. The resulting average MAPE is `0.5%` on AWS, `0.98%` on Google Cloud, and `4.5%` on Azure; the Azure gap mostly comes from auxiliary operations and CosmosDB details outside the current model.

The query results make the system useful, not just accurate. On the Booking application, Skyler finds that `reviewBooking` alone contributes more than `90%` of worst-case total cost, and that `detectSentiment` alone exceeds the `85%` threshold for dominant APIs inside that workflow. For input sensitivity, `reviewComment` has the highest growth coefficient, which suggests an immediate mitigation: constrain or pre-filter that field. The cross-provider query is also informative: for Booking, AWS is cheapest for small payloads up to about `1 KB`, with up to `32%` savings at `200 B`, while Google Cloud becomes cheaper for larger payloads by up to `6.4%`. Compared with calculator-style manual estimation and local emulators, Skyler also looks much more usable: manual error stays very high until a human effectively reconstructs whole-program taint flow by hand, and full analysis time still stays below `312` seconds for the largest benchmark, with most queries completing in under a second once the model exists.

## Novelty & Impact

Compared with _Mahgoub et al. (OSDI '22)_ and _Zhang et al. (NSDI '24)_, Skyler is complementary rather than competing: Orion and Jolteon optimize runtime execution and compute efficiency, while Skyler models API-side billing before deployment. Compared with _Ferreira et al. (PLDI '24)_ and _Gupta et al. (S&P '25)_, it repurposes dependency-graph analysis toward pricing semantics and denial-of-wallet-aware reasoning. That combination feels genuinely new: a static-analysis paper that produces developer-facing cloud cost queries rather than security or compiler diagnostics.

## Limitations

The model still has clear boundaries. If API-call counts inside a loop cannot be derived statically, Skyler asks the developer to provide them. It also does not model complex database-query pricing that depends on internal details such as indexing or entries scanned, and the Azure results show that auxiliary billed operations can still leak past the abstraction. More broadly, the prototype is JavaScript-only, depends on manually maintained API profiles and pricing plugins, and is evaluated on a curated benchmark suite rather than on large production deployments.

## Related Work

- _Mahgoub et al. (OSDI '22)_ — Orion optimizes runtime sizing, bundling, and prewarming; Skyler estimates API charges before deployment.
- _Zhang et al. (NSDI '24)_ — Jolteon improves workflow execution efficiency after profiling; Skyler reasons statically about billable API usage.
- _Ferreira et al. (PLDI '24)_ — MDG supplies the dependency-graph substrate that Skyler extends with triggers, resources, and pricing-aware sinks.
- _Gupta et al. (S&P '25)_ — Growlithe applies cross-function static analysis to compliance and permissions; Skyler redirects that machinery toward monetary cost estimation.

## My Notes

<!-- empty; left for the human reader -->
