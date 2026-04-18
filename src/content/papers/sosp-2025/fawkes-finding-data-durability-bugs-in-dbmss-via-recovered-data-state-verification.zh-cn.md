---
title: "Fawkes: Finding Data Durability Bugs in DBMSs via Recovered Data State Verification"
oneline: "Fawkes 在文件系统与内核交互点触发 DBMS 崩溃，再用按 checkpoint 校正的数据图核对恢复结果，抓住传统测试工具漏掉的 durability bug。"
authors:
  - "Zhiyong Wu"
  - "Jie Liang"
  - "Jingzhou Fu"
  - "Wenqian Deng"
  - "Yu Jiang"
affiliations:
  - "KLISS, BNRist, School of Software, Tsinghua University, China"
  - "School of Software, Beihang University, China"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764841"
tags:
  - databases
  - storage
  - crash-consistency
  - fuzzing
category: storage-and-databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Fawkes 通过在 SQL 执行进入文件系统或内核交互路径时故意打崩 DBMS，再核对恢复结果是否等于最近一次 checkpoint 之后本应保留下来的已提交状态，来测试数据库 durability。它把检查标准从“服务是否恢复”改成“恢复出的状态是否正确”，因此能抓住传统 fault injection 工具常漏掉的 data loss 和 inconsistency 类 DDB。

## 问题背景

论文针对的是 data durability bugs，也就是那些让已提交 SQL 修改在 crash 之后丢失、恢复错误、污染日志，甚至让 DBMS 无法恢复的实现错误。作者研究了 PostgreSQL、MySQL、IoTDB 和 TDengine 中的 43 个真实 DDB，发现它们在恢复后主要表现为四类后果：data loss、data inconsistency、log corruption 和 system unavailability。多数根因落在 crash recovery 或 data flushing 逻辑里，而且 86% 的已知 DDB 都是在 SQL 执行进入文件系统或其他 kernel-level call 时被触发。

这正是现有方法抓不住的地方。人工 durability 测试太贵，也很难覆盖真正危险的窄时间窗。Jepsen、Mallory、CrashFuzz、CrashTuner 这类工具要么随机注入故障，要么在过于粗的边界上打断系统；它们的 oracle 大多只问“系统是否恢复”或“副本是否一致”。但对单机 DBMS 来说，最关键的问题是恢复后的状态是否仍然等于本该持久化下来的已提交状态。

## 核心洞察

Fawkes 的核心想法是把 DDB 检测拆成两个相互配合的问题：第一，故障要打在 durability logic 真正运行的地方；第二，恢复后的状态要和“理论上应该恢复出来的状态”逐项比对。前者来自作者的经验研究，说明文件系统与内核交互点才是大多数 DDB 的高价值触发窗口。后者则利用最近一次 checkpoint 和 recovery log 计算预期状态，把 oracle 从“恢复过程是否结束”提升为“恢复结果是否正确”。

## 设计

Fawkes 有三个核心部件。第一，context-aware fault injection 在编译期间分析 DBMS 调用图，找出那些调用链最终会到 glibc、文件系统库、JVM 或其他 OS-facing library 的代码区域，并把它们登记成 fault injection site，记录进 fault location bitmap。运行时，Fawkes 用 library hook 拦截 `open`、`read`、`write`、`malloc` 等调用，记录当前命中的 site，再注入七类故障之一，例如 power failure、memory exhaustion、process kill、kernel crash、disk I/O failure 和 software exception。

第二，functionality-guided fault triggering 决定何时触发这些故障。Fawkes 维护一张 fault-functionality table，把源文件和最可能到达其 durability-critical 路径的 SQL grammar feature 关联起来。若某个文件的相关 site 覆盖不足，workload generator 就会偏向生成能触发这些 SQL 功能的 schema 和查询。它追求的不是泛化意义上的最高 branch coverage，而是尽快把那些与 durability 强相关、但平时很少被走到的执行路径跑出来。

第三，checkpoint-based data graph verification 负责做 oracle。Fawkes 不去保存整个数据库快照，而是维护一个紧凑的数据图，记录 tables、columns、row counts、indexes 和 constraints 等 metadata。发生 crash 后，它先从 recovery log 中找出最近一次 checkpoint，把图回滚到该时刻，再用 recovery 应该重放的已提交 SQL 去修正预期状态；checkpoint 之后未提交的事务会被去掉。DBMS 重启后，Fawkes 一方面检查 recovery log 是否出现 system unavailability 或 log corruption，另一方面把恢复出的 metadata、已提交行和更新结果与修正后的数据图比对，从而发现 data loss 和 data inconsistency。

## 实验评估

实现规模大约是 10k 行 C++，外加 Rust、C、Java 和 grammar 支持代码。作者把 Fawkes 跑在八个 DBMS 上，两周内找到了 48 个此前未知的 DDB，其中 16 个在论文写作时已经被修复，8 个拿到了 CVE。主实验里，Fawkes 在 72 小时内覆盖了 320,848 个分支并找到了 29 个 DDB；而 Jepsen、CrashFuzz、Mallory、CrashTuner 分别只做到 174,604/2、216,985/4、218,135/6 和 188,810/1。rediscovery 实验也很强：面对四个 DBMS 的历史 buggy 版本，Fawkes 在两周内重新找回了 43 个已知 DDB 中的 39 个，其中第一周就找回了 34 个。

组件消融实验解释了这些收益从哪里来。把随机风格的 fault injection 换成 context-aware injection，bug 数从 2 提到 5；再加上 functionality-guided triggering，会升到 8；最后启用 data graph verification，bug 数直接跳到 29，虽然执行的测试用例总数会下降。这说明真正决定上限的不只是更会“打崩”，还包括能否正确判断“恢复结果错在哪里”。当然，基线工具本来就不是为单机 recovered-state checking 设计的，所以这里更像是问题设定的胜利，而不只是工程实现的对打。

## 创新性与影响

Fawkes 的创新不在于单独发明了新的 SQL generator 或新的 crash model，而在于把三件常被分开的事合成一套闭环：围绕 durability-critical 文件系统/内核交互点做 fault placement，围绕 SQL feature 覆盖做 workload steering，再用 checkpoint 校正后的预期状态做 recovery oracle。对 DBMS 开发者来说，这直接对应 WAL、flush ordering、checkpoint 和 replay logic 这些最容易出错、也最难手工验证的部分。更广义地说，这篇论文说明 crash testing 一旦有了“恢复后应保留什么”的语义模型，价值会远高于只检查服务能否重新启动。

## 局限性

它的适用范围比标题看起来更窄。论文明确聚焦 fault-induced crash bug，并不覆盖纯 optimizer logic 或其他非故障场景下的 durability failure。数据图也是刻意做轻的，因此最擅长验证 metadata、行是否存在以及被跟踪的更新是否正确，而不是为整个数据库上的任意语义不变量做完备检查。除此之外，这套系统的工程成本和运行成本都不低：它需要源码级分析、DBMS-specific grammar 适配和定制 library hook，而持续 fault injection 会明显降低测试吞吐。论文还指出，checkpoint 频率等 tuning parameter 也会影响 bug-finding 速度。

## 相关工作

- _Zheng et al. (OSDI '14)_ - Torturing Databases for Fun and Profit 通过模拟 power failure 检查 ACID 违规，而 Fawkes 进一步把故障放置做精，并用 checkpoint-based recovered-state oracle 验证现代 DBMS 的 durability logic。
- _Pillai et al. (OSDI '14)_ - ALICE 研究的是文件系统应用的 crash-consistency testing，而 Fawkes 把 oracle 提升到 DBMS recovery 语义和 SQL 可见状态层面。
- _Lu et al. (SOSP '19)_ - CrashTuner 用 meta-information analysis 寻找云系统中的 crash-recovery bug，Fawkes 则把这一思路专门化到 DBMS durability 路径，并直接验证恢复后的数据状态。
- _Meng et al. (CCS '23)_ - Mallory 面向分布式系统做 greybox fuzzing，而 Fawkes 针对的是单机 DBMS durability bug，这类 bug 的症状往往是恢复后状态被破坏，而不是副本分歧。

## 我的笔记

<!-- 留空；由人工补充 -->
