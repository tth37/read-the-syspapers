---
title: "CoFS: A Filesystem for Fast Container Startup"
oneline: "CoFS precomputes minimal perfect hashes for read-only container images and serves most lookup and cached-read paths from kernel space to cut cold-start latency."
authors:
  - "Li Wang"
  - "Jinxiu Du"
  - "Yang Yang"
  - "Qingbo Wu"
  - "Tao Liu"
  - "Haoze Wu"
affiliations:
  - "KylinSoft"
conference: fast-2026
category: os-and-io-paths
tags:
  - filesystems
  - kernel
  - isolation
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`CoFS` is a container-image filesystem built on extended `FUSE` that assumes the image tree is fixed and read-only once published. It uses build-time minimal perfect hash functions (`MPHF`) to turn pathname lookup into near-direct indexed access inside the kernel, and it uses sparse mirror files so cached data can also be served from kernel space. The result is a lazy-pulling design that keeps the flexibility of a custom image format but removes much of the userspace overhead that hurts cold-start latency.

## Problem

The paper targets the cold start of containers in orchestration and serverless-style environments. Startup is dominated by a long serial path: download the image, unpack it, configure the container, then start the process. The authors cite prior work showing that image pulling accounts for `76%` of container start time, even though only `6.4%` of downloaded data is actually read during startup. That mismatch is why lazy pulling has become attractive.

Existing lazy-pulling systems still leave two bottlenecks on the critical path. Filesystem-level systems such as `Nydus-fuse` and `eStargz` rely on a userspace daemon to resolve metadata and serve reads, so every pathname traversal step can trigger `LOOKUP` requests, context switches, and copies between kernel and userspace. `Nydus-erofs` avoids some `FUSE` overhead by moving more logic into the kernel, but its first-access path still runs through `fscache` and a userspace backend, which adds synchronous writes, longer call chains, and cache-management complexity. The problem is therefore not just "pull less data"; it is "make the first metadata and data accesses cheap enough that lazy pulling actually shortens startup."

## Key Insight

The central idea is that container image layers are built once and are read-only from the container's perspective, so CoFS can specialize aggressively for a static filesystem tree. Instead of doing generic directory lookup at runtime, it computes an `MPHF` at image-build time and stores file metadata in a dense array indexed by the hash of `(parent inode, filename)`. If the image never mutates, that hash table can be collision-free and space-efficient, which turns lookup into a predictable kernel-side operation with at most one metadata-file I/O in the common case.

The same immutability argument also simplifies data access. Rather than routing every cached read through a userspace `FUSE` daemon, CoFS mirrors downloaded file contents into sparse files on the host filesystem. On later accesses, the kernel can test whether the requested byte range is already present and directly read from the host filesystem. CoFS therefore splits the problem in two: precompute metadata indexing offline, and use fine-grained sparse-file caching to create a fast kernel-only path for previously fetched data.

## Design

CoFS extends the `eStargz` image format rather than inventing a completely new layering model. It removes inode-construction metadata from `stargz.index.json` and reorganizes it into a binary file called `cofs.inode.array`. That file stores the `MPHF` parameters `{m, n, T1, T2, g}`, followed by a dense metadata array and an extra-metadata tail for long filenames and extended attributes. Each metadata entry is fixed-size (`120` bytes), and long names spill into the tail. Hard links are handled by allocating multiple metadata-array entries that contain the same inode metadata so that the one-key-to-one-slot invariant still holds.

At build time, the key for the first `MPHF` is the concatenation of parent inode number and filename. At lookup time, `cofs-driver` reads the `MPHF` parameters into memory through an `ioctl`, computes the hash for the incoming `(parent inode, filename)` pair, jumps to the indexed metadata slot, and validates the parent inode and filename. If the target filename is short enough, the comparison stays inside the fixed-size entry; otherwise CoFS follows the recorded offset into the extra-metadata area. The paper's claim is that this avoids the repeated userspace lookup path that ordinary `FUSE` would take during pathname traversal.

Data access is split between two components. `cofs-snapshotter`, a `containerd` snapshotter derived from the `eStargz` snapshotter, prepares one FUSE-mounted directory and one mirror directory per image layer. Before container creation it asynchronously pulls only `cofs.inode.array`, not the full image, and passes its file descriptor to the kernel driver. During I/O, cache misses still go to the userspace daemon, which fetches the needed byte range from the remote registry and asynchronously writes it into a sparse mirror file named after the inode number.

`cofs-driver`, the kernel-side extension of `FUSE`, then uses those sparse mirror files to create a fast path. On a read, it checks whether a mirror exists and uses `vfs_lseek(..., SEEK_HOLE)` to determine whether the requested range is already materialized. If the file is fully downloaded, or if the requested interval is known to be present, the driver reads directly from the host filesystem with `vfs_read`; otherwise it forwards the request to the userspace snapshotter as normal `FUSE` would. CoFS also adds a second `MPHF` keyed by full path plus a `kprobe` on `do_filp_open`, so deep path resolution can be accelerated in parallel from the bottom up when the pathname depth exceeds three components.

## Evaluation

The evaluation uses Linux `6.9.1`, a dual-`Xeon E5-2640 v4` host with `128 GB` of RAM, a `4 TB HDD`, and a separate image repository connected over `1 GbE`, which intentionally models constrained registry bandwidth. The systems compared are `CoFS`, `CoFS-gzip`, `traditional`, `Nydus-fuse`, `Nydus-erofs`, and `eStargz`, with four service images: `mariadb`, `redis`, `tomcat`, and `elasticsearch`.

The first useful result is that CoFS's image-format overhead is small. For example, the `mariadb-10.7.3` image grows from `126.2 MB` in `eStargz` form to `128.4 MB` in `CoFS` form, and build time rises from `23 s` to `25.36 s`; the other three images show similarly small deltas. On cold startup, the paper reports that CoFS outperforms every compared system on all four containers, and that turning on background prefetch often makes startup worse because it competes for bandwidth with the bytes actually needed on the critical path.

The more detailed microbenchmarks support the mechanism. Relative to `fuse-loopback`, CoFS improves average lookup latency by `73%` to `86%`, and for the `elasticsearch` container the parallel full-path lookup mechanism adds another `28%` improvement over CoFS without that optimization. For cached reads, the authors create a `100 GB` file, force it to be downloaded once, clear page cache, and then run `fio`; CoFS matches the performance of the traditional filesystem path and `Nydus-erofs`, while outperforming `Nydus-fuse` and `eStargz` because the cached-read path stays in the kernel. Finally, the `MPHF` construction cost appears manageable: on random graphs with one million nodes, average construction time is `34.042 s` and the maximum is `63.24 s`, which the authors argue is acceptable compared with multi-minute image builds. Taken together, the evaluation supports the paper's main claim for read-only container startup, though the workload and hardware regime are fairly narrow.

## Novelty & Impact

CoFS differs from `Nydus` and `eStargz` not by inventing another lazy-pull image layout, but by specializing the metadata and cached-read path for static read-only trees. The novelty is the use of build-time `MPHF` construction to turn container-image lookup into a dense-array problem, plus the use of sparse mirror files to bypass the normal `FUSE` data path for cached regions.

That combination makes the paper relevant to container runtimes, snapshotter designers, and anyone trying to lower serverless or autoscaling cold-start latency without giving up filesystem-level sharing. It is primarily a new mechanism, but also a useful framing: if the image is immutable, the filesystem should spend offline work to remove online lookup overhead.

## Limitations

The design depends heavily on immutability. The whole `MPHF` layout assumes a fixed read-only filesystem tree, so CoFS is not a general filesystem design and does not directly help writable layers, mutable image contents, or workloads that need dynamic reorganization. Even on cache misses, it still falls back to a userspace daemon and remote fetch, so first-touch latency remains sensitive to network bandwidth and registry behavior.

The evaluation is also constrained. All experiments run on one hardware setup with `1 GbE` and HDD-backed storage, and the cold-start study covers only four containerized services. That is enough to show the mechanism works, but not enough to characterize performance under SSDs, faster networks, larger clusters, or more adversarial access patterns. There is also an implementation-complexity cost: CoFS adds custom image metadata, an extended kernel-side `FUSE` driver, sparse-file mirror management, and a `kprobe`-based path optimization that is Linux-specific and may complicate long-term maintenance.

## Related Work

- _Harter et al. (FAST '16)_ — `Slacker` showed that lazy image distribution can shrink container startup cost; CoFS attacks the same startup bottleneck by changing the filesystem lookup and cached-read path.
- _Li et al. (USENIX ATC '20)_ — `DADI` provides block-level lazy-pulled container images, whereas CoFS stays at filesystem granularity so image data can still be shared through the page cache and optimized per-file.
- _Bijlani and Ramachandran (USENIX ATC '19)_ — `ExtFUSE` accelerates `FUSE` with in-kernel eBPF snippets, while CoFS uses offline `MPHF` construction to eliminate most generic userspace metadata lookup for immutable images.
- _Cho et al. (FAST '24)_ — `RFUSE` improves the kernel-userspace communication substrate of `FUSE`, while CoFS specializes lookup and cached reads for container images and could potentially benefit from `RFUSE` underneath.

## My Notes

<!-- empty; left for the human reader -->
