# 根据已有实现重新核对Themis调度与AUTIG比较

日期：2026-09-14。本轮只阅读源码与文献、下载公开参考源码，没有修改生产代码、启动AWS或运行性能扫描。本文修正此前仅从设计推导得出的调度建议。第三方C++实现未编译运行，相关结论是有效执行路径的静态审查，不冒充实测。

## 1. 结论的修正

已有实现能够支持“按交易数量触发Themis相关处理”，但本次没有找到可直接作为完整正确性参照的、同时具备真实完整List/Update、状态绑定、尾部推进和无进展处理的无周期实现。此前提出的“leader请求、单活动轮次、事件唤醒”仍是待验证的新工程设计，不是已经核实的作者或第三方实现路径。撤回把它直接列为当前推荐替换方案的建议。

这不证明事件驱动不可实现，也不证明必须保留150ms；它意味着不能为了去掉参数，未经验证就把自主设计称为已有Themis复现。保留现状只应作为停止扩大变量的临时措施，不是已经认可现有性能比较。

## 2. 参考实现与具体执行路径

### 2.1 作者公开快照

固定提交：`anonthemis/themis-src-anon@6b3aef8f0ea70ec939322baa61853f934e4e7fb2`。

[hotstuff.cpp:734](https://github.com/anonthemis/themis-src-anon/blob/6b3aef8f0ea70ec939322baa61853f934e4e7fb2/Aequitas-hotstuff/libhotstuff/src/hotstuff.cpp#L734)：只有leader将命令放入待提案缓冲，达到blk_size后取恰好blk_size笔；783–794以该批造相同replica列表；800调用排序计算；825以后经pacemaker进入on_propose。原真实列表来源、权重及若干更新计算被注释，详见主审查报告。

支持的结论：公开性能路径有数量聚批。不能支持的结论：它提供了完整在线Themis的无周期报告实现；或者把当前周期替换成它的blk_size即可忠实对齐。

### 2.2 Rashnu实验中的独立Themis实现

发现路径：[HeenaNagda/Order-Fairness](https://github.com/HeenaNagda/Order-Fairness/tree/3f8ac9e1713dcad244a44c7731982eb2747b122b)。根仓库明确将Themis_tx称为按论文独立实现的基线；不是Themis原作者实现。子模块与下载HEAD均为：

`HeenaNagda/Themis_tx@a4e5272de86c6d738a3d135e2416fb95c2eec56e`，2022-10-23。

| 事项 | 有效代码与结论 |
|---|---|
| 何时发报告 | [hotstuff.cpp:577–595](https://github.com/HeenaNagda/Themis_tx/blob/a4e5272de86c6d738a3d135e2416fb95c2eec56e/src/hotstuff.cpp#L577)：每个replica积累local_order_buffer，满blk_size后弹出该数量，调用on_local_order。 |
| 是否周期兜底 | [hotstuff.cpp:622](https://github.com/HeenaNagda/Themis_tx/blob/a4e5272de86c6d738a3d135e2416fb95c2eec56e/src/hotstuff.cpp#L622)：reorder_timer的初始化、回调和add全部注释；reset函数中add也注释。不能因为类里有TimerEvent成员就称它在运行。 |
| 是否完整未proposed列表 | [consensus.cpp:449–460](https://github.com/HeenaNagda/Themis_tx/blob/a4e5272de86c6d738a3d135e2416fb95c2eec56e/src/consensus.cpp#L449)：cmds直接取传入批；补入旧未proposed命令的两行被注释。缓冲中尚不足批量的接收交易也没有进入本次cmds。 |
| Update来源 | 同函数463行取missing-edge更新，481构造LocalOrder，490实际发送。更新是显式边列表，不能等同当前完整签名Update序列。 |
| 何时构图 | [hotstuff.cpp:312–329](https://github.com/HeenaNagda/Themis_tx/blob/a4e5272de86c6d738a3d135e2416fb95c2eec56e/src/hotstuff.cpp#L312)：实际收到不同replica报告并满足cache门槛后，执行fair_propose和fair_update，然后经pacemaker提出图。是真实多replica收集，不是作者复制列表的相同路径。 |
| 单方缺席 | [consensus.cpp:580](https://github.com/HeenaNagda/Themis_tx/blob/a4e5272de86c6d738a3d135e2416fb95c2eec56e/src/consensus.cpp#L580)：权重循环仅枚举同一列表中同时出现的两笔交易，没有当前按作者后续正文修正的单方出现票。 |
| CutShadedTail | 同文件615以后寻找截断点的循环遇到首个没有solid的SCC就停止；字面行为不是寻找最后一个含solid的SCC。此处仅说明不能直接当正确性oracle，未给此第三方实现做完整可达输入验证。 |
| 最终排序 | [consensus.cpp:248](https://github.com/HeenaNagda/Themis_tx/blob/a4e5272de86c6d738a3d135e2416fb95c2eec56e/src/consensus.cpp#L248)：tournament之后展开SCC中的元素，留有处理Condorcet cycles的TODO；没有当前实现的Hamiltonian构造与末solid规则。 |
| 公平性验证 | [entity.cpp:202](https://github.com/HeenaNagda/Themis_tx/blob/a4e5272de86c6d738a3d135e2416fb95c2eec56e/src/entity.cpp#L202)：Block::verify只检查QC；本次追踪的proposal接收链未见携带完整原始报告并重算FairPropose的验证路径。 |

因此，它是数量触发的实际先例，但不是可以整体替换当前Themis的合格完整参照。满批触发之外还有源码缺失，不能把这些路径带入新基线后称为忠实保留论文不足。

最小静态推导：blk_size=2，每个replica只收到1笔且不再到达新交易；启动路径不调用on_local_order，重报timer未启用。该路径不会仅因等待时间增长而发出报告。即使最终BFT提交还有其他等待条件，这个报告入口本身已经被满批门槛挡住。未运行C++，不报告具体等待时长或TPS。

### 2.3 其他查到的材料

[COB](https://github.com/yhzhang0128/cob/tree/bab4bc765aa4dd5cd4a15a4f5723ec76c9120c9d)的README明确Themis使用themis_sim.py和作者Python simulation函数；它不能给当前在线报告调度提供性能实现参照。

[SpeedyFair论文§V-A](https://www.ndss-symposium.org/wp-content/uploads/2024-693-paper.pdf)报告用共同Go HotStuff底座重实现Themis进行比较。本次查到的是论文说明与通用relab/hotstuff链接，未取得可追踪该Themis基线完整路径的固定提交。不把“文章说实现了”写成“已经独立审查其代码”，也不声称不存在未找到的公开代码。

公开[AUTIG v1](https://arxiv.org/html/2510.14186v1)也使用lo-size/lo-interval的共同实验设计；这是待审查比较自身的来源，不能循环用它证明Themis原文要求这些参数。本次不以其旧性能曲线约束当前代码必须出现相同趋势。

## 3. 本地AUTIG已经存在的实际差异

发现本地目录`D:/Work/go/workplace/code/utig`，origin为`https://github.com/lesserbug/AUTIG.git`，HEAD为`fd4b2576435ba84c0fe23da08616f452dd1c89c3`。工作树有README修改和未跟踪ordering实验文件。本轮未改变这些文件。该目录是现有候选AUTIG版本，尚待用户确认它是否就是历史远程实验使用的版本；不能用当前HEAD替旧运行背书。

| 比较项 | 此AUTIG工作树 | 当前Themis | 对比较的影响 |
|---|---|---|---|
| LO内容 | [service.go:183](D:/Work/go/workplace/code/utig/pkg/ofo/service.go:183)：receiptQueue前loMaxSize笔；有pending则重传原块；确认后消费自己的块 | 完整未proposed快照＋旧图Update | 相同数字不代表相同报告内容/证据历史；不得向Themis直接喂AUTIG截断报告冒充原生执行。 |
| 周期 | [main.go:271](D:/Work/go/workplace/code/utig/pkg/main.go:271)：ticker；[service.go:248](D:/Work/go/workplace/code/utig/pkg/ofo/service.go:248)：收集timer为2×interval，但timeout分支继续收集，不接受部分批或清空 | ticker触发报告；collector无该timer | 不能仅凭timeout变量推断AUTIG会丢弃慢报告。 |
| 选中sender | [service.go:291](D:/Work/go/workplace/code/utig/pkg/ofo/service.go:291)：按fragmentSeq轮换的预定n−F集合 | 先到的n−F个有效sender | 同b不保证同采用c；AUTIG选择逻辑本身在停发攻击下还需单独检查活性，本轮不将它判定为完整协议安全机制。 |
| 调度 | [service.go:262](D:/Work/go/workplace/code/utig/pkg/ofo/service.go:262)：凑齐后等待roundDone，期间排空重传；proposer等candidate.done | collector可排多批，proposer串行 | 不是“只有图算法不同”；不能将所有TPS差直接归因于增量维护。 |
| 攻击 | 反转fresh LO块；可选byzantine-lo-delay | 反转完整fresh List与Update，没有该delay行为 | 同名reverse仍有不同作用范围；LO大小在AUTIG中还改变攻击范围。 |
| 阈值 | [type.go:139](D:/Work/go/workplace/code/utig/pkg/types/type.go:139)：edge=n−ceil(γ(n−F))+1，solid=n−2F | edge=ceil(n(1−γ)+F+1)，solid=n−2F | n20,F4,γ1均为5与12，n−F均16；其他γ不可同值直接等价。数值相同不代替公平性前提核对。 |
| 证据语义 | [dependency.go:160](D:/Work/go/workplace/code/utig/pkg/ofo/dependency.go:160)：签名的位置链增量，复用已确认位置、每replica成对关系只计一次 | 当前proposal完整报告＋旧proposal补边 | 当前AUTIG不是简单把重复报告当新增票累加；不能用旧论文/旧实现描述替代代码。 |
| 宿主 | [auth_adapter.go:343](D:/Work/go/workplace/code/utig/pkg/auth_adapter.go:343)：固定leader，n−F验证ACK gate | 同级别gate | 提供公共排序层比较的基础；两者均不能称真实BFT提交。AUTIG宿主没有Themis那次额外leader Verify调用。 |
| 接收/验证成本 | AUTIG验证内容可用性、admission、位置链及结构证书 | Themis hash接收，完整图重算；无同等admission/Resolve路径 | 对齐外部职责，保留算法必要差异；不能单方面删必要验证追求对称。 |
| 指标 | leader固定截止前输出数，完成样本均值，提交量/未完成记录 | 同类口径 | 源码结构可对齐，但需实际运行manifest、窗口和参数一致才能拼表。 |

## 4. 对此前改造方案的判定

| 方案 | 判定 |
|---|---|
| 去掉无效lo_size | 可做接口清理；不改变当前Themis输出。 |
| 去ticker，只有满B发送 | 有Themis_tx先例；已有源码同时暴露尾部推进不足，不建议作为完整Themis替换。 |
| 采用leader pull＋事件＋父状态绑定＋重试 | 工程上可设计，核心图代码可复用；未获得本次参考实现的完整背书。必须独立验证，不应现在作为已确认建议。 |
| 固定β后复制相同replica排序 | 能复刻作者公开计算负载的部分行为；违反当前真实算法复现目标。 |
| 先保留周期，只补实际证据/图/工作量观测 | 改变量最少，有利于厘清现有50/150现象；仍需披露周期为本实现选择，不把150ms认定最佳值。 |

如未来实现新调度，最低验收应覆盖：单笔有限输入、B−1尾部、仅Update、新报告因提交失效、迟到replica、报告重传、无进展不忙循环、所有节点同已确认前缀、当前论文独立反例及公平性oracle。通过工程小例不是完整证明；故障模型和允许的重试仍应写清。当前没有执行这些新方案的测试，因为方案尚未实现。

## 5. 与AUTIG比较，不是改完就直接拼TPS

### 5.1 系统比较回答实际表现

在同级别宿主上各自按已声明的原生规则运行，使用相同规范交易字节/提交日程、n/F、硬件、客户端位置、测量窗口和业务职责。参数允许不同：AUTIG保留LO块上限与报告周期；Themis保留完整List及其已验证调度。公布有限候选集合、校准负载、选择目标，校准后冻结；不能每个b点重新选有利配置。

至少输出actual offered、finalized、outstanding、完成样本延迟、失败/拒绝、采用c、List/图/SCC分布。输入未饱和时只能报告该输入下表现，不能把TPS视为最大容量。相同输入种子不保证真实网络生成完全相同接收顺序；需保存实际trace或明确其随机性。攻击比较要区分原生chunk reverse与snapshot reverse，不能把不同攻击范围写成同一处理。

可以沿用两边启动程序，建议用一个共同run manifest驱动协议各自的参数翻译；不需要把内部消息/调度强制做成相同代码。Themis参数不存在时显式记N/A，不能继续把lo_size=200记成有效设置。按同一资源预算顺序/交错运行，避免并发抢同一机器。旧AUTIG结果仅在版本、环境和口径匹配后才能与新Themis比较，否则做配对重测。

### 5.2 机制比较回答差异来自哪里

本地AUTIG已有[ablation_benchmark_test.go:40](D:/Work/go/workplace/code/utig/pkg/ofo/ablation_benchmark_test.go:40)：GraphMaintenance的Incremental/Rebuild，以及FollowerVerification的Certificate/Recompute，并分Core/Full。它提供了在同一AUTIG语义和证据上隔离设计收益的现成入口；本轮只阅读，没有执行或认可其计时结果。

应先核对其独立正确性和计时边界，再用它支撑“增量维护/证书验证各节省多少工作”。其中Rebuild/Recompute仍是AUTIG语义的消融，不得改标签称Themis。

跨算法回放若进行，公共输入应为相同规范交易和replica接收历史，再按各自合法规则生成证据；不能共享同一截断wire报告、强迫两边输出同一批次或用一方的图当另一方的正确性oracle。此实验排除了原生报告调度，需与在线排序层性能分开呈现。

### 5.3 当前可执行的决策

暂不按上一轮自主pull设计改生产代码。先冻结并确认实际AUTIG版本，补双方实验契约和证据观测，保留Themis现有核心修复，用小量50/150对照与已有AUTIG消融定位差异。若仍决定改成数量/事件触发，先把它作为新调度版本验证并同旧Themis配对比较；验证后才进入AUTIG正式对照。删除参数不是达成可比性的充分条件。
