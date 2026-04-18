---
title: "Skyler: Static Analysis for Predicting API-Driven Costs in Serverless Applications"
oneline: "Builds a serverless economic graph and SMT pricing model to predict, before deployment, which API paths and inputs will dominate a serverless bill."
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

The paper starts from a mismatch in today's tooling. Provider calculators can aggregate pricing tables, but only if a developer can already supply the right request counts and payload sizes for every cloud API. In realistic serverless applications, those quantities depend on branching, loops, asynchronous triggers, shared state, and service-specific billing rules. Dynamic optimization tools help after deployment, but they target compute efficiency and need real executions; they do not tell a developer, before launch, whether API usage itself will dominate the bill.

The running example makes that gap concrete. A `/createPost` request may stop after a user lookup, or it may continue through a database write, queue send, toxicity analysis, and a later update triggered by the moderation result. Because DynamoDB, SQS, and Comprehend all bill differently, these control-flow differences are economically huge: the full moderation path can be `1368x` more expensive than the minimal path, and raising input size from `1 KB` to `200 KB` can increase cost by more than `50x`. The paper's argument is that this is not an edge case. In API-heavy serverless workflows, API charges often dominate compute charges, so missing one economic sink can invalidate the whole architecture-level budget.

## Key Insight

The key move is to treat billable API sites as first-class program objects, which the paper calls economic sinks. Once those sinks are explicit, cost reasoning becomes a whole-program symbolic analysis problem: trace tainted inputs to the sinks across functions and cloud resources, keep request counts and object sizes symbolic, and encode pricing semantics as constraints instead of hard-coding one workload guess.

That proposition matters because it separates program understanding from workload exploration. Skyler does the expensive static reasoning once, then lets the developer ask different "what if" questions against the same symbolic model: which workflow dominates cost, which API call dominates a workflow, which input field drives spend, and which provider is cheaper for a given workload. The paper's real claim is therefore not just "we can estimate cost," but "we can make cost a queryable property of the program before deployment."

## Design

Skyler has three stages. First, it parses IaC templates and JavaScript code to build a serverless economic graph, or SEG. SEG extends MDG with event nodes, API-call nodes, loop nodes, resource nodes, and explicit control/data edges such as `CFG`, `DEP`, `TRIGGER`, and `USES`. That richer graph is necessary because cost does not follow only local control flow: an HTTP request may enqueue a message, that queue may trigger another function, and both functions may touch shared state whose size affects later charges. SEG therefore combines intra-function object-dependency analysis with inter-function stitching from IaC-declared triggers and shared resources. The paper also notes a practical cloud-specific wrinkle: AWS SDK calls often expose the target resource and payload directly, while Azure and Google Cloud more often require provider-specific logic to recover layered client/resource bindings.

Second, Skyler walks SEG and emits SMT-LIB constraints. It declares symbolic variables for request counts, payload sizes, loop counters, and costs; propagates counts through control flow and batching; propagates sizes through data flow; adds guard constraints from provider limits; and finally applies provider-specific pricing equations. The rule set is small but expressive: declaration rules introduce symbols, control-flow rules move invocation counts, data-flow rules move sizes, guard rules encode provider limits, and pricing rules turn usage into dollars. Pricing itself lives in pluggable provider modules, so the same graph and solver can target AWS, Google Cloud, and Azure. Third, Skyler runs four built-in query families over the symbolic model: dominant workflows, dominant APIs within a workflow, input-cost sensitivity, and cross-provider comparison. The prototype is about `5,800` lines of Python with `21` service plugins and Z3 as the solver.

## Evaluation

The evaluation goes well beyond the motivating example. The authors build a 16-application JavaScript benchmark suite, with 12 microbenchmarks and 4 end-to-end applications spanning storage, queues, databases, orchestration, and inter-function event chains. They deploy these workloads on AWS, Google Cloud, and Azure, isolate API-related billing entries from provider reports, and compare those bills against Skyler's symbolic predictions under fixed request profiles and `128 MB` functions. The resulting average MAPE is `0.5%` on AWS, `0.98%` on Google Cloud, and `4.5%` on Azure. The Azure gap is explained mostly by auxiliary operations and CosmosDB details that the current model does not yet encode.

The query results are what make the system feel useful rather than merely accurate. On the Booking application, Skyler finds that `reviewBooking` alone contributes more than `90%` of worst-case total cost, and that `detectSentiment` alone exceeds the `85%` threshold for dominant APIs inside that workflow. For input sensitivity, `reviewComment` has the highest growth coefficient, which immediately suggests a mitigation: constrain or pre-filter that field. The cross-provider query is also informative: for Booking, AWS is cheapest for small payloads up to about `1 KB`, with up to `32%` savings at `200 B`, while Google Cloud becomes cheaper for larger payloads by up to `6.4%`.

I also found the comparison against manual methods persuasive. The paper decomposes hand estimation into four steps and shows that error stays very high until the developer effectively reconstructs full taint flow across the application; Booking remains above `500%` error through the first three steps. Local emulators help with concrete execution but still require path enumeration and repeated runs to answer sensitivity questions. Against that backdrop, Skyler's end-to-end analysis time, under `312` seconds for the largest benchmark and usually under a second per query once the model exists, is a reasonable trade for pre-deployment visibility. The evidence therefore supports the central claim: Skyler is not just a symbolic exercise, but a practical debugging surface for API-driven serverless bills.

## Novelty & Impact

Compared with _Eismann et al. (ICPE '20)_ and _Mahgoub et al. (OSDI '22)_, Skyler shifts the unit of analysis from deployed executions and compute tuning to API-side billing semantics captured statically before launch. Compared with _Ferreira et al. (PLDI '24)_ and _Gupta et al. (S&P '25)_, it repurposes cross-function dependency-graph analysis from security and compliance toward cloud economics. That combination feels genuinely new: a static-analysis paper that produces developer-facing budgeting queries rather than vulnerabilities or compiler diagnostics.

The likely impact is on two groups. Practitioners building multi-service serverless backends get a way to inspect architectural cost hazards before traffic arrives, and researchers get a concrete formulation of "cost as a program property" that is richer than calculator inputs but lighter-weight than full dynamic profiling. The paper also has a security-adjacent implication: by surfacing cost-amplifying paths and inputs, it gives developers another angle on denial-of-wallet exposure.

## Limitations

The model still has clear boundaries. If API-call counts inside a loop cannot be derived statically, Skyler asks the developer to provide them. It also does not model complex database-query pricing that depends on internal details such as indexing or entries scanned, and the Azure results show that auxiliary billed operations can still leak past the abstraction. More broadly, the prototype is JavaScript-only, depends on manually maintained API profiles and pricing plugins, and is evaluated on a curated benchmark suite rather than on large production deployments.

## Related Work

- _Eismann et al. (ICPE '20)_ — Predicting the costs of serverless workflows estimates workflow costs from deployment-oriented measurements; Skyler instead derives API-cost equations statically before deployment.
- _Mahgoub et al. (OSDI '22)_ — Orion optimizes runtime sizing, bundling, and prewarming; Skyler estimates API charges before deployment.
- _Ferreira et al. (PLDI '24)_ — MDG supplies the dependency-graph substrate that Skyler extends with triggers, resources, and pricing-aware sinks.
- _Gupta et al. (S&P '25)_ — Growlithe applies cross-function static analysis to compliance and permissions; Skyler redirects similar whole-application reasoning toward monetary cost estimation.

## My Notes

<!-- empty; left for the human reader -->
