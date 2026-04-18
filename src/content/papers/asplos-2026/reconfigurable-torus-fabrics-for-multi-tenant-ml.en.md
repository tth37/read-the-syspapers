---
title: "Reconfigurable Torus Fabrics for Multi-tenant ML"
oneline: "Morphlux adds a programmable photonic fabric inside torus ML servers so sub-rack slices recover bandwidth, fragmented resources become usable, and failures stay local."
authors:
  - "Abhishek Vijaya Kumar"
  - "Eric Ding"
  - "Arjun Devraj"
  - "Darius Bunandar"
  - "Rachee Singh"
affiliations:
  - "Cornell University, Ithaca, NY, USA"
  - "Lightmatter, Mountain View, CA, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790238"
code_url: "https://github.com/cornell-sysphotonics/Morphlux"
tags:
  - networking
  - hardware
  - datacenter
  - ml-systems
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Morphlux targets a mismatch in modern ML clusters: torus fabrics are excellent for one giant training job, but waste bandwidth and flexibility when many small fine-tuning or inference tenants share the same rack. The paper inserts a programmable photonic interposer under each multi-accelerator server, then uses a software controller to redirect link bandwidth, stitch together fragmented servers, and patch around failed accelerators. The payoff is up to `66%` more bandwidth for small slices, up to `70%` lower fragmentation, `1.72x` faster fine-tuning in the prototype, and in-rack failure recovery in about `1.2` seconds.

## Problem

The starting point is Google-style torus ML fabrics, where a rack forms a `4 x 4 x 4` accelerator torus and collective communication runs through multi-dimensional ring algorithms. That design is attractive for very large training jobs because it avoids packet-switch contention. The trouble is that the workload mix has changed. The paper argues that many users now want sub-rack allocations for inference or small-scale fine-tuning, not entire racks for months-long pretraining.

Those smaller slices interact badly with torus topology. An accelerator's egress bandwidth is statically split across the `X`, `Y`, and `Z` dimensions, but a sub-rack slice often cannot safely use all three because some dimension links sit on slice boundaries and would contend with neighboring tenants. The paper reports that `29%` of TPU allocations in Google's public distribution are sub-rack, and that some racks in their simulator leave up to `50%` of `Y`-dimension links unused. In the worst case, a small slice can lose up to two-thirds of its effective egress bandwidth.

The topology constraint also creates a placement problem. Packet-switched clusters can allocate non-contiguous servers to one tenant and let the network carry the rest, but a torus fabric needs physically contiguous resources if it wants to preserve direct-connect collectives without routing through someone else's slice. After enough alloc/dealloc churn, free accelerators exist but cannot be assembled into a legal torus request. Finally, failures are too expensive: if one accelerator in a torus slice dies, existing TPU-style policy migrates the whole job to a different rack or pod, which is operationally heavy and broadens the blast radius of a single chip fault.

## Key Insight

The paper's core claim is that torus fabrics become much more multi-tenant-friendly if bandwidth assignment stops being fixed at package design time and becomes programmable at server scale. Instead of hard-wiring each accelerator's output into one `X`, one `Y`, and one `Z` neighbor path, Morphlux exposes that bandwidth to a photonic switching fabric under the accelerators and maps it onto whichever in-slice directions are actually useful for the tenant currently occupying the rack.

That one change unlocks all three benefits. First, stranded bandwidth on unusable torus dimensions can be concentrated onto links that stay inside the tenant slice. Second, physically non-contiguous free servers can be presented as a logically contiguous torus by configuring optical circuits through the rack. Third, when one accelerator fails, the controller can wire a healthy spare in the same rack into the failed node's neighborhood instead of evacuating the whole job. The paper is strongest when it frames these as one resource-management problem, not three separate hacks: the programmable photonic fabric is the substrate, and allocation, repair, and bandwidth steering are all policies over the same substrate.

## Design

Morphlux augments each four-accelerator server with an optical interposer built from waveguides, transceiver blocks, and Mach-Zehnder interferometer switches. Accelerators remain electrical devices, but once traffic reaches the interposer's Tx/Rx blocks it becomes steerable light. Fibers leaving the interposer connect the server to its six torus directions, so the overall rack still looks like a direct-connect torus rather than a packet-switched Clos.

The important systems abstraction is the optical circuit: an end-to-end light path from one accelerator port to another, either within one server or across servers through fibers. Circuits reserve optical resources along the whole route, so communication remains contention-free once a path is installed. Reconfiguration is not on the critical path of every collective. The paper explicitly limits it to two cases that can tolerate microsecond-scale switch programming delays: slice allocation time and failure handling.

On top of the hardware substrate sits `MorphMgr`, with three pieces. The default allocator first tries to place a requested `x x y x z` torus on contiguous free servers. If that fails, the fragmented allocator solves an ILP that maps logical slice slots onto non-contiguous servers while minimizing the maximum circuit overlap on any inter-server boundary. That objective matters because overlap determines how many parallel fibers must be provisioned between servers. The fault manager reserves spare capacity per rack, models failures as shared-risk groups, and derives how many spares are needed to hit a target availability. For a 64-XPU rack, the paper finds that `4` spare XPUs, or two spare four-XPU servers at server granularity, cover over `95%` of failures under their sampled fault probabilities. The hardware control plane then assigns SerDes ports to communication groups and uses prior route-finding work to realize the needed circuits on the photonic mesh.

## Evaluation

The evaluation has two layers. The first is a small hardware prototype built from four Dell servers with RTX 6000 Ada GPUs connected through an off-the-shelf iPronics silicon-photonic mesh. This is not full co-packaging: the datapath is `GPU -> PCIe -> NIC -> photonics`, and an undocumented polarization mismatch limits the mesh to `10 Gbps`. Even so, it validates the mechanism. For `2 x 1 x 1` and `1 x 2 x 1` slices, Morphlux doubles `iperf` bandwidth and improves NCCL AllReduce bandwidth by about `1.8x`. On Llama-3.2-1B fine-tuning over WikiText-103, epoch time drops from `40.25 s` to `23.37 s` at batch size `8`, a `1.72x` speedup. Under a simulated GPU failure, the system reprograms the mesh and restarts the job with about `1.2` seconds of recovery time.

The second layer is a TPU-cluster simulator driven by the public TPUv4 slice-size distribution. Here the paper shows why the mechanism matters beyond a four-node demo. Morphlux raises bandwidth utilization to `100%` where the baseline may leave up to `50%` of ports unused. It improves simulated transformer fine-tuning throughput by up to `2x` on small slices, successfully serves fragmented `32`-TPU requests that default TPU and SiPAC-style allocators reject about `75%` of the time, and reduces average overprovisioning for failures by an order of magnitude relative to job migration. The support for the main claim is reasonably strong: the hardware prototype demonstrates the reconfiguration path is real, while the simulator explores the scale regimes where fragmentation and slice churn actually dominate. The main caveat is that the most dramatic scale results still come from simulation, not a production deployment.

## Novelty & Impact

Relative to _Vijaya Kumar et al. (HotNets '24)_, this paper moves from an argument for server-scale photonic connectivity to a concrete multi-tenant torus design with allocation, failure handling, and prototype evidence. Relative to _Wu et al. (OFC '23)_, which uses silicon photonics to accelerate collective communication, Morphlux is less about one contiguous training job's bandwidth and more about recovering flexibility for arbitrary small slices. Relative to _Zu et al. (NSDI '24)_, which documents whole-job migration in TPUv4 resilience, Morphlux's distinctive move is to shrink repair scope from rack migration to in-rack rewiring.

That makes the paper useful to several communities at once. ML-cluster architects can cite it as a concrete answer to the "torus versus flexibility" tradeoff. Photonic-systems researchers can cite it as an end-to-end systems case for co-packaged switching, not just faster links. Resource-management researchers can cite the fragmented allocator and fault model as evidence that topology-aware placement and repair policies should be designed together with the interconnect substrate.

## Limitations

The authors are candid that the prototype stops well short of a deployable product. Because accelerators are not bonded directly onto the interposer, the testbed runs at `10 Gbps`, far below the hundreds of Gbps the packaging vision targets. The paper argues the control-plane benefits are orthogonal to raw bandwidth, which is plausible, but it still leaves open how much additional engineering pain appears at datacenter-rate optics and real thermal budgets.

The design also assumes reconfiguration is infrequent. That is reasonable for allocation and fault repair, but it means Morphlux is not a general adaptive fabric that re-optimizes every collective or every phase boundary. The fragmented allocator depends on enough fiber capacity between servers, and the paper's ILP minimizes overlap under that assumption rather than proving a closed-form provisioning rule. Finally, most large-scale results rely on simulator workloads derived from public TPU distributions plus FlexNet-based communication modeling. That is a sensible methodology, but it is not the same as showing a production rack running many real tenants over time.

## Related Work

- _Vijaya Kumar et al. (HotNets '24)_ — motivates server-scale photonic connectivity, while Morphlux turns that architectural argument into a multi-tenant torus allocator and repair system.
- _Wu et al. (OFC '23)_ — SiPAC accelerates distributed training collectives with photonic connectivity, whereas Morphlux focuses on bandwidth redirection, fragmented placement, and failure containment for shared slices.
- _Wang et al. (NSDI '23)_ — TopoOpt co-optimizes topology and parallelization for distributed training jobs; Morphlux instead changes the rack substrate so small torus slices become more allocatable and better utilized.
- _Zu et al. (NSDI '24)_ — Google's TPUv4 resiliency work migrates jobs around failed hardware, while Morphlux tries to keep recovery inside the same rack by rewiring around the failed accelerator.

## My Notes

<!-- empty; left for the human reader -->
