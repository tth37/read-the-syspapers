---
title: "Analyzing and Enhancing ArckFS: An Anecdotal Example of Benefits of Artifact Evaluation"
oneline: "这篇 artifact-evaluation 论文为 Trio 的 ArckFS 补上 rename、crash-consistency 与并发缺陷修复，并基本保住原论文的性能结论。"
authors:
  - "Jonguk Jeon"
  - "Subeen Park"
  - "Sanidhya Kashyap"
  - "Sudarsun Kannan"
  - "Diyu Zhou"
  - "Jeehoon Kang"
affiliations:
  - "KAIST"
  - "EPFL"
  - "Rutgers University"
  - "Peking University"
  - "KAIST / FuriosaAI"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3768291"
code_url: "https://github.com/vmexit/trio-sosp23-ae"
tags:
  - filesystems
  - persistent-memory
  - crash-consistency
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文不是提出一种新的 NVM file system，而是对 SOSP 2023 的 Trio/ArckFS 做一次后续审计。作者补清了 multi-inode operation 所需的 verifier 规则，并修复了 1 个 rename 缺陷、1 个 crash-consistency 缺陷和 4 个并发缺陷。修补后的 ArckFS+ 仍基本保住原有性能叙事：在 48 线程 FxMark metadata 工作负载上达到 ArckFS 的 `97.23%`，在 Filebench 宏基准上达到 `97.1%` 到 `102.1%`。

## 问题背景

Trio 试图同时拿到 userspace NVM file system 的安全性与速度：把需校验的 core state 放在 NVM，把每个应用的 auxiliary state 放在 DRAM，并把 metadata integrity verification 尽量推迟到 inode ownership 转移时再做。代价是，正确性义务被推到了 LibFS、kernel controller 与 verifier 的边界上，而 artifact 把其中一部分规则留成了隐含条件：合法的 cross-directory rename 会被 verifier 拒绝；文件创建会因为缺少一个 memory fence 而部分持久化；并发竞态还会导致崩溃或 directory cycle。

## 核心洞察

论文最重要的判断是：Trio 的基本架构并没有被推翻，缺的是对边界情形的明确契约。只要把 inode sharing、rename ordering 和 persistence ordering 的规则写清楚，让 verifier 能分辨“合法演化”和“真正损坏”，系统就能恢复正确性，而额外代价也能留在少数低频转换点上，而不是回到普通读写热路径。

## 设计

Trio 把 file-system state 分成两部分：驻留在 NVM、用于 integrity verification 的 core state，以及每个 LibFS 在 DRAM 中按需构建的 auxiliary state。ArckFS 用 DRAM hash table、NVM multi-tailed log 和细粒度锁来实现这套架构；最关键的不变量是目录层次必须始终保持为一棵连通树。

ArckFS+ 的第一类修改是把 multi-inode contract 明文化。作者从目录迁移场景中提炼出三条原论文没有明确写出的规则：新建 inode 只有在父目录先被 release 后才能 commit 或 release；移动一个非空目录后，new parent 必须先于 old parent 被 commit 或 release；而在某些“迁入新建 sibling”的场景里，还必须在 rename 之前先 commit new parent，以打破依赖环。为让合法的 directory relocation 通过验证，kernel 的 shadow inode 新增 parent pointer，使 verifier 能区分“被 rename 到别处”与“被删除”；同时 verifier 还要求 LibFS 仍持有 old parent、new parent 不是被移动目录的后代，并且当前 LibFS 持有 global rename lock。

第二类修改是修补实现 bug，但尽量不重写快路径。针对 crash consistency，ArckFS+ 在刷写 commit marker 所在 cache line 之前插入一个 memory fence。针对并发问题，系统在 inode release 时获取所有相关锁，避免一个线程 unmap inode 时另一个线程仍在使用它；把目录 bucket 的临界区扩展到对应的 core-state 更新，防止 auxiliary state 先行；用 RCU 保护 bucket reader，避免遍历到已释放目录项；再通过 global rename lock 和 descendant check 阻止 directory cycle。

## 实验评估

评估运行在与 Trio 原论文不同的机器上，用来检验可复现性：一台双路、共 48 核的 Xeon 服务器，配有 Intel Optane persistent memory；对比对象包括 ArckFS 以及 Trio artifact 中的 ext4、PMFS、NOVA、OdinFS、WineFS、SplitFS 和 Strata。

主要结果是，这些修复并没有摧毁 Trio 原来的性能主张。单线程 metadata 测试中，ArckFS+ 在 open、create、delete 上分别达到 ArckFS 的 `83.3%`、`92.8%` 和 `92.2%`，损失来源与补丁本身一致，主要是 RCU read-side critical section 和新增的 memory fence。48 线程的 FxMark metadata 工作负载上，ArckFS+ 的几何平均吞吐仍达到 ArckFS 的 `97.23%`。在作者重建的 Filebench 框架里，他们恢复了原始 shared-directory 语义，而不是 Trio artifact 为了减小锁争用所采用的 private-directory 变体；在这个更贴近原语义的设置下，ArckFS+ 在 Webproxy 和 Varmail 上单线程达到 `101.1%` 和 `102.1%`，16 线程达到 `97.1%` 和 `98.8%`。这些结果基本支撑了论文的中心说法：修复之后，体系结构仍站得住。

但评估并没有同等覆盖所有补丁。rename 相关路径几乎没有被真正压到，因为主工作负载不执行 directory relocation；sharing-cost 实验也表明，共享写入的代价依旧存在，某些工作负载上 ArckFS+ 仍明显落后于 trust group 模式。

## 创新性与影响

这篇论文的创新点不在于提出新 file-system mechanism，而在于展示 artifact evaluation 在论文发表后到底能带来什么。相对于 _Zhou et al. (SOSP '23)_，本文把原先隐含的正确性前提写成明确的 verifier/LibFS 规则，修补了 artifact，并证明原始性能结论大体仍可成立。它因此既给 secure userspace NVM file system 的构建者留下了一份具体故障清单，也给 systems community 提供了 artifact evaluation 真能改进既有工作的实例。

## 局限性

这终究仍是一个围绕单一系统家族展开的 anecdotal case study。论文没有给出可泛化的 bug-finding method，也没有证明 ArckFS+ 已经没有潜在正确性缺陷；为了稳定复现失败，作者还在若干实验里主动插入了 `sleep()` 或额外 flush，这能证明 bug 存在，但不能说明真实部署中的出现频率。另一方面，rename-heavy workload 基本缺失，而 trust-group 结果也表明 sharing overhead 仍然重要，除非用户愿意放宽默认 verification 假设。

## 相关工作

- _Zhou et al. (SOSP '23)_ - Trio 和 ArckFS 是本文直接分析和修补的对象；本文的新意在于把原先隐含的 multi-inode 规则显式化，并修复发布 artifact。
- _Kadekodi et al. (SOSP '19)_ - SplitFS 同样把 persistent-memory file system 的一部分逻辑移到 userspace，但本文关注的是在这一设计点上如何保持 metadata integrity 与 correctness，而不是继续压缩 trusted path。
- _Chen et al. (FAST '21)_ - KucoFS 通过让 trusted component 参与每次 metadata operation 来保证安全，而 ArckFS+ 则坚持 deferred verification，并具体讨论了这种策略要想安全落地所需的边界规则。
- _Xu and Swanson (FAST '16)_ - NOVA 是 kernel persistent-memory file system 的代表性基线；本文把这类系统主要当作性能参照，而真正研究的是 Trio 这种 userspace-sharing 架构特有的正确性风险。

## 我的笔记

<!-- 留空；由人工补充 -->
