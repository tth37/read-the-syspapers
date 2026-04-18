---
title: "Extending Applications Safely and Efficiently"
oneline: "EIM 把扩展权限建模为对宿主状态、函数和资源的 capabilities，bpftime 再用 eBPF 验证、MPK 隔离和 concealed hooks 高效执行这些策略。"
authors:
  - "Yusheng Zheng"
  - "Tong Yu"
  - "Yiwei Yang"
  - "Yanpeng Hu"
  - "Xiaozheng Lai"
  - "Dan Williams"
  - "Andi Quinn"
affiliations:
  - "UC Santa Cruz"
  - "eunomia-bpf Community"
  - "ShanghaiTech University"
  - "South China University of Technology"
  - "Virginia Tech"
conference: osdi-2025
code_url: "https://github.com/eunomia-bpf/bpftime"
tags:
  - ebpf
  - isolation
  - security
  - pl-systems
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文把 userspace extensibility 拆成接口设计和运行时执行两部分。EIM 用 capability 精确定义扩展可访问的宿主状态、函数与资源，bpftime 再用 eBPF 风格验证、MPK 隔离和 concealed hooks 去落实这套策略。

## 问题背景

现代应用需要扩展来做 observability、安全策略、调试和部署定制，但现有做法各有硬伤。原生 plugin 和 binary instrumentation 很快，却基本继承宿主全部权限。语言沙箱和 SFI 方案能提供隔离，但常常要求宿主自己补安全检查，或者依赖昂贵的运行时检查。基于子进程或特权域的隔离更强，可每次进入扩展都要付出类似 context switch 的代价，在 Nginx、Redis、SSL tracing 这类热路径里并不合适。

论文认为，真正缺失的是一种能按部署表达最小权限的扩展接口。不同 extension point 需要的宿主交互差别很大：监控探针可能只该读取 request；防火墙扩展则需要改写 response，但不该读取无关内部状态。现有框架很难把这种按 entry 区分的 safety/interconnectedness trade-off 清楚表达出来。

## 核心洞察

论文的核心命题是：扩展安全应该被写成一个 capability interface，覆盖扩展可能消耗的一切东西，包括宿主变量、宿主函数，以及内存和指令预算这类普通资源。一旦接口被显式化，policy enforcement 就不必再和重量级隔离绑在一起。bpftime 让验证器证明扩展只用了允许的 capability，再用轻量硬件保护去维持扩展状态的完整性。

第二个关键观察是，没人用的 extension point 不该带来任何运行时成本。bpftime 因此先把 hook 从编译后二进制里移除，只有在部署真正加载对应扩展时，才把入口重新注入回去。

## 设计

EIM 分成两层。开发期规范由 application developer 编写，列出宿主愿意暴露给扩展的接口面，包括 state capabilities、带约束的 function capabilities，以及可被 hook 的 extension entries。部署期规范则由 extension manager 编写，把这些能力组合成 extension classes，并为每个 entry 指定精确的 allowed capability 集合。

bpftime 保留 eBPF 的编程模型。扩展写成 eBPF 程序，并通过普通 eBPF 相关系统调用加载；userspace loader 拦截这些调用，把 EIM 规则转成 verifier 约束。它会解析宿主二进制中的 DWARF，导出类似 BTF 的类型信息，把宿主函数 capability 替换成生成出的 mock kfunc，并插入函数约束对应的断言，再复用内核 verifier 检查类型安全、内存安全和对 extension class 的遵守。通过验证后，扩展被 JIT 成本地代码。

运行时则把 binary rewriting 和进程内隔离结合起来。rewriter 只为真正被使用的 extension entry 安装 trampoline；普通函数 hook 用 instruction trampoline，system-call hook 用 zpoline 风格改写。随后 runtime 用 ERIM 风格的 Intel MPK 域保护扩展代码和扩展内存，使其只在执行扩展期间可访问。bpftime maps 继续提供 eBPF 式的共享状态能力，包括跨进程和进程-内核共享。

## 实验评估

论文没有只给一个合成基准，而是评估了六个具体 use case，这和它的中心论点一致：瓶颈在真实应用中的热路径扩展执行。最有说服力的结果来自直接对比。对 Nginx 模块，bpftime 只带来 2% 的吞吐损失，而 Lua、WebAssembly、ERIM 和 RLBox 分别是 11%、12%、11% 和 9%。在 DeepFlow 场景里，把现有 eBPF probe 迁到 bpftime 后，被监控微服务的吞吐至少比 eBPF uprobe 提高 1.5 倍。对 sslsniff，最坏情况下的吞吐损失则从 eBPF 的 28.06% 降到 bpftime 的 7.41%。

Redis 和 FUSE 的案例说明，这个框架不只适合 observability。带 fast-notify 的 delayed-fsync 扩展能达到 65k requests/s，超过 Redis alwayson 模式的 5 倍，而且只比 everysec 慢约 10%，但 crash 时可能丢失的数据量比 everysec 少 5 个数量级。FUSE metadata cache 扩展把延迟最多降到原来的 1/250 左右。Syscount 也证明了 concealed entries 的价值：eBPF 监控会让目标进程和非目标进程都慢大约 10%，而 bpftime 只让被监控进程慢 3.36%，对未监控进程没有影响。

微基准解释了原因。对 uprobe 和 uretprobe，bpftime 比 eBPF 快一个数量级以上；但在 syscall tracepoint 上，它比 eBPF 慢约 1.5 倍。兼容性也不错：17 个现成的 BCC 和 bpftrace 工具可以不改代码直接运行，bpf-conformance 也只失败 1 项。需要保留的一点是，和 Lua、WebAssembly、ERIM、RLBox 的比较并不是策略完全等价的替代关系，因此这些结果更像工程开销对比，而不是严格对称的安全竞赛。

## 创新性与影响

它的创新点不在某个单独机制，而在组合方式：capability 风格的 userspace 扩展接口模型、eBPF 兼容的验证流水线、MPK 进程内隔离，以及 concealed hooks。相对于 Orbit、RLBox 和 ERIM，这篇论文第一次把这些思路围绕“部署期扩展权限”组织成一个完整系统，而不是只做 compartment 或通用 sandbox。

它最可能产生的影响是工程层面的。如果 bpftime 继续成熟，运维者就有机会把现有 eBPF 风格工具迁到 userspace 应用里，同时避开 uprobe 每次 trap 进内核的成本，也不必把 plugin 直接当作宿主的一部分来完全信任。

## 局限性

它的信任模型其实比标题看起来更窄。论文假设 application developer 和 extension developer 是可信但可能犯错的，extension manager 是可信且不会出错的，而且宿主应用具备 control-flow integrity。因此，它主要防的是 buggy extension，以及试图篡改扩展状态的受损宿主，而不是面对恶意 extension author 的完整防御体系。

原型本身也有明显边界。开发期规范依赖注解生成，目前只支持 C/C++ 宿主；隔离实现只覆盖 Intel x86 上的 MPK；当前运行时每个 entry 只支持一个扩展；论文还明确承认其设计会受到 ERIM 类方案已知的 syscall-based 攻击影响。trusted computing base 也不小，包含内核 verifier、binary rewriter、操作系统以及硬件保护机制。

## 相关工作

- _Jing and Huang (OSDI '22)_ - Orbit 借助操作系统支持来隔离 auxiliary execution，但它并不是围绕部署期 extension points 和 least-privilege extension classes 来设计的。
- _Narayan et al. (USENIX Security '20)_ - RLBox 在 Firefox 中做组件沙箱化，而 bpftime 关注的是已编译应用里的 extension hook 以及 capability 受限的宿主交互。
- _Vahldiek-Oberwagner et al. (USENIX Security '19)_ - ERIM 提供了 bpftime 借用的 MPK 隔离底座，但没有 EIM 这样的接口模型，也没有 concealed hooks。
- _Bijlani and Ramachandran (USENIX ATC '19)_ - ExtFuse 通过更侵入式的方式提升 FUSE 性能，而 bpftime 则试图用 extension hook 在不引入自定义内核模块的前提下取得类似收益。

## 我的笔记

<!-- 留空；由人工补充 -->
