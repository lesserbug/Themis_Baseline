# Themis 本地计算微基准

本组结果只表示 **execution time and cumulative allocation per replay**。
`ns/op` 是每次重放的执行时间；`B/op`、`allocs/op` 来自 `testing.B.ReportAllocs()`，
表示累计分配，不是峰值 RSS、保留堆或协议状态大小。不能推导 finalized TPS 的同比变化。

本次只添加同包测试代码和标准库 Python 采集器，不修改生产算法、认证、阈值、排序、
提交或 AWS 部署。它是当前仓库实现的跨协议参考，不是 AUTIG 内部消融中的任一分支，
也不是对 Themis 论文所有能力的实现声明。未添加 AUTIG 的增量图、结构证书或 BlockForest。

## 审查到的实际生产路径

| 职责 | 文件 / 函数 | 本次测量的含义 |
|---|---|---|
| 程序入口、交易生成 | `pkg/main.go` | 本地/远程负载入口；不在操作计时内 |
| 传输 | `pkg/network/network.go` | 不测 TCP、广播、收集等待 |
| 接收和签发完整列表 | `pkg/ofo/service.go`: `handleMessage`, `generateAndSendOrders` | 检查交易内容哈希；按接收时间排序；生成签名 LocalOrder 和 UpdateOrder |
| 收集 | `validateReplicaOrders`, `runCollectorStage` | 验签、检查发送者和序号；收集 n-f 个不同副本并排序 |
| 构造 | `buildProposal`, `recomputeProposal` | 再检查 n-f 个不同发送者、认证和列表合法性，复制保留提案，排除已完成/已提案交易，完整构图及 FairUpdate |
| 图与排序 | `pkg/ofo/dependency.go` | `BuildGraphAndClassifyTxs`, `CutShadedTail`, `FairUpdate`, `IsTournament`, `ComputeFairOrder`, Tarjan SCC、凝聚图拓扑序和 Hamiltonian cycle |
| 原生验证 | `VerifyProposal` | 检查高度，验证签名 evidence，重构并核对新图、TxStates 和所有旧图更新 |
| 原生提交 | `CommitVerifiedProposal`, `commitVerifiedProposal`, `commitFinalizedData` | 复制并暂存旧图、应用边、安装新图；按高度处理完整 tournament，阻塞于首个不完整图；排序并提交、清理 |
| 编码/摘要 | `pkg/types/type.go` | LocalOrder、UpdateOrder、LeaderProposal 和摘要定义 |
| 测试认证和 hosting | `pkg/benchmark_adapter.go`, `pkg/ofo/service_test.go` | 确定性 Ed25519 密钥；执行真实 Ed25519 Sign/Verify 和 SHA-256 |
| 现有实验和测试 | `benchmark/fabfile.py`, `pkg/benchmark_test.go`, `pkg/ofo/*_test.go` | hosting/流量实验与回归测试；原有 `.pprof` 不用于新采集 |

新图的 presence 和 pair weights 与构图耦合。Blank/Shaded/Solid **确实已在本仓库定义**，
不是由 AUTIG 移植：presence 达到 edgeThreshold 后成为 nonblank，达到 n-2f 成为 solid；
`CutShadedTail` 保留能到达 solid SCC 的节点。主实验阈值不变。
构造候选并不执行最终 FairFinalize；最终排序在提交阶段执行。

跨轮保留的对象是未完成提案的图、TxStates、原始签名列表/更新引用，以及 committed IDs、
finalizedOrder、每副本已提交序号、接收池。没有累计位置矩阵或跨轮权重矩阵。
`FairUpdate` 为每个旧图扫描缺边对并计算本轮权重，原地安装发生在提交阶段。
`cloneProposal` 深复制 Graph 和 TxStates，但共享不可变 Proof/Updates；这项生产复制成本保留。

候选 `Proof` 是 n-f 个副本的完整签名输入，不是 SCC/结构证书，也不是 BFT quorum certificate。
`LeaderProposalDigest` 绑定高度、图、边更新、TxStates、发送者、序号和输入摘要/签名；
发送者集合和边表按规范排序，列表内交易顺序由 evidence 摘要绑定。
它**没有**绑定前驱摘要、参数/epoch、候选输出序列、输出批次、后状态或 leader 签名。
`CommittedContext` 绑定 finalizedOrder、保留提案摘要和提交序号，并分别返回高度/最近提案摘要；
不绑定接收池、累计延迟或单独的 committed-ID map。不能只比较这些摘要来断言全部状态一致。

`VerifyProposal` 是当前原生候选 verifier，绝不能称为满足 AUTIG 验证契约的完整输出 verifier。
它不执行 FairFinalize，也不检查候选中不存在的前后状态/顺序字段。
hosting adapter 检查消息类型及来源，计算候选摘要，缓存通过验证的候选；后续按高度/摘要提交。
消息来源检查不是密码学 leader 签名。`CommitVerifiedProposal` 是受信任的组合接口，
只能在对应候选已经通过验证后调用。微基准不会把直接调用它当成验证。

## 计时边界

| 名称 | 包含 | 排除 / 限制 |
|---|---|---|
| `GraphCore` | 新 DependencyManager 分配、原生 presence/weights、完整新图、剪枝及其 SCC；对所有旧图调用 FairUpdate | 已验输入的分离和 exclusion set 准备、旧提案复制、验签、候选摘要和提交；比 AUTIG graph-only Core 边界更宽 |
| `LeaderBuildFull` | 生产 `buildProposal` 全部工作：校验/验签、原生缓存复制、完整构图、旧图更新、原生 evidence 引用构造；非空候选摘要 | 从**已收集的签名列表**开始；不含列表生成/签名、collector 前一次验证/收集、hosting 的再次自验证、传输和最终提交排序。Full 指该构造函数完整边界，不是完整排序层 |
| `CandidateCheckCore` | 完整构图/剪枝/更新和原生 graph、TxStates、Updates 比较；一次构图复用 | 输入已通过公共检查；不重新构造 proof，不验签，不算摘要；**不是独立完整 verifier 或显式输出 verifier** |
| `FollowerVerifyFull` | 生产 `VerifyProposal` 全部工作：高度、签名证据合法性、复制、完整重构和字段比较；原生候选摘要计算 | 不含接收、adapter 的来源分支/缓存 map 写入、host 提交；无候选 leader 签名、显式输出、前后状态承诺可检查 |
| `CommitFinalizeFull` | 生产 `CommitVerifiedProposal`：暂存复制、应用图更新、tournament 门控、SCC/确定性完整排序、按高度批次释放、状态安装、摘要、序号和清理 | 已经验证的候选；不再次验证，不含 hosting 共识和传输。基准恢复旧服务状态在计时外 |

前两个 Full 不掩盖生产函数自己的复制或分配。原生 `VerifyProposal` 内部调用
`recomputeProposal` 会分配一个预期提案包装及 evidence 指针 slice；为了测量当前实现，
本次保留其成本。它不签发新 evidence。测试版 Core 不构造这些包装，
且没有“重算后再调用整个 verifier”的重复路径。这不是两种同边界算法，不能算 Core/Full 加速比。

AUTIG 的完整 leader 构造和 follower 验证包含显式输出/证书/后状态操作，不能直接用同名
Themis 阶段当作一一对应。FairFinalize 成本另列，以免漏掉排序；也不要把不同 replay 的
均值机械相加当作端到端延迟。若要改测整个 hosting adapter，需要另定义本地边界。

构造、Core 和 VerifyProposal 经快照/输入不变性测试后复用同一只读状态。
它们没有 pending 缓存或重复候选快速返回。提交每次复制恢复会被修改的服务字段；旧提案
是不可变输入，复用其引用，原生 staging 深复制仍在计时内。测试对比深复制快照与这种
恢复方式并检查源状态不变。样本生成、结构统计、差分断言、磁盘读取均在操作计时外。
每次结果只存于局部变量，用 `runtime.KeepAlive` 保活；没有跨迭代全局大图 sink、
手工 MemStats 差值或某一分支专属强制 GC。仍存在正常 GC 和缓存影响。

## 参数、接收上限和样本

默认 n=10/50、f=1、gamma_all=0.95 均通过生产 `ValidateThemisParameters`：
`n*(2*gamma_all-1)>4*f`；edgeThreshold 分别为 3 和 5，solidThreshold 分别为 8 和 48。
gamma_all 是 Themis 全副本语义，不能解释为 AUTIG 的 honest-replica gamma。
没有额外 gamma 扫描。正式配置应由最终主实验确定。

本实现 `lo_size` 仅为命令兼容保留，不截断完整 List_i；不存在与 AUTIG 相同的每轮增量
LocalOrder 上限。因此新脚本**没有** `--lo-size`。
`--receipt-cap` 默认 200，仅是测试工作负载每副本每轮新增**投递事件**数的上限，包含迟到投递。
预热和测量均检查，超过立即失败，绝不截断列表或增大上限。
LocalOrder 和 UpdateOrder 仍携带该副本全部适用接收历史，实际长度可以大于 200。
尤其较大的 UpdateOrder 不能被解释成违反了某个不存在的 Themis 增量消息阈值。
降低 receipt-cap 后，历史通过更多完整提交轮积累。释放轮的缺失旧交易投递也计入上限，
例如 low_release 实际需要 97，而不只是 fresh=96；cap=96 明确失败。

所有样本从 3 笔真实非空提交及池清理开始。通过 n-f 个逻辑副本的生产交易 admission、
完整列表生成/签名、构造、验证和 CommitVerifiedProposal 形成预提交快照；不手拼内部图或
跳过清理。测试将 admission 后的墙钟时间替换为严格递增逻辑时间，固定接收次序，避免睡眠。
这是受控合成近似样本，**不是 AWS 实测 trace 回放**。

| 场景 | 实际结构及计时外约束 |
|---|---|
| `low_release` | 保留恰好 12 笔 + 96 fresh；补齐第一批缺失接收，断言输出 108 且清空保留状态。低积压近似，不声称完全代表正常轨迹 |
| `small_fresh`（可选） | 恰好 24 保留 + 192 fresh；第一批缺边阻塞，fresh 合法提交到保留队列，输出为零 |
| `history_few` | M=`--history`（默认 480）保留 + 8 fresh，断言阻塞和 M+8 后保留 |
| `history_many` | 同 M + 128 fresh，断言阻塞和 M+128 后保留 |
| `no_receipts` | 同 M，无新投递；完整 UpdateOrder 仍被扫描，缺边保持，构造返回 nil；验证/提交 N/A，不报零耗时 |
| `late_completed`（可选） | 再投递开头已完成的 3 笔，admission 忽略；有效新增为零、无候选；验证/提交 N/A |
| `cycle` | 96 fresh，三组块旋转接收顺序；断言新图最大 SCC=96、输出=96，无保留。不是任意小环，也不冒称 AUTIG 的保留/部分释放 SCC |

阻塞由首个图中一对共同出现、但两个方向都未达到建边门槛的 shaded 交易产生；
通过指向 solid 节点的路径保留。单方出现计票仍然启用。后面的完整图即使可排序也必须等待。
若其他合法 n/f/gamma 不能形成预期结构，断言失败，不强造图。
新增固定配置机制实验及独立推导见 [THEMIS_MECHANISM.md](THEMIS_MECHANISM.md)。

交易 canonical bytes：前 8 字节 big-endian seed、再 8 字节递增 serial，剩余第 j 字节为
`(31*j + serial + seed) mod 256`；ID 使用生产 `TransactionID`。
顺序按场景定义，固定处理副本 0..n-f-1；其余 f 个副本不提供本轮 evidence。
每个样本附 receipt trace digest、workload version 和所有配置。共同 seed/大小只是对齐的
必要条件，**尚未证明与另一仓库的生成器产生相同字节或轨迹**。跨协议应显式共享这一定义
或导入同一轨迹，核对实际事件和阶段边界；不能按 benchmark 名称自动配对。

## 指标定义

manifest 的 `metrics` 记录以下实际值；计数零值显式记录，能力 N/A 用顶层 null 表示。

- `retained_txs` 定义 M：被测前未完成提案的有效节点数；`completed_txs`、`post_retained_txs`、
  `deferred_batches`、`pool_entries`、`sequence_entries` 分别反映已完成/后状态/缓存规模。
- `receipt_cap`、`warmup_rounds`、`warmup_max_receipts`、`measured_max_receipts`、
  `warmup_max_local_order`、`measured_max_local_order`、`warmup_max_update_order`、
  `measured_max_update_order` 区分新增投递和完整消息长度。
  顶层 `native_lo_limit=null` 表示没有这种协议参数。
- `effective_new_receipt_events` 是本轮成功接收的新 (replica,tx) 事件；`fresh_txs` 是新创建交易量；
  `effective_new_txs` 是排除已完成/已提案后 LocalOrder 中的不同交易量。
- `local_evidence_occurrences`、`update_evidence_occurrences` 为本轮证据出现次数，
  `effective_local_occurrences` 排除已完成/已提案交易。没有累计有效位置状态可映射。
- `evidence_touched_txs` 是有效新列表和 UpdateOrder 的不同交易并集，定义为**证据涉及范围**；
  它不是 AUTIG refresh 的实际 touched set，**本结果不定义跨协议 k**。
  即使无新增接收，该值和 FairUpdate 扫描成本仍可很大。
- `retained_graph_*`、`new_graph_*` 分别统计有效 nodes、edges、sccs、nontrivial_sccs、max_scc。
  最大 SCC 在每个原生图内计算，绝不将不同高度图拼成一个 SCC。
- `new_weight_entries` 为本轮新图构造时非零权重项（含剪枝前计算），`added_update_edges` 为
  本轮实际补边数。旧图更新内部临时权重矩阵未暴露，不能由新图权重数代替；持久权重 N/A。
- `blocked_missing_pairs` 是保留图中无任一方向边的无序对数；`output_txs`、`output_batches`
  为实际 FairFinalize 提交的交易/高度批次数，而非候选携带的显式输出。
- `proof_signatures`、`proof_signature_bytes` 和 evidence 出现次数记录原生证明组成，
  不声称是具体传输编码总字节数。`cached_state_entries`、`cached_proof_entries` 记录保留缓存；
  proof 引用通常共享，不应将引用计数解释为唯一 heap 对象数。

无 BlockForest、forest roots/depth 或 AUTIG excluded_solid 对应项，保持 null。

## 正确性、拒绝及已知验证缺口

新增 Core 在计时前与生产构造、原生 VerifyProposal 差分：比较有效图、TxStates、更新、
原生 proof 和规范摘要；比较完整输出顺序及批次、实际提交的保留图/提交 ID/序号/接收缓存。
提交后再推进一轮确认缓存可用，检查原始快照/输入未修改。计时前断言实际历史、SCC、
阻塞、释放和非空输出结构。固定 seed 1/7/19 的复现测试独立于计时。

拒绝测试包括：错误高度、发送者上下文/序号、重复/缺少发送者、坏 LocalOrder/UpdateOrder
签名、重复列表交易、缺少 UpdateOrder、外来/已提案输入、不一致的已签名顺序、
遗漏/加入节点、反向边、TxStates、缺失更新边、未知更新高度。
证据内部篡改按需重新签名；图/分类/更新篡改额外确认公共输入检查通过并对比 Core 拒绝结果。
正确图搭配坏 evidence 签名仍拒绝。证明发送者排列及邻接顺序的不同合法表示均接受。
无效候选通过 `VerifyProposal`/`CommitProposal` 后不得改变服务状态；这些接口没有 pending map。
adapter 的网络来源检查和 pending 缓存不在同包微基准范围，继承现有 hosting 测试。

不存在的候选前驱/后状态字段、显式输出顺序/批次/SCC 证书无法做篡改测试，标 N/A。
本次没有降低 native verifier 的要求，也没有新增测试版“更完整”协议。
另有边界回归测试明确展示：仅篡改已完成前缀、保持图/序号一致，原生 VerifyProposal
不能检测；不得据此宣称已有前状态绑定。任意签名合法的接收列表是否忠实报告网络接收，
也不是该 verifier 能独立证明的性质。

## 运行和交付文件

在仓库根目录运行，本地 PowerShell：

```powershell
$env:GOMAXPROCS='1'
go test ./... -count=1
python -m unittest discover -s benchmark -p 'test_*.py'
go test ./pkg/ofo -run '^$' -bench '^BenchmarkThemisLocal$' -benchmem -benchtime=1x -count=2 -args -micro-history=24 '-micro-scenarios=low_release,cycle,no_receipts'
python benchmark/run_microbench.py --nodes 10 --seeds 1 --history 24 --scenarios low_release,cycle,no_receipts --processes 2 --count 2 --benchtime 1x --out benchmark/micro-results/smoke
```

单台与最终主实验一致的 m5.xlarge 上运行（不部署通信副本，不调用 fab/AWS）：

```sh
python3 benchmark/run_microbench.py --nodes 10 50 --faults 1 --gamma 0.95 \
  --seeds 1 7 19 --history 480 --receipt-cap 200 --tx-size 512 \
  --processes 4 --count 1 --benchtime 1s --expected-go go1.22.12 \
  --out benchmark/micro-results/formal-v1
```

`go1.22.12` 来自现有主实验脚本，正式运行应替换为最终主实验使用的精确版本。
脚本校验版本（指定时）、固定 GOMAXPROCS=1、顺序运行 collector 自测、Go 全部测试、
每个所选 n/seed 的精确样本差分，全部通过后才开始测量。目录必须新建以防覆盖旧结果。
输出 `environment.json`、全部命令/日志、每组 sample JSON、原始 Go benchmark 日志、
`measurements.csv`、`summary.json`。记录 commit/dirty、Go env、CPU、OS、GOMAXPROCS、
GC 配置、版本/参数、seed、独立 process、process 内 repeat 和每次 b.N iterations。
另记录所有 Go/Python 源文件和 go.mod 的 SHA-256，便于区分 dirty 工作树产生的数据。
失败保留日志和 failed 状态；不将缺失或重复计时误当有效数据。

`summary.json` 按 seed/场景/阶段分别报告绝对时间范围和进程均值 CV；不输出任何跨协议或
Core/Full ratio。Themis 无 A/B 分支，无需 AB/BA。单次 `1x` 只能冒烟，不能用于性能结论；
`1s` 也不保证统计精度，应检查独立进程波动。不要同时运行其他 benchmark。
GOMAXPROCS=1 不是 CPU affinity，不能把其绝对耗时当作主实验默认并行配置的延迟。

workload 版本为 `themis-receipts-v1`。正式数据应在可复现的已提交版本重新采集；没有
dirty-tree 强制拒绝。不可混用 AUTIG 更改输入上限前后的旧/新数据，也不可只因 n 相同就
关联两种协议的结果。区分“相同接收工作负载”与“按实际 M、图/证据规模解释成本”。
低积压、状态规模和图结构样本的输出/积压可以不同，无跨协议后状态等价断言。

新增文件：`micro_helpers_test.go`（合法样本、准备/Core、快照与结构统计）、
`micro_test.go`（差分/拒绝/复现/上限与缺口测试）、`micro_benchmark_test.go`（五项计时、
配置与 manifest）、`run_microbench.py`、`test_run_microbench.py` 和本文；README 仅加入口。

## 本地验证记录（2026-09-10）

- Windows 11 / Ryzen 7 7840HS / Go 1.24.5；这是开发检查环境，不是主实验 m5.xlarge。
- `go test ./... -count=1` 通过，采集器在最终两次采集前均重新执行。
- 新旧 Python 测试共 14 项通过；旧 fabfile 测试的已有依赖安装于系统临时目录下的隔离 venv，
  没有改动 requirements 或运行部署。新增采集器自身不依赖这些库。
- `check-smoke`：n=10，小历史，两个进程 × 两次 `1x`，用于早期流程检查。
- `check-timed-final`：当前代码，n=10 / seed=7 / history=24，cycle 与 no_receipts，
  两个独立进程、每项 `1s`；进程均值 CV 约 4%–14%，不作正式性能结论。
- `check-large-final`：当前代码，n=50 / seed=19 / history=480，history_few/history_many，
  一个进程 × 两次 `1x`，用于结构及分配统计冒烟；实际预热 5 轮、每轮最多 200 个新增投递。
- 日志位于 `benchmark/micro-results/` 对应目录。final 两组采集记录的源文件 SHA-256
  已核对当前代码一致。未运行 EC2 正式采集或核验另一仓库的同轨迹输入，也未测 Go 1.22.12。
