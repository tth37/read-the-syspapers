---
title: "Large Network UWB Localization: Algorithms and Implementation"
oneline: "Locate3D combines UWB range and AoA constraints with MST edge selection and rigidity decomposition to localize large peer-to-peer networks faster than range-only methods."
authors:
  - "Nakul Garg"
  - "Irtaza Shahid"
  - "Ramanujan K Sheshadri"
  - "Karthikeyan Sundaresan"
  - "Nirupam Roy"
affiliations:
  - "University of Maryland, College Park"
  - "Nokia Bell Labs"
  - "Georgia Institute of Technology"
conference: nsdi-2025
tags:
  - networking
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Locate3D is a peer-to-peer UWB localization system that treats angle-of-arrival as a first-class topology constraint instead of an afterthought. By jointly optimizing ranges and angles, selecting only low-uncertainty edges, and repairing non-rigid regions, it cuts localization latency by up to `75%` (`4.2x`) while reaching `0.86 m` median 3D error in a 32-node building deployment and `12.09 m` median error in a 100,000-node simulation with 15 anchors.

## Problem

The paper starts from a mismatch between modern UWB hardware and standard large-network localization algorithms. Range-only multidimensional scaling remains the dominant recipe because pairwise distance is easy to measure and does not require heavy infrastructure. But that recipe needs many edges, converges slowly, and only recovers positions. It throws away the azimuth and elevation information that newer commercial UWB arrays can already provide in the same exchange.

That omission matters at the scale the authors care about: swarms of drones, asset-tracking tags, mobile responders in buildings, and future vehicular or cellular deployments. In those settings, nodes move, connectivity is incomplete, occlusion is common, and update latency matters as much as eventual accuracy. A system that must remeasure a dense graph every round or depend on dense anchors becomes too slow or too brittle.

The obvious alternative is multimodal localization, such as combining UWB with VIO. The paper argues that this is a poor default for very large deployments because camera quality, lighting, and calibration are inconsistent across users and environments. Locate3D instead aims for a unimodal RF-first design: get 3D position and orientation from peer-to-peer UWB measurements alone, and use infrastructure only opportunistically when it exists.

## Key Insight

The core claim is that one carefully chosen UWB edge is much more informative than a classical range-only edge because it carries three constraints: range, azimuth, and elevation. If the optimizer can use angle information without getting trapped in bad local minima, then the system can localize a large graph with far fewer sampled edges than a range-only method.

That insight only becomes practical when paired with two additional observations. First, the useful edges are not arbitrary; the system should prefer edges with low predicted uncertainty and valid angle geometry, which turns edge selection into a minimum-spanning-tree problem over uncertainty-weighted links. Second, even a connected spanning tree may still be flexible, so rigidity has to be checked explicitly and repaired through subgraph decomposition and critical edges.

In short, Locate3D works because it uses angles to shrink the feasible geometry, then uses graph algorithms to spend measurement budget only where those constraints are most valuable.

## Design

Locate3D has four main algorithmic pieces. The first is a joint range-angle objective. Instead of optimizing only Euclidean distance error, it adds an angular loss term based on the negative cosine of the difference between measured and inferred angles. The paper motivates that transformation carefully: direct squared angle loss over arctangent expressions creates a highly non-convex surface with many local minima, while the cosine form is smoother and keeps the angular term bounded. The range loss is normalized before combining it with angle loss so the larger distance magnitudes do not drown out the angular gradient.

The second piece is optimal edge selection. For a graph with `n` nodes, the paper argues that range-only 3D localization needs roughly `3n-4` constraints, whereas a range-plus-azimuth-plus-elevation edge can constrain a node with far fewer samples. Locate3D therefore builds an MST with Kruskal's algorithm, using edge weights derived from estimated uncertainty area: shorter edges, lower variance, LOS links, and edges with usable angle measurements are cheaper. The first iteration is a cold start that measures neighbors broadly; later iterations reuse the previous topology estimate to choose only the next useful edges.

The third piece addresses the fact that connectivity is not enough. Commercial UWB arrays have limited angle field of view, so some AoA values are wrong near broadside or missing entirely. Locate3D filters suspicious angles using the sensor FoV and, when available, inertial rotation information. It then constructs a rigidity matrix over distance and angle constraints, studies its near-zero eigenvalues, and groups nodes with identical displacement vectors into rigid subgraphs. The system also records critical inter-subgraph edges so later rounds can reconnect these regions without remeasuring everything.

The fourth piece is reference-frame alignment and anchor integration. Raw AoA is reported in each node's local frame, so paired measurements must be rotated into a common global frame. Locate3D solves for roll, pitch, and yaw offsets by exploiting the complementary geometry of bidirectional azimuth and elevation observations; if IMU data already provides roll and pitch, only yaw must be solved. Anchors are optional rather than required. Static anchors bias the MST toward globally grounded nodes, while "virtual anchors" let infrastructure cameras temporarily register well-localized users and inject that information back into the graph.

## Evaluation

The implementation uses Raspberry Pi 3 nodes with NXP SR150 UWB boards and Intel Realsense T261 sensors, collecting UWB measurements at `20 Hz`. The authors report more than four hours of real-world data from 32 nodes and supplement it with city-scale simulations stitched from 20,000 measured UWB interactions. This is a sensible evaluation mix for a paper whose claim is both algorithmic and systems-oriented.

At room scale, Locate3D reaches median absolute errors of `18 cm` in 2D and `30 cm` in 3D. More importantly, it stays robust in regimes where the VIO-based baseline `Cappella` degrades: darker lighting does not hurt RF measurements, and static nodes still localize correctly because the system does not need an odometry tail. In line-of-sight versus NLOS tests, the 3D median error rises only from `31 cm` to `39 cm`, which suggests the filtering and edge selection logic are doing real work rather than merely averaging noise.

The building-scale result is the strongest real deployment evidence. Across 32 nodes on multiple floors and no infrastructure anchors, Locate3D reports `0.86 m` median 3D localization error and `4.5°` average orientation error. The paper also validates its AprilTag-based ground truth path against motion capture, which makes the building claim more credible than a pure simulation would.

The large-scale numbers show the scalability tradeoff clearly. In a `100,000`-node simulation with 15 anchors, median error is `12.09 m`; with one anchor it rises to `21 m`. In a wide-area New York City trace with `100,000` nodes over roughly `22 km x 3.2 km`, median error is `82.31 m` with one anchor and `34.19 m` with five. Those are not navigation-grade results, but they do support the central claim that the approach scales to huge peer graphs. The ablation study is also well aligned with the thesis: adding raw angles cuts latency but hurts accuracy, filtering restores accuracy, rigidity adds a small latency cost for a unique realization, and the full `Range+Angle+MST` stack delivers the best latency reduction while keeping accuracy near the range-only baseline.

## Novelty & Impact

The paper's novelty is not "UWB can measure angles"; that capability already exists in hardware and earlier systems. The contribution is a full localization stack that treats AoA as a graph constraint from end to end: objective function, edge sampling, rigidity repair, and reference-frame alignment. Compared with `Cappella`, which relies on VIO trajectories to stitch sparse UWB ranges, Locate3D stays RF-centric and therefore works in darkness and for static users. Compared with `ULoc`, which triangulates from infrastructure anchors, Locate3D propagates peer-to-peer constraints so the system still functions when anchors are sparse or out of range.

That makes the paper useful to several communities at once: systems researchers working on localization substrates, robotics and XR builders who need infrastructure-light coordination, and UWB platform designers deciding what sensor capabilities are worth exposing to upper layers. It is a new mechanism wrapped around a new systems framing: large-network localization should be treated as constrained graph construction, not just repeated range fitting.

## Limitations

The system is not yet a real-time distributed implementation. The prototype collects data online but processes it offline in Matlab, so the paper demonstrates algorithmic viability and measurement quality more strongly than deployment readiness. The discussion section acknowledges that a semi-distributed design with local leaders would be needed to improve worst-case latency and robustness in highly mobile settings.

Locate3D also depends heavily on AoA quality, and present-day COTS UWB hardware still has narrow useful FoV and bias near broadside. The filtering logic and optional inertial sensing mitigate this, but they do not remove the underlying hardware limitation. If angle quality is poor, the system falls back toward a noisier range-only regime.

Finally, the large-scale accuracy remains in the meter-to-tens-of-meters range and improves materially with anchors. Cold start still requires broad neighbor measurement, subgraphs can drift if they stay separated for long periods, and the virtual-anchor mechanism only registers a fraction of visible users over tens of seconds. So the paper is best read as a scalable peer-localization substrate, not as a fully solved turnkey navigation system.

## Related Work

- _Grosswindhager et al. (SenSys '18)_ - `SALMA` uses a single anchor plus UWB multipath assistance for small-scale localization, whereas Locate3D targets anchor-optional peer-to-peer 3D localization across much larger graphs.
- _Stocker et al. (IPSN '19)_ - `SnapLoc` is an ultra-fast UWB indoor localization system for large numbers of tags around infrastructure, while Locate3D focuses on uncertainty-aware edge sampling and rigidity in ad hoc networks.
- _Zhao et al. (IMWUT '21)_ - `ULoc` achieves centimeter-scale results with dense UWB anchors and AoA triangulation, while Locate3D trades that infrastructure dependence for broader coverage under sparse-anchor conditions.

## My Notes

<!-- empty; left for the human reader -->
