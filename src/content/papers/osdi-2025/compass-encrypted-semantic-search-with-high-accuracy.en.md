---
title: "Compass: Encrypted Semantic Search with High Accuracy"
oneline: "Compass makes encrypted semantic search practical with directional graph filtering, speculative prefetch, and traversal-aware ORAM while preserving plaintext-level retrieval quality."
authors:
  - "Jinhao Zhu"
  - "Liana Patel"
  - "Matei Zaharia"
  - "Raluca Ada Popa"
affiliations:
  - "UC Berkeley"
  - "Stanford University"
conference: osdi-2025
code_url: "https://github.com/Clive2312/compass"
tags:
  - security
  - databases
  - ml-systems
category: databases-and-vector-search
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Compass asks whether encrypted search can keep the accuracy of modern semantic retrieval instead of falling back to keyword search or weaker trust models. It runs an HNSW-style graph index over encrypted embeddings by combining quantized directional hints, speculative graph prefetch, and a Ring-ORAM layout tailored to multi-hop traversal. Across four datasets, it matches the plaintext embedding baseline's search quality and keeps user-perceived latency at 0.57-1.28 seconds on the paper's slow cross-region network.

## Problem

The paper targets a mismatch between what encrypted search systems usually protect and what modern search systems actually do. Prior encrypted-search work often focuses on lexical retrieval with inverted indexes, which protects data but loses the semantic accuracy now expected from embedding-based search. Other systems keep more expressive search but weaken the security story by leaking access patterns, relying on TEEs, or assuming multiple non-colluding servers. Compass wants a stronger point in the design space: semantic search over a user's own encrypted corpus, with privacy for the data, the query, and the result set even if the server is fully compromised.

The obvious implementation route does not work. State-of-the-art semantic retrieval often uses graph ANN indexes such as HNSW because they give excellent accuracy. But HNSW is built for local memory: each step greedily visits a node, inspects all of its neighbors, and continues. If every visited node becomes a remote ORAM access, search turns into a long chain of costly client-server round trips. The paper notes that a good HNSW query may touch tens to hundreds of candidate nodes, each with tens to hundreds of neighbors, so a naive ORAM port fetches data for thousands of nodes and still needs tens to hundreds of network trips. Fully homomorphic or garbled approaches can hide this, but at much higher cost. The real problem is therefore not just "encrypt the index"; it is "restructure graph search so ORAM only pays for the accesses that matter."

## Key Insight

The key claim is that HNSW-style search can survive encryption if the client uses a cheap local approximation to decide where the graph walk should go next, then spends exact ORAM accesses only on the most promising nodes. In other words, Compass does not treat ORAM as a black box under an unchanged graph algorithm. It co-designs the traversal and the storage protocol.

That proposition works because the client already performs query-side computation locally. If the client stores a compressed geometric sketch of the graph, it can rank neighbors approximately without revealing the query to the server. Once it knows which few neighbors are most likely to matter, it can fetch only those nodes' exact coordinates and adjacency lists. The same principle extends to latency: if future graph steps are predictable enough, the system can speculate on them and batch their ORAM work; if ORAM costs that are not on the critical path can be delayed, user-perceived latency drops without changing search results.

## Design

Compass keeps the HNSW graph and encrypted embeddings on the server and runs the search logic on the client. Each ORAM block stores one graph node's full embedding and neighbor list. The client keeps the usual ORAM state, HNSW metadata, a cached tree top for ORAM, and locally cached upper HNSW layers. It also stores a new structure called Quantized Hints: a product-quantized embedding for every node, mapping node IDs to cheap approximate coordinates.

The first mechanism, Directional Neighbor Filtering, uses those hints to avoid fetching every neighbor of the current node. For each node under consideration, the client looks up its neighbors' quantized embeddings, ranks them by approximate distance to the query, and fetches only the top `efn` neighbors' exact data. The quantized hints are never used as the final search result; they only decide which exact accesses are worth paying for. That matters because directly running ANN on quantized embeddings would hurt accuracy, but using quantization only as a filter reduces bandwidth by roughly `M / efn` while keeping the true full-precision comparison on the critical path.

The second mechanism, Speculative Neighbor Prefetch, attacks round trips rather than bandwidth. Instead of processing only the single best candidate in the search frontier, Compass extracts the top `efspec` candidates from the candidate list and fetches their next-hop neighborhoods together in one batch. The client then evaluates the returned nodes and updates the frontier. This is speculative work, but the candidate list is already ordered by distance to the query, so the guesses are informed rather than blind. In the paper's formulation, this reduces the number of search batches by about a factor of `efspec`.

The third mechanism is Graph-Traversal Tailored ORAM. Compass stores a node's coordinates and neighbor list in the same block so one fetch avoids a second trip just to read adjacency. It batches ORAM accesses, caches bucket metadata on the client, and delays eviction until after the query via multi-hop lazy eviction. Because Ring ORAM's online reads dominate what the user feels and eviction is offline work, this moves much of the cost off the critical path. To keep these changes from leaking graph-structure information, Compass pads nodes to equal degree, fixes the number of search steps per layer, and pads batched accesses. For malicious-server integrity, it layers Merkle trees over the ORAM tree, including a secondary tree inside each bucket, so tampering or replayed data is detected by the client.

## Evaluation

The implementation is about 5k lines of C++ using Faiss for HNSW and product quantization, plus AES-256-CBC and SHA-256 through OpenSSL. The evaluation uses a Google Cloud client and server, with a fast 3 Gbps / 1 ms network and a slow 400 Mbps / 80 ms network. The four datasets are LAION, SIFT1M, TripClick, and MS MARCO, and parameters are tuned to reach at least Recall@10 = 0.9.

The main result is accuracy without giving up practicality. Compass matches the quality of brute-force embedding search and therefore tracks the plaintext HNSW baseline across all four datasets, while clearly outperforming the secure lexical and homomorphic baselines. In latency, Compass is still about 6-10x slower than plaintext HNSW, so encryption is not free, but it is up to 920x faster than a naive HNSW-on-ORAM construction and orders of magnitude faster than the two secure baselines the paper evaluates. On the slow network, perceived latency ranges from 0.57 seconds on LAION to 1.28 seconds on MS MARCO. The paper also reports that lazy eviction cuts perceived latency by 1.5-5.6x relative to full latency, and the ablation study shows batching ORAM requests alone contributes a 12-20x latency reduction.

The memory and scalability story is more mixed, and the paper is candid about it. Server-side memory is 3.2-6.8x that of storing the embeddings and graph in plaintext because ORAM needs dummy capacity. Client memory is modest for user-scale datasets, 5.49 MB on LAION and 35.84 MB on SIFT1M, but rises to 498.65 MB on MS MARCO. That is why the authors frame Compass as a private-data and encrypted-RAG retrieval system rather than a web-scale search engine. The upside is that the server is lightweight operationally: on LAION, the storage-heavy server reaches 436 queries per second with only 26% CPU utilization under 25 concurrent clients.

## Novelty & Impact

Relative to _Mishra et al. (S&P '18)_ on Oblix, Compass is not another oblivious lexical index; it moves the problem to semantic retrieval and shows how to preserve the search behavior of a graph ANN structure under strong privacy constraints. Relative to _Henzinger et al. (SOSP '23)_ on Tiptoe, it tackles private encrypted corpora rather than the easier public-database setting where homomorphic preprocessing can lean on plaintext data. Relative to _Chen et al. (USENIX Security '20)_ on SANNS, it avoids a much heavier mix of cryptographic tools by centering the system around one carefully adapted ORAM-based traversal.

That makes the paper's contribution a systems co-design rather than a new cryptographic primitive or a new ANN graph. The likely impact is on private personal-cloud search and encrypted RAG: any future system that wants semantic retrieval quality without trusting server hardware will need to grapple with the same "graph search over hidden access patterns" problem, and Compass is a strong first answer.

## Limitations

Compass is careful about what it does not hide. The server still learns the operation type, public search parameters, rough corpus size, and timing side channels. The system also assumes the client can safely persist its local state; if the client's disk fails and recovery depends only on server-provided checkpoints, a malicious server could return stale state without detection.

The second limitation is scale. The paper explicitly says Compass is not yet a global web-search design, and the 498.65 MB client footprint on MS MARCO explains why. Even search latency has a split personality: user-perceived latency is around a second because eviction is delayed, but full latency on larger datasets remains several seconds. Updates are also not cheap. On MS MARCO, the paper reports 19.2 seconds to insert a document over the slow network when using a candidate-list size of 160. That is acceptable for personal or asynchronous indexing, not for high-rate shared updates.

## Related Work

- _Mishra et al. (S&P '18)_ — Oblix provides oblivious search indexes for lexical retrieval, while Compass targets embedding-based semantic search and therefore has to hide graph-style traversal rather than keyword-list accesses.
- _Dauterman et al. (OSDI '20)_ — DORY achieves encrypted search with distributed trust across multiple domains; Compass stays in the single-server setting and refuses the assumption that one trust domain remains honest.
- _Chen et al. (USENIX Security '20)_ — SANNS supports secure approximate nearest-neighbor search with heavier cryptographic machinery, whereas Compass makes a graph ANN practical by co-designing it with Ring ORAM.
- _Henzinger et al. (SOSP '23)_ — Tiptoe makes private queries over public corpora efficient via clustering, while Compass handles private encrypted data and accepts a more complex traversal to preserve high semantic accuracy.

## My Notes

<!-- empty; left for the human reader -->
