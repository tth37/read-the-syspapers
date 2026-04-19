---
title: "Revealing the Unstable Foundations of eBPF-Based Kernel Extensions"
oneline: "DepSurf 把 eBPF 程序依赖的内核函数、结构体与 tracepoint 显式建模，证明源码演化、配置差异和编译器优化会系统性破坏可移植性。"
authors:
  - "Shawn (Wanxiang) Zhong"
  - "Jing Liu"
  - "Andrea Arpaci-Dusseau"
  - "Remzi Arpaci-Dusseau"
affiliations:
  - "University of Wisconsin-Madison"
  - "Microsoft Research"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717497"
code_url: "https://github.com/ShawnZhong/DepSurf"
project_url: "https://github.com/ShawnZhong/DepSurf-dataset"
tags:
  - ebpf
  - kernel
  - observability
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DepSurf 把 eBPF 可移植性的问题从源码是否兼容，改写成程序依赖集和编译后 kernel image 依赖面是否匹配。它直接分析发布出来的 kernel image 与 eBPF object file，不只找出编译或 attach 时会报错的情况，也能提前指出更危险的 silent 错误。

## 问题背景

eBPF 常被理解成一种不用改内核源码、却能安全扩展 Linux 的办法，CO-RE 又进一步强化了「一次编译，多处运行」的期待。但现实里的 eBPF 工具并不只依赖稳定接口。它们会 attach 普通 kernel functions、tracepoints、system calls，读取内核 structs 和 fields，甚至直接碰不同架构上的 `pt_regs`。问题在于，这些依赖同时会被三股力量改写：上游源码演化会改签名和 hook，config 会让同名内核暴露出不同的 constructs，编译器还会做 inline、duplication、constprop、isra 等优化，让 source code 看着没变，binary interface 却已经变了。

CO-RE 能做的是在字段还存在时重定位 offset，它救不了那些在目标内核上本来就编不过、hook 已经消失，或者 kprobe 读取参数时语义悄悄变化的情况。论文开头拿 `biotop` 举例，这个问题前后拖了将近两年才真正收尾。作者想说明的正是：这不是偶发事故，而是 eBPF 可移植性的常见形态。

## 核心洞察

这篇 paper 最重要的判断是，eBPF 的 portability 不能只盯着 source tree 看，必须在 compiled kernel image 上研究。作者把一个内核真正暴露给 eBPF 的 functions、structs、tracepoints、syscalls 统称为 dependency surface，再把某个 program 实际依赖的那部分称为 dependency set。这样之后，兼容性问题就不再是模糊的「可能坏了」，而是可以精确分类的 mismatch。

这也解释了为什么 source diff 不够。某个 C 声明明明还在代码树里，binary 里却可能因为 full inline 直接消失，因为 selective inline 只剩部分 call sites 可见，或者因为 compiler transformation 改了调用约定。DepSurf 的贡献，就是把这些 image-level effects 也纳入分析，再翻译成具体的 failure modes。

## 设计

DepSurf 分两阶段。第一阶段是 dependency surface analysis。输入是 `vmlinux` 和 debug info；工具会从 DWARF、symbol table、data sections 中提取函数、结构体、tracepoints、syscalls 的声明，同时记录函数是否 full inline、selective inline、transformation、duplication、name collision。比如 tracepoints 不是靠启动内核去枚举，而是静态解析 ftrace event 数组；syscalls 则通过 `sys_call_table` 反查名字。随后它把多份 kernel image 互相比对，得到一份 mismatch dataset。

第二阶段是 dependency set analysis。对 eBPF object file，DepSurf 从 section names 恢复程序 attach 的 hooks，再从 CO-RE 依赖的 `.BTF.ext` 中提取 structs 和 fields 的访问链。最后拿 program 的 dependency set 去查询前面的 dataset，就能按 kernel image 生成报告。字段缺失通常意味着 compile 或 relocation 会失败；缺失的 function、tracepoint、syscall 会导致 attachment error；函数签名变化或兼容 type 变化会引发 stray read；selective inline 和 duplication 则会让 probe 只看见一部分调用。这种把 loud failure 和 silent failure 分开的方式，让 DepSurf 变得很实用。

## 实验评估

实验设计和论文主张是对齐的。作者没有只做 source-level diff，而是分析 25 个 Ubuntu kernel images，覆盖 17 个版本、8 年时间、5 种架构、5 种 flavor、14 个 compiler versions；再把结果应用到 BCC 和 Tracee 的 53 个真实 eBPF programs 上。

相邻 LTS 之间，functions 和 structs 最多分别有 24% 被新增、10% 和 4% 被删除；tracepoints 的新增高到 39%，删除也有 5%。就算 construct 还存在，定义也并不稳：6% 的 functions、18% 的 structs、16% 的 tracepoints 会变化。配置差异主要改的是有没有；在某些 builds 里，大约四分之一的 functions 和 structs 会消失，34% 的 tracepoints 可能不存在。编译阶段再加一层扰动：36% 的 functions 会 full inline，11% selective inline，16% 被 transformation，12% 出现 duplication。

这些数字在真实程序上也确实转化成问题。53 个程序里有 42 个，也就是 83%，在作者检查的 kernels 上至少撞到一种 mismatch；真正完全没问题的只有 9 个。25 个依赖 functions 的程序里，有 14 个受 selective inline 影响，14 个遇到 signature changes，14 个碰到 compiler transformation。25 个依赖 tracepoints 的程序里，有 18 个会被 tracepoint changes 影响。论文还把不少结果和 BCC 的 GitHub issues、修复提交对上号，包括 `biotop` 和 `readahead` 两个案例。主要保留意见还是样本范围偏 Ubuntu，不能直接外推成所有发行版和未来工具链的定律。

## 创新性与影响

这项工作的创新不在于再造一个 eBPF runtime，而在于把 portability 重新表述成发生在 binary image 边界上的系统问题。CO-RE 提供了 relocation 机制，但没有告诉开发者哪些情况根本不是 relocation 能解决的；verifier 和安全性研究关心的是程序是否合法，DepSurf 追问的是一个合法的 eBPF program 换了 kernel 之后，语义还剩多少。这个区分对 BCC、Tracee 维护者、发行版构建者和 kernel developers 都很重要，因为它把「不要破坏 userspace」变成了对内部 hooks 的具体检查。

## 局限性

DepSurf 看得到 exposed constructs 和 types，看不到语义。如果某个 hook 的签名没变，但行为已经变了，它抓不住。作者也没有声称覆盖所有 distro、全部 configs 或全部 compiler choices。另一个限制是诊断不等于自动修复：有些 mismatch 可以靠 fallback、更好的 tracepoint 或更丰富的 metadata 缓解，但另一些仍然需要人工改写 eBPF program，甚至要求 kernel maintainers 主动提供更稳定的 hooks。

## 相关工作

- _Cantrill et al. (USENIX ATC '04)_ - DTrace 试图给内核探针提供稳定抽象；DepSurf 说明 eBPF 目前没有对应的兼容层，所以必须做 image-level 诊断。
- _Tsai et al. (EuroSys '16)_ - 这项工作研究的是 system call 边界上的 Linux 兼容性；DepSurf 进一步下沉到 eBPF 直接依赖的 functions、structs 和 tracepoints。
- _Jia et al. (HotOS '23)_ - 该文强调 kernel extension verification 本身就很难；DepSurf 补上的则是另一面，即便程序合法，kernel 演化依旧会让它失配。
- _Deokar et al. (SIGCOMM eBPF Workshop '24)_ - 他们总结了 eBPF application development 的真实痛点；DepSurf 把这些痛点落实为可检测的 dependency-surface mismatches 及其后果。

## 我的笔记

<!-- 留空；由人工补充 -->
