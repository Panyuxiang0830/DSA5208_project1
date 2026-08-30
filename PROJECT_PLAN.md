# DSA5208 Project 1：MongoDB 客户端中心一致性实验计划

## 1. 项目信息

- 课程：DSA5208 Scalable Distributed Computing for Data Science
- 截止日期：2026-09-27
- 小组人数：不超过 3 人
- 计划数据库：MongoDB Community（最终固定到明确的 `8.0.x` 镜像版本与镜像摘要）
- 计划部署：一台 Google Cloud Ubuntu VM 上的 3 个 Docker 容器
- 客户端与实验工具：Python、PyMongo、Docker Compose
- 当前状态：计划阶段

> 本计划是执行基线。数据库、驱动、操作系统和 Docker 的精确版本将在首次成功部署后记录并锁定。

## 2. 项目目标

本项目搭建一个三数据节点 MongoDB Replica Set，通过改变读写关注级别、读偏好与客户端会话设置，研究应用程序实际观察到的以下四种客户端中心一致性：

1. **Read-your-writes（读己之写，RYW）**：客户端后续读取能够看到自己之前完成的写入。
2. **Monotonic reads（单调读，MR）**：同一客户端后续读取不会退回到更旧的数据版本。
3. **Monotonic writes（单调写，MW）**：同一客户端的写入按照其逻辑先后顺序生效。
4. **Writes-follow-reads（写随读，WFR）**：客户端读取某版本后产生的写入建立在该版本或更新版本之上。

项目不仅判断一致性是否被违反，还将同时记录延迟、错误率、可用性和故障恢复时间，以展示一致性与可用性之间的权衡。

## 3. 范围与非目标

### 3.1 范围

- 三个数据承载节点组成的 MongoDB Replica Set（Primary-Secondary-Secondary）。
- 正常运行、单节点故障、Primary 故障与网络分区。
- 至少三组一致性配置。
- 四种客户端中心一致性的可重复自动化实验。
- 原始日志、汇总 CSV/JSON、图表和最终 PDF 报告。

### 3.2 非目标

- 不搭建生产级跨区域 MongoDB。
- 不把 MongoDB 端口直接暴露到公网。
- 不把 Vanda/Atlas8 作为主要部署平台，因为共享 HPC 不适合长期数据库服务、Docker 管理和人为网络分区。
- 不将请求失败自动判定为一致性违反；失败、超时与返回旧值分别统计。

## 4. 部署架构

```text
研究人员的电脑
    |
    | SSH
    v
Google Cloud Ubuntu VM
    |
    +-- Docker 私有网络: mongo-net
    |     +-- mongo1 (Replica Set member)
    |     +-- mongo2 (Replica Set member)
    |     +-- mongo3 (Replica Set member)
    |
    +-- Python experiment runner
          +-- configuration selector
          +-- workload generator
          +-- fault controller
          +-- structured result logger
```

### 4.1 基础设施原则

- 使用单 VM、多容器方案降低费用和复现难度；课程要求明确允许该部署方式。
- 为三个 MongoDB 节点分别使用 named volume，避免容器重启导致数据丢失。
- 数据库端口仅对 Docker 私有网络或 SSH 隧道开放。
- Google Cloud 设置预算提醒；不做实验时停止 VM。
- 报告中明确说明：单 VM 的容器共享宿主机、磁盘和物理网络，不能完整模拟多台物理服务器的独立故障域。

## 5. 软件与版本管理

计划使用：

- Ubuntu LTS（记录具体镜像版本）
- Docker Engine 与 Docker Compose v2
- MongoDB Community 8.0.x
- Python 3.x
- PyMongo（在 `requirements.txt` 中固定版本）

首次部署后执行并保存以下信息：

```bash
docker version
docker compose version
docker image inspect mongo:<version>
python3 --version
python3 -m pip show pymongo
```

## 6. 待研究的一致性配置

| 配置编号 | Session | Write concern | Read concern | Read preference | 目的与初步预期 |
|---|---|---|---|---|---|
| C1 强基线 | 同一因果会话 | `majority` | `majority` | `primary` | 预期四类会话保证均成立；故障时可能牺牲可用性或增加延迟 |
| C2 跨副本因果读取 | 同一因果会话 | `majority` | `majority` | `secondary` / `secondaryPreferred` | 验证因果会话能否在读取 Secondary 时维持客户端一致性 |
| C3 弱配置 | 无因果会话 | `w: 1` | `local` | `secondaryPreferred` / 定向 Secondary | 更容易观察旧读、非单调读以及故障后的异常 |
| C4 对照配置 | 无因果会话 | `majority` | `majority` | `primary` | 分离“多数派读写”与“因果会话”各自的影响 |

注意事项：

- 每次操作显式记录最终生效的配置，不依赖隐式默认值。
- 在因果会话中，读操作使用 `majority`、写操作使用 `majority`，以满足 MongoDB 文档对因果一致性保证的前提。
- Replica Set 使用三个数据节点而不是 arbiter，避免将数据持久性问题与仲裁节点行为混合。
- 是否保留 C4 将根据试运行结果和总实验量决定，但 C1、C2、C3 为最低配置集。

## 7. 数据模型与可观测性

核心文档示例：

```json
{
  "_id": "experiment-key-1",
  "value": "payload",
  "version": 17,
  "writer_id": "client-1",
  "parent_version": 16,
  "operation_id": "uuid",
  "updated_at": "client timestamp"
}
```

每次操作至少记录：

- run ID、scenario ID、configuration ID；
- logical client ID、session ID、thread ID；
- operation ID、操作类型与客户端序号；
- 读到/写入的版本和 `parent_version`；
- 操作开始、确认和结束时间；
- 成功、超时、异常或重试结果；
- MongoDB 返回的错误类型；
- 尽可能记录实际服务节点；
- 故障注入与恢复的时间点。

一致性判断以逻辑版本、操作先后关系和确认结果为基础，不仅依赖不同机器之间可能有偏差的墙上时钟。

## 8. 四类一致性实验设计

### 8.1 Read-your-writes（RYW）

单个逻辑客户端写入递增版本 `v+1`，等待数据库确认后立即读取相同键。如果读取版本小于该客户端已确认的写入版本，则记为 RYW 违反。

### 8.2 Monotonic reads（MR）

后台写入器持续增加版本；逻辑客户端在可能不同的副本上连续读取。如果第 `i+1` 次读取版本小于第 `i` 次读取版本，则记为 MR 违反。

### 8.3 Monotonic writes（MW）

同一逻辑客户端按照序号连续写入，并使用操作日志或版本条件更新验证写入顺序。若后继写入在其前驱写入之前生效，或数据库最终状态反映逆序，则记为 MW 违反。

MongoDB Replica Set 的写入由 Primary 处理，本实验预期 MW 较难被违反。实验仍将保留，用来验证数据库机制与客户端重试/并发设置是否符合预期。

### 8.4 Writes-follow-reads（WFR）

客户端先读取版本 `v`，随后提交带有 `parent_version=v` 的派生写入。通过条件更新和操作日志检查写入是否建立在读取到的版本或更新版本上。若写入建立在更旧状态，则记为 WFR 违反。

### 8.5 重复次数与统计指标

- 每个“配置 × 场景 × 一致性模型”组合先试运行 20 次。
- 正式实验目标为至少 500 次操作序列；若违反事件稀少，将增加到 1,000 次以上。
- 使用固定随机种子，并至少使用三个不同种子复核。
- 汇总 violation count/rate、成功率、超时率、p50/p95/p99 延迟和恢复时间。
- 保存所有原始结果，汇总脚本不得覆盖原始日志。

## 9. 场景与故障注入

| 场景 | 操作 | 主要观察点 |
|---|---|---|
| S0 正常运行 | 三节点和网络正常 | 建立一致性与延迟基线 |
| S1 Secondary 故障 | 停止一个 Secondary 容器 | `majority` 是否仍可用、Secondary 读取如何退化 |
| S2 Primary 故障 | 停止当前 Primary | 选举时间、重试行为、短期不可用和一致性结果 |
| S3 Primary 与多数派分区 | 隔离当前 Primary 与两个 Secondary | 原 Primary 降级、多数派重新选举、读写行为 |
| S4 单个 Secondary 网络延迟/分区 | 限制客户端或复制流量 | 放大复制滞后，观察弱配置下的旧读和 MR 违反 |
| S5 节点恢复 | 恢复网络或容器 | 数据追赶时间、恢复后的读取和可能的回滚 |

故障控制脚本必须：

1. 在注入前记录 Replica Set 状态；
2. 确认目标节点角色，避免依赖固定的 Primary 名称；
3. 记录故障发生和恢复时间；
4. 在下一轮前验证三节点健康；
5. 提供幂等的恢复命令，避免残留网络规则污染后续实验。

网络分区优先通过受控的 Docker 网络操作或容器内网络规则实现。具体方法将在小规模验证后固定，并记录所需权限和恢复步骤。

## 10. 初步预测

| 配置 | RYW | MR | MW | WFR | 主要代价 |
|---|---|---|---|---|---|
| C1 因果会话 + majority + primary | 预期成立 | 预期成立 | 预期成立 | 预期成立 | 故障时延迟升高或请求失败 |
| C2 因果会话 + majority + secondary | 预期成立 | 预期成立 | 预期成立 | 预期成立 | Secondary 可能等待因果依赖，延迟增加 |
| C3 无会话 + `w:1` + `local` + secondary | 可能违反 | 可能违反 | 预期通常成立 | 可能违反 | 可用性和低延迟较好，但可能返回旧状态 |
| C4 无会话 + majority + primary | 预期多数情况下成立 | 预期多数情况下成立 | 预期成立 | 需要实验验证 | 不能把多数派确认直接等同于完整的客户端因果会话 |

最终报告将把“实验前预测”和“实际观察”分开，避免根据结果倒推预测。

## 11. 实验流程

每轮实验遵循相同流程：

1. 检查三个节点和 Primary 状态。
2. 清理或使用新的 run ID 隔离实验数据。
3. 设置确定的客户端配置和随机种子。
4. 启动工作负载并保存基线状态。
5. 在预定时间注入故障。
6. 持续执行操作并记录成功、失败、延迟和版本。
7. 恢复节点或网络。
8. 等待 Replica Set 恢复健康并记录恢复时间。
9. 执行一致性判定与汇总脚本。
10. 保存环境元数据、原始日志和汇总结果。

## 12. 仓库规划

```text
DSA5208_project1/
├── PROJECT_PLAN.md
├── README.md
├── compose.yaml
├── .env.example
├── config/
│   └── mongodb/
├── scripts/
│   ├── init_replica_set.sh
│   ├── cluster_status.sh
│   ├── stop_node.sh
│   ├── restore_cluster.sh
│   ├── partition_network.sh
│   └── heal_network.sh
├── experiments/
│   ├── common/
│   ├── read_your_writes.py
│   ├── monotonic_reads.py
│   ├── monotonic_writes.py
│   └── writes_follow_reads.py
├── analysis/
│   └── summarize_results.py
├── results/
│   ├── raw/
│   ├── summary/
│   └── figures/
├── requirements.txt
└── report/
    ├── report_source.*
    └── references.*
```

敏感信息、私钥、Google Cloud 凭据、真实 `.env` 和体积过大的原始数据不得提交到 Git。

## 13. 分工建议

若为三人小组，可按以下方式分工，但关键实验需要交叉复核：

- 成员 A：云环境、Docker Compose、Replica Set 和故障注入。
- 成员 B：一致性实验客户端、结构化日志和自动化运行器。
- 成员 C：结果分析、图表、文献整理和报告整合。

所有成员共同完成：实验预测、异常结果解释、复现测试和最终校对。

## 14. 时间计划

| 日期 | 里程碑 | 完成标准 |
|---|---|---|
| 08-30 至 09-03 | 方案和仓库基线 | 计划、README、目录和依赖方案确定 |
| 09-04 至 09-08 | 基础部署 | 三节点 Replica Set 可重复启动、停止和重建 |
| 09-09 至 09-13 | 正常场景实验 | 四个实验脚本可运行并生成结构化结果 |
| 09-14 至 09-18 | 故障与网络分区 | S1-S5 可重复注入和恢复 |
| 09-19 至 09-22 | 正式实验 | 完成配置矩阵，冻结原始数据 |
| 09-23 至 09-25 | 分析与报告 | 图表、解释、局限性和引用完成 |
| 09-26 | 独立复现与最终检查 | 从干净环境按 README 复现主实验 |
| 09-27 | 提交 | PDF、代码、脚本和复现说明上传 Canvas |

## 15. 成本与资源控制

- 在 Google Cloud Billing 中确认课程教育额度和到期日。
- 设置预算提醒，例如 US$25、US$40 和 US$48。
- 先使用足以运行三个容器的小规格 VM；正式压力实验前再评估是否临时扩容。
- 无人使用时停止 VM；同时注意持久磁盘在 VM 停止后仍可能计费。
- 每次实验记录 VM 规格、区域和运行时间，报告中注明云环境差异。

## 16. 风险与缓解措施

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 单机资源不足 | 容器被 OOM、延迟数据失真 | 限制容器资源、先做小规模测试、必要时短期扩容 |
| 弱配置下仍观察不到违反 | 无法验证预测 | 增加重复次数、定向读取 Secondary、受控增加复制延迟 |
| 故障后环境未恢复 | 后续数据不可比较 | 所有故障脚本配套恢复和健康检查 |
| 驱动自动重试掩盖行为 | 错误分类不准确 | 显式记录并分别测试 `retryWrites` 等设置 |
| 网络分区操作影响 SSH | 失去 VM 控制 | 仅操作 Docker 网络，保留宿主机 SSH 通路 |
| 教育额度耗尽 | 无法继续实验 | 预算提醒、停止闲置 VM、本地 Docker 作为备用环境 |
| 单 VM 不是真实多机 | 外部效度受限 | 在报告中明确故障域限制；有余量时补充多 VM 验证 |

## 17. 完成标准

项目完成需同时满足：

- 可从干净环境按 README 建立三节点 Replica Set。
- 至少三种一致性配置均有明确预测和实验结果。
- 四种客户端一致性均有自动判定逻辑。
- 正常、节点故障和网络分区场景均有可重复实验。
- 原始数据、汇总结果和报告图表可以追溯到具体 run ID。
- 恢复脚本能把环境还原到健康状态。
- 报告说明观察是否符合预期，并讨论失败请求与一致性违反的区别。
- PDF、代码、脚本和简明复现说明齐全。
- 数据库文档、其他资料和 AI 使用均得到披露与引用。

## 18. 计划引用资料

后续报告至少引用以下官方资料，并记录访问日期：

1. [MongoDB: Replica Set Read and Write Semantics](https://www.mongodb.com/docs/manual/applications/replication/)
2. [MongoDB: Read Concern](https://www.mongodb.com/docs/manual/reference/read-concern/)
3. [MongoDB: Write Concern](https://www.mongodb.com/docs/manual/reference/write-concern/)
4. [MongoDB: Read Isolation, Consistency, and Recency](https://www.mongodb.com/docs/manual/core/read-isolation-consistency-recency/)
5. [MongoDB: Distributed Queries and Read Preference](https://www.mongodb.com/docs/manual/core/distributed-queries/)
6. [MongoDB: Replica Set Configuration](https://www.mongodb.com/docs/manual/reference/replica-configuration/)
7. [Docker Compose documentation](https://docs.docker.com/compose/)
8. [Google Cloud Billing documentation](https://docs.cloud.google.com/billing/docs/)

## 19. AI 使用说明草案

本项目将披露生成式 AI 的辅助范围，例如：概念解释、计划整理、脚本初稿、代码审查和文字润色。小组成员负责验证所有命令、代码、实验设计、结果与引用；实验数据和结论不得由 AI 虚构。最终报告将按课程要求描述所使用的 AI 工具、用途和人工复核方式。

## 20. 后续实验扩展计划（暂不改变当前基线）

本节记录完成基础部署与现有 C1-C4 实验后可考虑的扩展。当前阶段不据此修改核心实验设计，以避免在部署完成前扩大实验矩阵。

### 20.1 配置参数归类

后续分析中需要保持以下概念边界：

- `causalConsistency=true/false` 属于客户端 Session 配置；
- `{w: 1}` 与 `{w: "majority"}` 属于 Write concern；
- `"local"`、`"majority"` 与 `"linearizable"` 属于 Read concern；
- `primary`、`secondary` 与 `secondaryPreferred` 属于 Read preference。

因此，`local` 和 `linearizable` 不应作为新的独立配置列，而应作为 Read concern 的不同取值。

### 20.2 四种客户端一致性的关系

四种客户端一致性是并列且相对独立的会话保证，分别覆盖同一逻辑客户端相邻操作的四种类型：

| 前序操作 | 后续操作 | 对应的客户端一致性 |
|---|---|---|
| Write | Read | Read-your-writes |
| Read | Read | Monotonic reads |
| Write | Write | Monotonic writes |
| Read | Write | Writes-follow-reads |

单独满足其中一种不会自动推出其余三种。因果一致会话在满足相应读写条件时可以同时提供四种保证；线性一致性属于更强的、要求真实时间顺序的数据中心一致性模型，不能与任意一个单独的客户端保证简单等同。

### 20.3 MongoDB 官方 2x2 Concern 矩阵

在因果一致会话中，MongoDB 官方文档给出的可持久因果保证如下：

| Read concern | Write concern | RYW | MR | MW | WFR |
|---|---|---|---|---|---|
| `majority` | `majority` | 保证 | 保证 | 保证 | 保证 |
| `majority` | `w: 1` | 不保证 | 保证 | 不保证 | 保证 |
| `local` | `majority` | 不保证 | 不保证 | 保证 | 不保证 |
| `local` | `w: 1` | 不保证 | 不保证 | 不保证 | 不保证 |

表中的“不保证”表示系统允许出现违反，而不是每次运行都必然违反。网络分区、Primary 切换、Secondary 复制滞后和大量重复操作可用于提高观察到违反的概率。

完成 C1-C4 后，可以考虑把该 2x2 矩阵作为第二阶段的受控实验：保持因果 Session 与 Read preference 不变，只改变 Read concern 和 Write concern，从而减少混杂变量。

### 20.4 可选的 Session 对照

后续可增加一组与因果会话配置仅相差 Session 开关的对照：

| Session | Write concern | Read concern | Read preference | 目的 |
|---|---|---|---|---|
| 因果会话 | `majority` | `majority` | `secondary` | 跨副本因果读取 |
| 无因果会话 | `majority` | `majority` | `secondary` | 分离因果 Session 本身的影响 |

两组配置应保持其他参数、工作负载、随机种子与故障时间线一致。

### 20.5 可选的 Linearizable 强对照

`readConcern: "linearizable"` 与 `writeConcern: "majority"` 可作为额外的强一致性对照，但不纳入当前核心矩阵。候选配置为：

```text
causalConsistency: false
writeConcern: majority
readConcern: linearizable
readPreference: primary
maxTimeMS: 5000
```

该配置需遵守以下限制：

- Linearizable read concern 只能读取 Primary；
- 不能用于 causally consistent session；
- 实验应按唯一键（例如 `_id`）读取单个文档；
- 应设置 `maxTimeMS`，避免多数数据节点不可用时无限等待；
- 它可能显著慢于 `local` 或 `majority`，因此应同时比较延迟和错误率。

Linearizable 对照的目的不是替换四种客户端一致性实验，而是展示更强的数据中心一致性在延迟和故障可用性上的代价。

### 20.6 扩展启用条件

仅在以下条件满足后启用上述扩展：

1. 三节点 Replica Set 部署和恢复流程稳定；
2. C1-C4 在正常、节点故障和网络分区下均可重复运行；
3. 原始日志足以区分一致性违反、超时、回滚和普通请求失败；
4. 核心实验与报告进度不受影响；
5. 小组确认增加的实验量能够在截止日期前完成。

扩展参考资料：

- [MongoDB: Causal Consistency and Read and Write Concerns](https://www.mongodb.com/docs/manual/core/causal-consistency-read-write-concerns/)
- [MongoDB: Read Concern `linearizable`](https://www.mongodb.com/docs/manual/reference/read-concern-linearizable/)
- [MongoDB: Read Concern](https://www.mongodb.com/docs/manual/reference/read-concern/)
