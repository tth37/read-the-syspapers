---
title: "Hourglass: Enabling Efficient Split Federated Learning with Data Parallelism"
oneline: "Hourglass keeps one shared split-FL server partition per GPU and schedules dissimilar client features together, removing model swapping while speeding convergence."
authors:
  - "Qiang He"
  - "Kaibin Wang"
  - "Zeqian Dong"
  - "Liang Yuan"
  - "Feifei Chen"
  - "Hai Jin"
  - "Yun Yang"
affiliations:
  - "Huazhong University of Science and Technology, Wuhan, China"
  - "Swinburne University of Technology, Melbourne, Australia"
  - "University of Adelaide, Adelaide, Australia"
  - "Deakin University, Melbourne, Australia"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717467"
tags:
  - ml-systems
  - gpu
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Hourglass argues that split federated learning should not keep one server-side model partition per client. It instead keeps one shared server-side partition per GPU and schedules dissimilar client features through those shared partitions. The paper reports up to 35.2x faster convergence than SplitFed and up to 9.28% higher accuracy.

## Problem

Split federated learning exists because edge clients cannot realistically train large models end to end. SplitFed-style systems fix that by moving upper layers to a fed server, but they also create a new scaling problem: the server keeps a distinct server-side partition for every client and aggregates all of them.

The paper identifies two direct costs. If the server has fewer GPUs than clients, it must keep swapping partitions in and out of GPU memory; over 300 clients, that switching accounts for 13.1%-79.9% of total training time, with a 43.15% average. Storage also explodes. The authors estimate that training DINOv2 for 10K clients would require more than 40 TB just to store server-side partitions. Compression can reduce size, but it hurts accuracy and does not fix the one-model-per-client design.

## Key Insight

Hourglass's core claim is that server-side state should scale with GPU count, not client count. With one GPU, the server keeps one shared partition and runs all client features through it. With `M` GPUs, it keeps `M` shared partitions, trains them in parallel, and aggregates only those `M` partitions. That removes swap-heavy per-client training and lets many clients update shared server state directly rather than reconciling isolated server models later.

The second insight is about heterogeneity. The paper finds that feeding similar features to the same GPU tends to push a shared partition in the same direction repeatedly, which can hurt generalization. Feeding dissimilar features together makes each shared partition absorb broader variation, so Dissimilar Feature First (DFF) beats both FCFS and similarity-first placement.

## Design

Hourglass keeps the normal split-FL round structure: clients run forward passes on client-side layers and send intermediate features, the server schedules those features onto GPUs, trainers run forward and backward passes through server-side partitions, gradients return to clients, and an aggregator applies FedAvg across server-side partitions for the next round.

In the single-GPU case, Hourglass keeps one shared server-side partition in memory for all clients. That alone removes model switching, but the bigger change is knowledge fusion: client features update the same server partition immediately instead of first diverging into per-client models. The paper says this design reaches the same accuracy as per-client partitions with only 4.31% of the training time for VGG-16 and 11.93% for ResNet-50, while also reducing storage overhead by up to 96.67% and computation overhead by up to 88.07%.

In the multi-GPU case, Hourglass keeps one shared partition per GPU. Waiting for all clients and running `k`-means would block on stragglers and add 8.1%-24.1% clustering overhead, so Hourglass uses Euclidean-distance LSH instead. Arriving features are bucketed online and dispatched to available GPUs, with stronger GPUs preferred when hardware is heterogeneous. The paper also gives convergence bounds under strongly convex, general convex, and non-convex assumptions.

## Evaluation

The evaluation uses five models across four datasets: VGG-16, ResNet-50, and ViT on CIFAR-10 and CINIC-10; CharCNN and LSTM on AG News; and VGG-16 on Speech Commands. The fed server has 10 RTX 3080 GPUs and 5 RTX 2060 GPUs; clients are CPU-only machines.

The headline result is convergence speed. In a 10-GPU configuration, Hourglass-DFF beats FL by 8.9x-78.8x and SplitFed by 2.7x-35.2x. Accuracy also improves: on single-GPU VGG-16/CIFAR-10, Hourglass-DFF reaches 86.82% while SplitFed reaches 80.6%, and the largest reported gain is 9.28% on ResNet-50/CINIC-10.

The ablations support the main mechanism. DFF consistently beats FCFS and similarity-first placement. More GPUs help only up to a point: with 300 clients, the best result is at 10 GPUs, after which knowledge gets spread too thin across partitions. On a mixed 3080/2060 server, LSH plus capacity-aware placement reduces training time by 22.1%-56.8% versus random placement.

## Novelty & Impact

The paper's novelty is not a new optimizer; it is a server architecture for split FL. Relative to SplitFed, it replaces one-model-per-client with one-model-per-GPU. Relative to clustered FL systems like IFCA and Auxo, it moves heterogeneity handling from client grouping to online intermediate-feature placement. The result is a systems design that couples shared server partitions, DFF scheduling, and LSH-based asynchronous dispatch.

## Limitations

Hourglass is still tailored to homogeneous split-FL jobs. All clients are assumed to share the same model architecture and cut layer, and the paper leaves model heterogeneity for future work. Its strongest gains also depend on the operating point: too many GPUs or too many clients weaken knowledge fusion.

There are also gaps between theory and deployment. The convergence analysis uses convexity-based assumptions that do not literally match the evaluated deep nets, and the evaluation is compute-centric rather than a real wide-area deployment with unstable networks.

## Related Work

- _Thapa et al. (AAAI '22)_ - SplitFed is the direct baseline: it keeps one server-side partition per client and aggregates them, while Hourglass keeps one shared partition per GPU and removes swap-heavy per-client training.
- _Ghosh et al. (NeurIPS '20)_ - IFCA clusters clients in federated learning, but it operates at the client/model level rather than scheduling split-learning intermediate features onto a GPU-constrained server.
- _Liu et al. (SoCC '23)_ - Auxo also uses client clustering to exploit heterogeneity, whereas Hourglass replaces global clustering with online LSH over arriving intermediate features so it can act without waiting for all clients.
- _Liao et al. (ICDE '24)_ - MergeSFL improves split FL with feature merging and batch-size regulation, while Hourglass focuses on server-side compute/storage bottlenecks and GPU placement.

## My Notes

<!-- empty; left for the human reader -->
