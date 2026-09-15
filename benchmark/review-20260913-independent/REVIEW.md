# Themis 独立论文与代码审查

审查日期：2026-09-13。代码基线：`e679a8976ec718cafa7b4e6ad04a08624b2e5371`，开始审查时工作树干净。本次没有修改生产代码、原有测试或实验配置，没有调用 AWS、启动远程实验或运行作者的部署脚本。新增文件仅为本审查及复核材料。

**结论：当前对象是自主实现的 Themis 排序层，加上公共基准测试式的提交适配器。它既不是作者公开性能程序的逐行复现，也不是完整 Themis–HotStuff 集成。** 对用户当前 `n=20,F=4,γ=1`，本次核对的核心计票、分类、补边和顺序释放规则，没有发现需要回滚的“过度优化”；但是输入模型、集成边界和若干额外实现成本，使当前实验不能直接检验论文完整协议的性能或攻击结论。

本报告区分三种证据：**代码确定**、**本地小例实证**、**尚需运行数据**。已有测试通过不等于完整正确性证明；源论文存在表述缺口时，不把自行补全的规则冒充原算法。

## 1. 锁定文献版本和作者快照

| 标识 | 锁定材料 | 本次确认的内容 |
|---|---|---|
| P21 | [ePrint 初稿，2021-11-06 15:48:37](https://eprint.iacr.org/archive/2021/1465/1636213717.pdf)，33 页 | §4、图1–3；图2没有补边源交易出现 `n−2F` 次的条件。§5.1主要是5节点，表2/3为 median latency 与 peak throughput；单区 β=400。不能混用后来扩展实验的口径。 |
| P22 | [ePrint 修订版，2022-11-29 23:45:44](https://eprint.iacr.org/archive/2021/1465/1669765544.pdf)，19 页 | 本次算法主基准：§IV、图1–3、附录图7；性能 §V-A、图4；攻击 §VI-E、图6。图2增加源交易出现门槛。 |
| D25 | [Kelkar 博士论文，2025年8月](https://mahimnakelkar.github.io/dissertation.pdf)，*Rethinking Security for Emerging Decentralized Systems* | 第6章，印刷页138 / PDF页156 明确单方出现也计顺序票；图6.1–6.4延续修订版核心结构。性能见 §6.5.1；公平性实验另见第7章。 |
| A23 | [作者仓库固定提交](https://github.com/anonthemis/themis-src-anon/tree/6b3aef8f0ea70ec939322baa61853f934e4e7fb2) | `6b3aef8f0ea70ec939322baa61853f934e4e7fb2`，2023-05-19；父提交 `bd70894379e208ca6e5e9576d3767f7a3040590b`，2022-08-19。最新提交只新增 `gamma_tradeoffs.py`，下述 C++ 性能路径两次提交相同。 |

[ePrint 版本页](https://eprint.iacr.org/archive/versions/2021/1465)列出3个时间戳；2022-11-29 23:42:08 与 23:45:44 的实际 PDF 字节相同，也与本次下载的最新版相同。不能仅凭下载文件名认版本。本次核对了 PDF 内容并渲染查看算法页。SHA-256：

- P21：`2796332824740003ca238d48c58ecb4b7d7499e49859f20877e63a09e32a43c7`
- P22：`51178e3871782abf48658184a4d588c434c0803482d01ad46efb925f920a98fd`
- D25：`34c6fdef83dba4e1e385cfc04fff82debd5ae1456ac9bf819ce4d0bd5af3803a`

**“澄清”与“修改”要分开。** P21→P22 的 FairUpdate 源出现条件是可观察的算法条件变化；D25 的单方出现括号是明确的后续定义澄清。原两版均没有这句括号，但其图性质证明依赖这种计票解释。可以写“采用2022修订版，并按作者2025正文明确的 Weight 定义实现”；不宜写“逐字复现2021初稿”。没有证据认定作者修改了核心 Themis 来做额外性能优化。

### 作者公开性能路径究竟执行什么

README 指向 `Aequitas-hotstuff/libhotstuff`；其编译及部署入口最终运行 C++ example，进入 `HotStuffBase::start` 的命令队列回调。以下均依据 A23 的有效语句及注释边界，不把注释中的旧实现算作执行路径：

| 环节 | 可核对证据 | 判定 |
|---|---|---|
| 聚批 | [hotstuff.cpp:734](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/src/hotstuff.cpp#L734)：缓冲达到 `blk_size` 后取恰好该数量 | 真实的 proposal 输入批量控制；不是周期 List 上报 |
| replica 顺序来源 | 同文件781行真实取列表调用被注释；783–794行给 `cmds` 造递增时间戳，再复制 `peers.size()` 份同一列表 | 没有实际取得 `n−F` 个独立签名接收顺序 |
| 权重、补边 | [hotstuff.cpp:514](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/src/hotstuff.cpp#L514)：514–548及555–588是块注释 | 两两权重计票和旧图更新未执行 |
| 新图 | 同文件611–632行直接 `G.addedge(i,j)`，阈值分支被注释 | 真实执行构图计算，但用传递图替代真实计票输出 |
| deferred / finalize | 644–674旧图处理被注释；681行 tournament 检查被注释；685仍调用 `G.finalize` | 执行一部分图计算，但没有完整 deferred 生命周期 |
| 排序结果接入共识 | 700构造的排序对象为局部量，函数返回 void；[825–827行](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/src/hotstuff.cpp#L825)把原 `cmds` 送入 `on_propose` | 这条路径把排序计算作为负载；未用其输出替换共识交易序列 |
| 共识本身 | [consensus.cpp:97](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/src/consensus.cpp#L97)：QC、锁和提交链；227行投票聚合；`entity.cpp:59–68` 验证 QC | 真实存在 HotStuff 共识路径；不能说整个程序都是模拟，也不能把 QC 验证说成 Themis 公平性证明验证 |

这足以否定“这个公开快照的性能路径是完整论文协议实现”。但**没有作者生成论文每个数据点时的二进制、构建清单和原始日志，不能进一步断言论文所有图都由这个快照精确生成**。作者 README 的复现指引与公开代码之间存在需要披露的实现范围差距。

作者攻击实验是另一条路径：[adv_reorder.py](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/simulations/adv_reorder.py)。它合成发送时间及独立网络延迟，离线反转部分节点的全部交易顺序；`themis_protocol` 在完整输入上计票、求 SCC，而非运行在线 List/Update/共识。该函数使用全部 n 个排序；median 分支使用前 n−F 个。它没有在线 deferred、Hamiltonian 跨 proposal 释放或 TPS 测量。论文攻击图的“逆转比例”与当前在线 TPS 不是同一指标。该脚本对 SCC 内 ID 排序后比较逆序，也不能不经复核就作为论文“进入同一 cycle 也算攻击成功”表述的完整计分 oracle。

## 2. 当前入口与算法规则

当前有效入口：[main.go:338](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/main.go:338) → `runDistributedMode` → `NewOFOService` + `benchmarkNodeAdapter` → `Start` 定时生成报告 → collector → proposer → hosting gate → `CommitVerifiedProposal` → FairFinalize 风格的前缀释放。`main.go` 开头及597–679行、`service.go` 开头的历史注释没有进入此链路。

`F` 是阈值参数；`b` 只用于设置最高 b 个 ID 的 `isMalicious`。未配置 b 时 CLI 的 `−1`、Python 的 null 均回退到 `b=F`；显式0保持0。对于当前配置：

| 量 | 独立计算 |
|---|---:|
| List / Update 采用数、hosting确认门槛 | n−F=16 |
| solid 出现数 | n−2F=12 |
| nonblank / 建边阈值 τ | ceil(n(1−γ)+F+1)=5 |
| shaded | 出现5至11次 |
| blank | 出现0至4次 |
| 容错前提 | n(2γ−1)>4F，即20>16 |

这里 γ 的原文前提是 **γn 个节点的接收顺序**，不是 γ(n−F) 个诚实节点。反转的是“声称的顺序”，不能把声称次序替代真实接收次序用于公平性验证。与 AUTIG 的 γ 是否相同，必须核对 AUTIG 自己的定义；本仓库没有其可执行实现，不能仅凭适配器注释确认两边完全一致。

对每份报告，A、B 都出现时按实际列表位置投一票；只有 A 出现时给 A→B 一票；只有 B 出现时给 B→A 一票；均缺席时不投票。因此双向权重之和等于至少包含一方的报告数。双方达到 τ 时选较大权重，平票确定性选边；均未达到时不建边。FairUpdate 另要求源节点本轮出现数达到 n−2F，并且只补同一旧 proposal 内尚不存在的边。

### 逐项差异与一致性表

类型用语：**修复**=必要正确性条件；**工程**=不改变算法输出语义的实现选择；**优化**=额外性能优化；**偏离**=协议语义或必要集成缺失；**低效**=自主实现的额外工作；**观测**=日志、测量或有效性保护。无差异时直接标“一致”，不为了凑问题而判错。

| 论文或作者实现要求 | 当前实现及代码位置 | 差异类型 | 对正确性/性能的影响 | 证据与置信度 |
|---|---|---|---|---|
| P22 §IV：按接收次序记录 | [service.go:649](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:649)，校验交易hash、拿锁后记第一次 `time.Now()`；上报时排序，时刻相同按ID破平票 | 工程；接收事件定义需披露 | 记录的是服务处理接收，不是socket到达；hash/锁/worker排队不计入本地先前接收时间。当前单源FIFO一般保留交易相对次序，但多客户端集成需重新定义边界 | 代码确定，高 |
| P22 §II：客户端向所有节点发交易；攻击实验有接收顺序分歧 | [main.go:681](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/main.go:681)，一个leader内发生器，按ID依次广播每笔交易 | 实验模型不足 | 同一诚实输入流，难以产生 Condorcet 图和脆弱交易对；不是算法优化 | 代码确定，高；不同网络故障运行需日志 |
| List 是全部未 proposed 接收序列，报告有签名 | [service.go:690](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:690)、728–733、769–803；`loSize`不存储不使用 | 一致；完整列表属于必要语义 | 不截断、不按发送删除；完整积压可能很大。不能恢复任意截断来“忠实保留低性能” | P21/P22 local order定义；代码及现有测试，高 |
| Update 只需未完整旧 proposal 的相关交易；附录图7更精确说缺边端点 | [service.go:691](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:691)、738–764，把全部未最终释放图中的已接收交易放入 Update | 低效；证据范围宽于最小要求 | 包含无缺边 solid、甚至已完整但被前缀挡住的图。对缺边端点的相对次序和票数无影响，却增加排序、hash、网络和扫描 | P22 图7；最小例R5，高 |
| 区分未proposed、deferred、完成 | [service.go:961](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:961)、1085–1153、1290–1327 | 基本一致；命名不精确 | `committedTxIDs`其实是最终释放ID；`deferredProposals`是所有未释放图，含已完整图。新构图同时排除两者；剪掉的shaded仍留pool再报 | 代码确定，高 |
| distinct n−F 已签名报告 | [service.go:806](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:806)、857–891、950–959 | 一致；到达顺序是工程选择 | 校验sender范围、ID和sequence，按sender去重，凑够即排批。pending中同sender取较新报告；不是固定最小ID集合，也不保证攻击者入选 | 代码确定，高 |
| 按真实计票分类/建边 | [dependency.go:64](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/dependency.go:64)、109–217 | 当前主配置一致；单方缺席修复应保留 | 执行真实权重计数，没有采用作者C++模拟传递图捷径。另有非整数γ边界疑点R3 | P22图1、D25 p138；R1/R3，高 |
| shaded保留当且仅当可达solid | [dependency.go:223](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/dependency.go:223) SCC反向可达剪枝 | 工程、语义一致 | 在满足论文图性质的输入上，与末solid之后截尾等价；没有solid则输出空。任意DAG上的差异不能直接当合法论文输入反例 | P22正文和Lemma B.1；高，整数边界另论 |
| FairUpdate源出现门槛、已有边不变、确定性平票 | [dependency.go:318](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/dependency.go:318)，337–369、425–436 | 与P22/D25一致；不同于P21 | 不应删除源出现条件来提速；只补同图缺边。Update允许单方出现票 | P21/P22图2、R2，高 |
| FairFinalize只释放连续已完整proposal前缀 | [service.go:1105](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:1105)，遇首个非tournament即break | 必要正确性条件，当前一致 | 不能跳过旧缺边图先输出新图。P22图3“最后tournament”简写须结合正文“所有i≤k完整”理解 | P22 §IV-B、R5，高 |
| 每个SCC用确定性Hamiltonian顺序，末SCC末交易为solid | [dependency.go:486](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/dependency.go:486)、532–630 | 输出规则一致；实现复杂度有额外成本 | 不是对SCC直接按ID排序；按ID选择路径/环是允许的确定化。末solid选择保留跨proposal边界性质。现有枚举/样本测试及本次R5通过，非全规模证明 | P22图3、§IV-B；高 |
| 可选提前释放纯solid SCC前缀 | 当前等整图成为tournament | 未启用论文可选优化 | 是可明确保留的未优化基线；不能把该等待说成所有Themis实现不可避免的下限 | P22 p7 明示可选；高 |
| follower重算FairPropose/FairUpdate验证 | [service.go:1014](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:1014) → recompute、比较图/状态/updates | 必要验证，当前一致 | 不能称为不该做的重复计算，也不能为对齐作者模拟速度删掉 | P22 Replica verification；高 |
| leader构图后无需为算法定义重复相同计算 | [benchmark_adapter.go:192](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/benchmark_adapter.go:192)再次Verify；构建前也重验collector已验报告 | 低效/防御性工程检查 | 正常成功路径leader至少两次构图，采用报告通常经过三次签名验证；状态检查不能盲删，但可按不可变证据缓存密码验证 | R7计数及调用链，高 |
| 已验证同一proposal可在确认后应用 | [benchmark_adapter.go:148](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/benchmark_adapter.go:148)、162–166、229；[service.go:1069](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:1069) | 优化：缓存已验证proposal，省提交时再次验同一证据 | 不跳过首次验证或最终排序，不改变论文排序算法；这是已确认的工程去重优化，不是更强Themis变体 | 代码、R7，高；导出API需由可信宿主管理 |
| consensus先同意proposal，再从已同意序列释放 | [benchmark_adapter.go:175](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/benchmark_adapter.go:175)等n−F ACK后模拟commit | 偏离/完整集成缺失 | 无BFT证书、view/leader切换、链提交、持久化和客户端完成回执。真实签名报告不等于真实BFT共识 | P22 §IV及图7；代码确定，高 |
| PKI与不可伪造身份 | [benchmark_adapter.go:21](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/benchmark_adapter.go:21)由公开replicaID推导密钥；[network.go:106](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/network/network.go:106)不把消息From绑定认证连接；ACK无签名 | benchmark假设；完整协议缺失 | Ed25519计算真实执行，但任意节点可复算其他私钥；当前脚本只反转排序，不测试伪造。不能声称真实Byzantine安全部署 | P22 §II；代码确定，高 |
| 每轮的List/Update应反映相应proposal状态 | [service.go:624](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:624)、806–854、942–959；签名中无父状态或高度 | 工程调度差异＋低效 | 独立tick可积累多批旧分类证据；当前状态变化后整批失效。拒绝本身安全，失效工作和报告补发延迟不是论文必然代价 | R6，高；实际占比未知 |
| 图算法应按选定复杂度实现 | [dependency.go:37](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/dependency.go:37)、337、448、644、683；[service.go:1196](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:1196) | 低效 | 多处在两两/逐边循环内线性扫描邻接切片，密图可达三次成本；不是论文“图有平方条边”的同义实现 | 代码确定、高；CPU占比需profile |
| 历史去重必要，但未要求每轮复制全部已完成历史 | [service.go:975](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:975)、1085，digest序列化见[type.go:115](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/types/type.go:115) | 低效 | 重建排除集O(H)、克隆所有未释放图、重复排序/hash；长期运行成本随历史增长 | 代码确定，高 |
| 控制消息与交易接收无固定线程要求 | [network.go:49](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/network/network.go:49)、78，adapter同步Verify | 工程选择，可引入额外排队 | 每节点单worker，Verify/SCC/commit可阻塞交易和ACK处理；加worker前需保序，不能只改一个数字 | 代码确定，高；瓶颈强度未知 |
| 指标应记真实完成与未完成 | [main.go:813](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/main.go:813)、[service.go:1314](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:1314)、[fabfile.py:205](D:/Work/go/workplace/code/SpeedFair_simplify/benchmark/fabfile.py:205) | 观测/必要测量修复 | 截止前leader最终释放数除配置窗口；只对完成样本记延迟，记录Outstanding、实际输入、失败与最终状态。不能将完成样本平均延迟推广到全部交易 | 代码和日志，高 |
| 失败、过载运行不能伪装成功 | [service.go:674](D:/Work/go/workplace/code/SpeedFair_simplify/pkg/ofo/service.go:674)、[fabfile.py:151](D:/Work/go/workplace/code/SpeedFair_simplify/benchmark/fabfile.py:151)、231–243、504–528 | 观测＋测量保护 | evidence队列满就标INVALID并取消pipeline，释放worker避免ACK死锁；保护改变失败运行的结束方式，不是有效运行的算法加速 | 代码、现有guard测试，高 |

## 3. 按严重程度排列的问题与修改建议

这里的 P1 表示会直接使论文比较或研究结论不成立，P2 表示条件性正确性、实现归因或复核完整性问题。**本次没有确认当前主配置存在新的核心建边方向错误。**

1. **P1：复现对象和结论边界必须改正。** 当前排序层指标不能作为完整Themis/HotStuff指标；作者公开模拟计算路径也不是正确性oracle。论文写明基线版本、D25澄清、真实执行范围和公共宿主假设。如果目标确实是完整端到端复现，需要另行接入真实共识并重测；不能用现有gate代替。
2. **P1：当前输入不足以支撑论文式抗重排实验。** 单源FIFO使诚实相对顺序一致；b扫描主要改变报告声称顺序，常不改变图。增加一个独立的接收顺序回放/多客户端实验，记录真实接收次序和按Dist分桶的攻击成功率。保留单源实验作为单源吞吐场景，不强行解释成通用Byzantine压力测试。
3. **P1（若主张算法性能差距）：密图额外三次成本与重复工作必须隔离。** 先profile，再把邻接查询/去重、图比较和历史排除集改成能保持同一输出的实现；以相同签名证据做差分验证。这些是修正自主实现额外成本，不能称“删除论文不足”。若截稿前不改，只能比较当前具体实现及配置，不能把劣势归因于Themis算法本身。
4. **P2：周期报告与状态分类不同步。** 为报告补充明确上下文或提供状态一致的生成/消费策略；分离密码签名验证缓存和状态有效性检查。新策略可能改变选中报告，因此应单独版本和重测，不冒称零语义影响。不可直接放行过期Update，不能只靠增大队列掩盖。
5. **P2：非整数γ边界存在“伪代码字面值与图性质引理”缺口。** R3给出已运行反例。代码是忠实执行字面阈值，不能立即把ceil改floor当作普通bug修复。主配置γ=1不受此例影响；截稿前把该参数区间标记未验证。若开放通用γ，需明确整数化规范并证明/测试；例如把 `n−2F≥2τ−1` 作为图完备性引理的额外充分检查，或暂限γn为整数，都是需要披露的域收紧，不是原论文现成要求。
6. **P2：缺少“采用了谁”的证据与阶段计时。** 现有日志不知道每轮采用攻击者数、图大小和SCC分布；collector_rejected、build_nil混合原因。补日志即可，不用改算法或故意把攻击者选进每轮。
7. **P2：统计可追溯性仍不完整。** `_write_result`校验已有F/b元数据但不要求每个节点都提供，记录build元数据却不强制节点版本一致；部署拉取可变分支，未绑定此次本地提交。应保存实际SHA、dirty diff或源码hash、binary hash、逐节点参数/硬件映射，并拒绝缺失或不一致。失败日志保留，同时增加失败运行manifest，避免汇总只见成功JSON。
8. **P2：安全与数据可用性边界。** 确定性测试密钥、未认证ACK/连接、只有交易hash缓存而无交易执行/缺失payload取回协议，都是benchmark范围限制。若只提交排序层结果，可明确假设暂缓；若宣称完整BFT复现，则属于必须补齐的集成工作。

对 `lo_size` 的特别建议：继续保留完整List；将入口明确标记inactive即可。不要给Themis恢复AUTIG式本地截断。若要控制论文β，需要定义对**新proposal候选**的批量策略并论证不会切断必要依赖，不能把 `lo_size=200` 或 `λΔ≈200` 说成已经实现β=200。

## 4. 现象A：50 ms为什么可能优于150 ms

### interval实际控制什么

它直接控制每个replica调用 `generateAndSendOrders` 的ticker周期，包含fresh List构造、排序、签名、Update构造/签名和发送。它**没有直接设置**客户端输入频率、collector的超时、共识round时钟或proposal大小。当前collector没有注释旧版中的 `2*interval` 清空定时器。collector异步累积，proposer串行构建并同步等待hosting；所以50ms意味着每节点目标每秒20次上报，150ms约6.67次，**不等于每秒恰好20或6.67个成功proposal**。生成或发送变慢时ticker也不会保证逐tick执行完整次数。

更短间隔同时可能带来：更少等待、更小fresh批次；更多固定开销、签名、重复报告和空批；同一状态下更多排队报告；提交后更多过时证据。`pending`只保存同sender最新一份但更新之前已经验签；batch入队后不是“取最新状态”的队列。证据队列512、批队列256、网络队列10000都不是论文β。

### 把不同成本拆开

设 q=n−F，U为本轮报告中的未proposed交易规模，G为剪枝前图的nonblank数，H为全部已释放历史ID数，D为未释放图规模。一次计算不只是平方图计票：

| 工作 | 当前发生位置/规模 | interval变短时不能省略的部分 |
|---|---|---|
| 新交易payload处理 | 每笔交易向n节点发送、hash并入pool；发生器与leader共资源 | 若实际输入不变，每秒新交易工作量大体不变；发送反压则实际λ也变 |
| List/Update排序与签名 | 每节点每tick扫描pool、未释放图，排序并签名；空List也签名 | 次数增加，重复ID可增加；Update规模不只由新增流量决定 |
| fresh成对计票 | 每份列表遍历前后交易及缺席端点；blank在部分内部循环仍被访问 | 若U≈G≈λΔ，单位时间约O(qλ²Δ)；但积压、blank与重复报告会使近似失效 |
| 图插边、存在性检查 | `addEdge`逐出边查重，`IsTournament`逐交易对扫描双方出边 | 密图可有O(G³)，不是只有O(G²) |
| 图比较 | `edgeMapsEqual`每条边用`containsTx`线性查另一图出边，两方向比较 | 密图可有O(G³)；每个follower也执行 |
| SCC、condensation、Hamiltonian | Tarjan还排序邻接；condensation边去重线性查找；环构造反复线性查邻接 | 无法把所有这些实现都当作原文“线性于边数”的图处理 |
| deferred工作 | 每次build/verify克隆所有未释放图；FairUpdate扫描每张图中所有交易对寻找缺边 | 无缺边但被挡住的完整图也会被扫描；规模可能取决于运行历史 |
| 历史去重 | 每次recompute把全部H个完成ID复制到excluded | 成功批越多扫描越频繁，运行越久H越大；不是每笔只扫描一次 |
| 重复验证 | collector验签、build验签、leader hosting再次验签与重构；followers独立验证 | 短间隔可增加无效/无进展批上的固定验证成本 |
| 传输/排队 | leader逐节点同步Send，payload、candidate、commit共享连接；单worker处理消息 | 图、proof大小影响网络及FIFO阻塞；不能只看纯排序CPU |

一个不靠计时的额外成本证据：完全传递图有G(G−1)/2条边。当前 `addEdge` 在线性邻接切片上插入所有互不重复的边，查重比较次数为 `Σ d(d−1)/2 = G(G−1)(G−2)/6`。G=50时为19,600，G=400时为10,586,800。这个三次项来自数据结构/调用方式；即使诚实顺序完全一致，也存在，不应标成论文不可避免的算法缺陷。

只为解释方向的简化模型：假设稳定输入λ、每Δ产生一个有效proposal、G≈λΔ、几乎无重复/积压/deferred，单位时间工作可以包含

`W(Δ,t) ≈ a/Δ + bλ + c q λ²Δ + d λ³Δ² + e H(t)/Δ`。

其中a包含每轮固定处理；c为成对计票；d为本实现密图线性查询嵌套成本；e为本实现历史复制。H增长或过载后，该模型还不够，应加入失效批、Update和网络。它说明短间隔既可能减小某些大批成本，也可能增加固定和历史工作；**不是对用户50/150ms数据的实测归因，也不要求曲线必须出现反转**。

### 现有日志究竟支持什么

仓库可见的是9个本地smoke日志和旧microbenchmark产物；没有用户所述完整远程50ms/150ms矩阵的原始日志。旧审查文档记载的500/700 TPS点只作为历史说明，未找到相应完整原始记录，不当作独立验证证据。`pkg/cpu_themis.pprof`大小为0，pprof读取失败，不能据它判断热点。现有microbench是旧提交/dirty状态下的本地计算样本，不是当前网络性能证据。

以下两份日志来自同一标注 `127d1df... modified=true` 的4秒smoke；它们不等同本次干净基线，也不能证明该次dirty源码包含全部当前修复：

| 指标 | [50ms日志](D:/Work/go/workplace/code/SpeedFair_simplify/.benchmark-test-venv/smoke-n10-f1-r100-i50-run1-20260912T150756150568Z-3f188d1c.log) | [150ms日志](D:/Work/go/workplace/code/SpeedFair_simplify/.benchmark-test-venv/smoke-n10-f1-r100-i150-run1-20260912T150804856223Z-9c7f2c60.log) |
|---|---:|---:|
| n,F,γ，配置输入 | 10,1,.95，100/s | 同左 |
| 实际提交/完成/窗口 | 399 / 394 / 4s | 399 / 389 / 4s |
| 输出TPS | 98.50 | 97.25 |
| 完成样本平均延迟 | 41ms | 94ms |
| leader List次数 / ID总数 / 最大长度 | 80 / 450 / 11 | 26 / 394 / 17 |
| build次数 / build_nil | 79 / 1 | 26 / 0 |
| 累计build耗时 | 81.7284ms | 31.2815ms |
| 累计hosting耗时 | 413.4718ms | 260.9776ms |
| 成功proposal / 末采样deferred数 | 78 / 0 | 26 / 0 |
| Outstanding | 5 | 10 |

这两个样本**支持**较短间隔下List较小、报告更多、累计build/hosting时间反而更多、完成延迟更短；TPS差是固定窗口内多完成5笔。它们**不支持**“50ms整体运算更少”“150ms已达到容量上限”或“这是远程大差距的原因”。列表统计只来自leader，不能用最大List长度充当proposal图节点数；`Finalized/proposalsAccepted`至多是聚合每成功proposal释放量近似，不能分离更新释放的旧图。

现在没有发现50ms分支会省去本应执行的签名验证、FairUpdate、图比较或最终排序。两种interval走相同代码。`build_nil`不进入hosting包括无新工作、剪枝为空、过期报告、取消等；它不是“正确性失败数”。被取消计算不计TPS是正确的，但其消耗仍需profile。只要有deferred，构建仍调用FairUpdate；没有deferred时不调用是必要操作的输入条件未触发，而非偷偷省略算法。

## 5. 现象B：b增加而TPS近乎不变

### F/b分离核对

本次沿全部有效实验入口检查：`settings → _remote_parameters/_local_parameters → _command → resolveByzantineCount → runDistributedMode`。F继续传给 `NewOFOService` 和hosting的faultCount；b只用于 `totalNodes−b` 的攻击ID阈值。分类、边阈值、报告门槛、ACK门槛均未用b替换F。Python远程循环显式枚举b并传CLI，17个采集器测试含该路径的mock验证。现有注释旧代码按F攻击，不是现在的执行分支。

本次查到的有效攻击只有：fresh List反转，以及存在deferred时Update反转。它不改变集合，不主动延迟、不停发、不损坏签名、不操纵ACK、不做leader攻击或共识view-change。默认leader为ID0，b≤F<n，因此当前攻击集合不包含leader。

### 配置攻击者数不等于采用攻击者数

记每次真正提交proposal的Proof中攻击者数为c。collector选择先凑齐的distinct q份报告，随后按ID排序只是为了确定化，不是重新选sender。对n=20,F=4,b≤4，只能保证 `0≤c≤b`，无法从b推断c。四个被省略的节点完全可能涵盖全部攻击者；也可能c=b。当前没有持久化Proof、sender集合或c，无法追溯每轮实际值。最高ID攻击者还与机器排序/发送先后耦合，可能有选择偏差，但没有日志足以证明总被排除。

### 即使所有攻击者入选，图也可完全不变

对任何一对A、B，若所有诚实报告都声称A在B前且两者都出现，16份采用报告给正向16−c票、反向c票。c≤4意味着反向达不到τ=5，正向至少12。因此每个b都会得到同一条A→B。R4以三笔交易及c=0…4全部执行验证，输出始终A,B,C，三个SCC均为单点，不产生deferred。

这还与当前输入有关：无发送失败时，单发生器对各节点发送的交易投影是同一FIFO序列。诚实报告的fresh列表是在共同排除集下的接收前缀，非单纯“网络延迟很小”。在状态一致、没有同时间戳ID破平票改变先后的条件下，对早交易A、晚交易B，任何诚实报告都不会给B→A票；反向最多F票，无法建反向边。这样即使存在报告长度差异，图仍很难出现攻击实验中的循环/fragile pairs。单worker阻塞可改变时间和前缀长度，**并不意味着它会在这个单源FIFO工作负载中制造诚实交易相对逆序**。

反转本身是O(List长度)操作，且不改变每份列表的交易数、签名数或必须枚举的交易对数。在有诚实顺序分歧的输入上，反转才可能改变建边方向、SCC和保留shaded规模，进而改变计算；这仍不保证TPS单调下降。不能仅凭“攻击存在”推断“工作量必须增加”。

当前可见的5份 `byzantine-smoke-n20-f4-b*-r50-i150` 日志仅为3秒本地测试：b=0…3均提交149、完成142、TPS=47.33；b=4完成135、TPS=45.00；各末次采样deferred为0，实际输入49.67/s。它们说明该轻负载短窗口受输入和截止尾部影响很大，不能据此测系统上限；也没有足够分辨率排除短暂deferred。用户50ms的大规模结果没有可见原始数据，不能直接套用这5份smoke结论。

**论文并未报告“上述reverse攻击下TPS随实际恶意节点数下降”的同类曲线。** P22 §VI-E / 图6测试n=21,F=5和n=101,F=25、γ=1，观察相对于诚实排序的交易对逆转比例与Dist；其正文还指出该特定策略额外corruptions带来的收益较小。性能图4则是节点规模、β及部署环境比较。这两组问题不可拼接成一个预期TPS趋势。

应分别报告：①性能是否变化；②攻击证据是否入选；③入选后图和计算是否改变；④在**真实**接收顺序给出的前提下，论文公平性性质是否成立。当前TPS与末态一致检查只能回答①及有限一致性问题，不能回答④。

## 6. 与论文实验的可比性

| 项目 | P22 / 作者公开材料 | 当前可核实状态 | 允许的比较 |
|---|---|---|---|
| 机器 | P22：每节点C5.4xlarge、16vCPU、32GiB | settings期望m5.xlarge；脚本运行existing实例，并未核验实际机型/CPU配额。[AWS规格](https://aws.amazon.com/ec2/instance-types/m5/)中m5.xlarge名义资源为4vCPU/16GiB，真实实例仍需记录 | 资源不等价；不能按TPS比例直接判断算法复现对错 |
| n与区域 | P22：n=5至100；单区us-east-2；跨5区均分 | 当前矩阵n=20，配置us-east-1一地；远程按实例排序映射ID并用公网地址 | 可作为另一个单区场景；不是论文geo实验 |
| F与γ | 理论前提n(2γ−1)>4F；A23 server取floor((n−1)/4)，客户端ACK计数仍取floor((n−1)/3)+1；性能正文未逐点列γ | 主配置F4、γ1、n20合法；b0…4另扫 | 记录两边实际阈值，不从节点数或同名γ臆测等价 |
| proposal β | P22图4为50、400；正文另提geo下1200；A23按blk_size实际切批 | 无proposal β控制；lo_size200无效；interval150ms不是β | 只能比较不同报告周期，不能写“双方blocksize200” |
| 交易大小/执行 | P22性能正文未找到明确字节数；A23 `CommandDummy`两个uint32，payload由编译宏决定；公开构建配置未见REQSIZE定义 | canonical512B，前16B是计数/随机数，其余默认0；每节点真实发送并hash；排序协议交换ID；无状态机业务执行 | 不能认定512B与论文一致。A23“8B默认命令”是源码默认推导，不是已证实论文全部运行的字节数 |
| 客户端 | P22独立client节点；A23支持多个client，每client outstanding窗口，公开配置max_async175、max_iter200000 | 一个leader进程内发生器，与网络/排序争资源；目标100/300/500每秒，实际率另记 | 开环定速与闭环并发窗口不同；远程发起者位置也不同 |
| 共识 | 论文声明HotStuff集成；公开快照有真实HotStuff+模拟排序计算 | n−F验证ACK gate，无HotStuff | 端到端曲线不能直接比；双方同gate仍须分别审查AUTIG |
| 延迟起点 | A23 Request计时在发送调用后建立，完成取客户端响应计数达到其f+1；P21表为median | 本地发生器创建/广播前SubmissionTime → leader最终释放；只报完成均值，毫秒舍入；不是客户端响应RTT | P21 median与当前mean不可直接比较；当前leader端样本不依赖跨机时钟同步 |
| 吞吐窗口 | A23 `thr_hist.py`从第一条完成记录按默认1秒计数，保留最后不完整桶；另输出IQR过滤前后平均延迟 | 固定从实验start到deadline，TPS=截止前finalized/T；含启动阶段、截止尾部 | 固定窗口平均不等于峰值或稳态最大吞吐 |
| 稳态/积压 | 论文公开信息不足以重建每点warmup、drain、置信区间和运行长度 | 无显式warmup；到deadline停新输入/提案，不drain积压；followers等Finish应用已发送前缀；默认runs1 | 低完成率运行的平均完成延迟有选择偏差；不能称steady-state latency |
| 失败处理 | 论文每次失败运行处理未能从材料确定 | 检查send/reject/INVALID/panic及所有节点末态；实际输入不足仅标记，仍保存JSON；异常会停止当前矩阵 | 保留失败率/原因和低输入标记，不只报告成功点 |
| 攻击问题 | P22攻击图是离线逆序比例/Dist；网络frontrunning另用真实延迟测量及Wonderproxy数据 | 在线单源输入＋reverse报告的TPS | 不能用TPS替代公平性或攻击有效性；网络真实不代表运行了完整攻击协议 |

作者资源及统计的直接代码来源：[client的发送与确认](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/examples/hotstuff_client.cpp#L74)、[命令格式](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/include/hotstuff/client.h#L63)、[统计脚本](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/scripts/thr_hist.py#L38)、[并发窗口配置](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/scripts/deploy/group_vars/clients.yml)。公开脚本与论文数据口径不完全一致之处需如实列出，不替作者补造实验细节。

## 7. 最小反例与复核结果

[审查用测试文件](D:/Work/go/workplace/code/SpeedFair_simplify/benchmark/review-20260913-independent/audit_repros_test.go.txt)只在临时源码副本中以Go测试形式执行；它在仓库以 `.txt` 保存，避免改变原有测试包。下列预期值先从论文条件推导，再调用当前函数检验。

| 编号 | 最小输入与独立预期 | 当前结果 / 意义 |
|---|---|---|
| R1 单方缺席 | n5,F1,γ1；4份 `[A,B],[B,A],[A],[B]`。出现数3/3均solid；按D25票为2/2，τ2，确定性选一条边 | 当前符合；若只算双方出现则1/1无边，违反图性质。证明此前缺席计票是必要修复 |
| R2 版本变化 | n5,F1,γ1；旧图缺A-B，Update为`[A,B],[A,B],[],[]`。wAB2≥τ2但A出现2<solid3 | P21图2字面加边；P22/D25及当前不加。不能把旧版与新版混称同一规则 |
| R3 非整数γ | n6,F1,γ.9，4.8>4合法；5份`[A,B],[A,B],[B,A],[B,A],[]`。A/B各出现4均solid，w2/2，τ=ceil2.6=3 | 当前接受参数并保留两个无边solid；符合图1字面却不符合Lemma B.1。属于源规则整数化缺口；不是当前n20,γ1数据的归因 |
| R4 攻击进入但图不变 | n20,F4,γ1，16份完整三交易报告，c份`[C,B,A]`、16−c份`[A,B,C]`；c=0…4 | 每对正向≥12、反向≤4<τ5，图始终传递图、输出A,B,C。不能把“不降速”推成“没采用攻击者” |
| R5 partial、跨proposal与多余Update | n5,F1,γ1，A<B<Z<C按ID。第一轮`[A,B,Z],[B,A,Z],[Z],[Z]`：A/B shaded，Z solid；AB1/1无边，AZ/BZ平票2/2按ID指向Z。第二轮新图只有solid C | 第1、2轮均不释放。当前Update报A,B,Z,C，而图7缺边端点只有A,B。第三轮Update`[A,B],[B,A],[A],[]`给AB2/BA1且A出现3，补边后输出A,B,Z,C。证明连续前缀规则正确、多余Update是额外工作 |
| R6 过期但签名有效 | 在无deferred状态生成sequence2的List含A,B,Z,C，Update=nil；先提交R5第一轮partial proposal | sequence仍未消费、签名没变，却从合法变非法；按新状态生成List C＋Update A,B,Z可通过。拒绝是对的，周期报告缺上下文导致浪费需要单独处理 |
| R7 重复验签 | n5,F1；同4份签名List依次经过collector等价校验、build、hosting等价Verify | 共12次密码验签，build和Verify各重构一次；CommitVerified不再验签。量化重复工作，不删除follower必要验证 |

R3的整数数学原因：要从一对含solid节点的票数并集至少n−2F，推出至少一向达到整数τ，需要 `n−2F≥2τ−1`。原文实数前提 `n−2F>2[n(1−γ)+F]` 在非整数时未必推出这一点。当前主参数满足12≥9；本地n7,F1,γ.9满足5≥5；n10,F1,γ.95满足8≥5。没有证据把本例推广成这些配置也出错。也没有据此擅自降低阈值或提出“优化版算法”。

检查完成情况：

- 原仓库 `go test ./... -count=1` 通过；包括既有计票、分类、deferred、签名/图验证、Hamiltonian、取消/队列保护及micro fixture测试。没有运行性能扫参。
- 临时副本 `go test ./pkg/ofo -run TestIndependent -v -count=1`：7个审查测试通过。R3等测试的PASS表示成功复现所描述差异，**不是该性质符合论文引理**。
- `python -m unittest discover -s benchmark -p test_fabfile.py`：17个测试通过。测试打印的remote矩阵来自mock，不是AWS操作。
- 阅读并解析9份本地smoke日志；汇总见[existing-log-summary.json](D:/Work/go/workplace/code/SpeedFair_simplify/benchmark/review-20260913-independent/existing-log-summary.json)。旧micro产物的版本/dirty信息已核对，未拿其计时替当前基线背书。
- 未运行race检测、长时压力、真实共识或任意Byzantine行为实验；没有完整形式化证明。仅靠这些小例不能证明所有线程交错、网络故障及Hamiltonian大图均正确。

## 8. 已确认优化、必要修复、额外低效分别是什么

**应保留的必要正确性条件/修复：** 单方出现计票；完整未proposed List；不同sender去重与签名验证；P22 FairUpdate源出现条件；已有边不改向；真正的Hamiltonian排序和末solid边界；旧缺边proposal挡住新proposal；完成记录去重。对其中已经正确实现的部分，本次不声称它们都是最近新增的改动。

**已确认的额外性能优化：** 当前适配器缓存已经Verify的精确proposal，commit按digest应用而不再次完整Verify。这是工程去重；没有绕过首次验证，也没有改变排序结果。本次未发现并行化成对计票、SNARK、乐观先提交后审计、跳过真实Weight、增量图缓存、任意候选截断或提前输出纯solid前缀等算法加速路径。CutShadedTail的反向可达是等价实现选择，不能仅因写法不同称为“优化变体”。

**自主实现额外低效：** 邻接切片上的线性去重/查边/比较嵌套；重复tournament检查（commit先检查一次，ComputeFairOrder入口再查一次）；leader重复构图与验签；SCC邻接排序；全历史ID复制；每轮克隆未释放图；对已完整未释放图仍扫描FairUpdate；Update带多余顶点；周期性全pool排序/报告及过期批；单worker与同步fanout排队。替换数据结构并保持相同证据、相同图、相同输出，是实现效率修正；它会改变计时，修改后性能数据应重测。

**仅观测/实验保护：** F/b元数据、build和队列计数、实际输入率、截止时间、未完成计数、发送/验证失败、状态digest和队列满INVALID。它们有小量观测开销，可能改变失败运行何时终止，但不能据此推论有效运行采用了更强算法。不能为保旧数据删除有效性保护。

## 9. 截稿前取舍与150ms数据的研究价值

| 必须处理 | 可以暂缓 | 应保持不变 |
|---|---|---|
| 明确论文版本与排序层范围；纠正任何“完整共识/论文β”误标 | 若只比较排序层，真实HotStuff、PKI/状态机执行可以另开任务 | 当前n20,F4,γ1和显式b分离 |
| 按实际执行版本判定旧数据能否用于当前算法；受缺席计票修复影响的数据必须重测或降为历史结果 | 广泛多区、多节点/大负载全矩阵；先复核关键点 | 完整List、单方缺席计票、补边门槛、前缀释放、Hamiltonian边界 |
| 补“采用攻击者数+接收次序”的证据，或删除无法支持的攻击/公平性结论 | 复杂攻击、恶意leader、网络攻击；需独立范围与验证 | 当前reverse攻击可保留为一个明确定义场景，不应悄悄换更强攻击制造下降 |
| 同版本50/150敏感性复核；报告实际输入、积压、失败和完成样本范围 | 固定150ms的特定实现结果可先保留，不必宣称经过最优校准 | 不实施论文可选solid提前释放、SNARK或乐观审计，维持明确基线 |
| 若论文声称“算法本身导致低TPS”，先消除/隔离已确认额外成本；做不到就收窄结论 | 状态绑定调度改造可等profile证实其影响，不能无证据整体重构 | 正确性校验、失败运行保护，不用放宽它们追求更好曲线 |
| 通用γ结果需审查整数边界；仅γ1论文可披露后暂缓扩域 | 对其他γ域给完整离散证明/联系作者澄清 | 不擅自把ceil改floor并称其忠实原文 |

**可以保留的150ms配置设计：** 固定机器/节点/交易大小/输入率矩阵、F不变扫b、重复次数及既有部署设计仍有价值；150ms可以作为这个实现事先采用的报告周期场景。只有记录证明确为事先选择，才能称“预先固定”，不能事后补造150ms的理论最优性、论文推荐或通信预算依据。配置设计可保留，不等于其所有测量值仍代表当前代码。

**需要重新测量或核对的数据：**

1. 运行版本不明、dirty源码未存档，或使用旧“双方都出现才计票”实现的Themis点，不能合并进当前算法曲线。若存有完整采用证据，可离线确认哪些图/输出受影响；但重新计票会改变在线调度，离线重算无法恢复新版本TPS/延迟，性能仍需重跑受影响的比较。
2. 输入不足/失败/末态不一致、遗漏Outstanding的数据需按新口径重测或明确标为无效/非饱和；不能只换JSON中的算法标签。
3. 若修正邻接结构、历史扫描、leader重复计算或调度，受其影响的Themis性能点重测，不与旧版拼线。
4. AUTIG若源码、发生器、宿主和指标口径完全相同且原始记录完整，不必因Themis单方修改机械地全部重跑；跨日期环境或输入差异仍需配对复核。

**旧150ms数据允许支持的结论：**“所记录版本在该公共排序框架、硬件、单源输入、报告周期下的表现”；可作为历史实现、调度敏感性或工程迭代的证据。若核心修复前后的影响未排除，不可支持“忠实Themis的性能上限”“Themis相对AUTIG的固有劣势”“b增加必然/不会造成协议性能退化”“完整Byzantine安全与公平性已验证”。没有论文义务要求150ms胜过50ms，也没有理由为了保存旧数据而修改算法制造此趋势。

建议可直接用于论文的方法限定（仅在对应记录齐全后使用）：

> 我们依据Themis的2022修订版实现其排序层，并采用作者后续正文明确的接收顺序计票定义。两个排序层运行于共同的实验宿主；该宿主不实现HotStuff共识。Themis使用完整未proposed接收列表，150ms为本实现的报告周期而非论文proposal blocksize；我们通过50ms配置检查结论对周期的敏感性。吞吐为固定窗口内leader完成排序的交易数，延迟仅统计该窗口内完成的交易，并同时报告输入率、积压与失败运行。

这段话不能替代AUTIG路径审查，也不能消除当前单源攻击实验的限制。

## 10. 最小复核计划

以下是下一轮建议，不是本次已运行的网络实验；不需要先启动AWS或全矩阵扫描。

1. **冻结证据。** 将当前SHA、binary hash、机器/节点映射、完整命令、F/b/γ、interval和测量窗口写入run manifest；保留失败记录。先整理已有远程原始日志，按build版本分组，判断哪些150ms值仍可解释。
2. **最少增加观测。** 每成功proposal记高度、采用sender IDs、c、每sender List/Update长度、生成/接收/采用时刻或sequence+上下文、剪枝前后顶点数、边数、SCC大小、原始solid/shaded数、未释放图/交易数、补边数。把build_nil拆成无新工作/无solid/状态过期/重复sequence/取消。生产大负载只记聚合；小复核保存完整签名报告以供独立oracle。
3. **50/150定位：先两个配置。** 固定n20,F4,γ1,b0及同一输入，选一个既有差距最大的工作点；只做50/150各1次短配对诊断和有效CPU profile（数据文件非空、带SHA）。不据单次估置信区间。观察实际λ、List/图分布、阶段CPU/壁钟、队列、失败；根据实际热点决定是否修正额外成本。
4. **结论复核：最多12次关键网络运行。** 选择一个低负载和一个接近已观察差距的负载，50/150×2个负载×3次。预先说明warmup和窗口，例如先10秒预热，再固定30秒观测；保留窗口开始/结束计数，不把原60秒平均与新稳态口径直接混用。交错/随机运行顺序。若无法达到稳态，明确报瞬态和积压趋势，不能标最大容量。此步骤需新增窗口支持后执行。
5. **攻击效果先离线。** 用同一真实或可复现的接收时间矩阵，固定F4，扫b0…4；保存攻击前后报告、选中集合、Dist、图/SCC及输出。先比较c=0与c=b两个受控集合，只作诊断，不替换正式first-arrival选证策略。既记录同cycle变化，也检验相邻交易至少由论文要求数量的诚实节点按该顺序接收；batch公平性按原文cycle定义检验，不能直接把当前输出SCC当正确答案。
6. **在线攻击最少先测b0/b4。** 在有接收分歧的有限回放或多客户端场景下保持同λ和部署，比较选中c、图大小、SCC、deferred和阶段时间。如果确有结构差异再扩展b1…3和TPS统计；如果仍无差异，如实报告输入/攻击影响范围，不换攻击来强行制造下降。
7. **结束条件。** 对论文主体，至少做到：核心小例无新的不一致；每个结论有匹配版本、输入与口径；50/150关键比较可复核；b实验能够区分未入选与入选但无影响；已识别额外实现成本不再被写成论文不足。完整HotStuff复现另以共识安全、视图切换、持久化及客户端端到端指标验收。
