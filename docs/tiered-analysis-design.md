# 分层分析设计与路线图 / Tiered Analysis — Design & Roadmap

> 状态 / Status: **draft v0** — 记录性设计文档（design of record）。
> 目前仅新增独立模块 `src/tiered_analysis/`，**不改动**现有单次分析主链路
> (`src/analyzer.py` / `src/stock_analyzer.py` / `src/core/pipeline.py`)。
>
> 本文档是我们讨论结论的完整记录。语言以英文为主、关键市场术语保留中文。

---

## 0. 背景与产品目标 / Background & goal

在 DSA 现有**产品外壳**之上（Web 前端、微信/通知集成、自选股跟踪、调度、
多市场路由 `data_provider/base.py:_market_tag`），增量构建一个**分层的**个股分析产品：

- 用户对某 ticker 先得到 **Tier 1**（四维信息采集 + 方向判断）。
- 可按需向上加深：**Tier 2**（多空辩论）、**Tier 3**（风险压测）、**Tier 4**（组合层）。
- 每一层输出**报告 + 决策**；层级越高，成本/延迟越高，但决策越充分。

**为什么用 DSA 作基座**：Tier 1 本质上就是当前 DSA；前端、通知、自选股、调度、
多市场路由已经存在，从零建新仓库等于重建整个外壳。TA / VT 是美股优先的 agent 框架，
没有可复用的产品外壳。

**三个参考仓库的定位**（均为已核对结论）：
- **DSA**：单次 pipeline，确定性技术分析 → 一次 LLM → 护栏层改写决策。A 股数据最深，
  美股/港股/日韩走较薄的 yfinance 路径。无仓位数量、组合感知为"幻影"。
- **TA (TradingAgents)**：多 agent 辩论（4 分析师 → 多空 → 研究经理 → 交易员 →
  三方风险辩论 → 组合经理）。全 LLM prose。美股/全球，无 A 股。无强制仓位数量、无组合感知。
- **VT (Vibe-Trading)**：对话式 ReAct agent + 确定性回测引擎 + 29 个 YAML swarm 预设 +
  MCP server。真正能算 shares 的地方只在回测引擎；建议 prose 无数量；决策时不感知真实持仓。

三者共同缺口 = **真实仓位数量 + 组合感知**，这正是本产品的差异化空间。

---

## 1. 第一原则：数值 vs 文本 / The numeric-vs-textual rule

整个数据层的核心分类规则：

| 类型 | 生产方式 | 可复现 | 可回测 | 能否喂入仓位计算 |
| --- | --- | --- | --- | --- |
| **NUMERIC 数值** | 确定性代码从数据源计算 | ✅ | ✅ | ✅ |
| **TEXTUAL 文本** | LLM + 联网搜索综合，**必须带可核验引用** | ❌ | ❌ | ❌ |

**规则表述**：
- 任何用户可能**据以下单的数字**（价格、指标、比率、经济序列、市场宽度）→ 必须由
  确定性代码产出。可复现、便宜、快、可回测、可安全进入仓位计算。
- 任何**定性判断**（情绪、叙事）→ 交给 LLM + 搜索 + 引用。因不可复现，**绝不进入
  数量化仓位路径**。

**两个必须避免的反模式**：
1. 给定性情绪**写死爬虫**（脆弱、维护成本高、逐平台逐语言）。
2. 用 **LLM 搜索去"猜"数值**（如市场宽度、涨停家数——没有文章会公布"今日 2347 家上涨"，
   搜索无法可靠还原，只会抓到一句"市场涨跌互现"或直接编造）。

**类比 Claude Code skills**：skill 是 prompt + LLM 即兴，但它仍调用**确定性工具**
（bash、文件读写）取得事实。LLM 负责**编排与叙述**，确定性工具负责**产出每一个数字**。
本设计沿用同一分工。

---

## 2. 四个维度 / The four dimensions

对每个维度给出：类型、各市场数据源、实现方式、覆盖度说明。

### 2.1 技术面 Technicals — **NUMERIC**，地域耦合度最低

- **类型**：NUMERIC。指标是对归一化 OHLCV 序列的纯数学运算，与交易所无关。
- **数据源**：任意市场的日线 OHLCV。v1 用 Yahoo Finance（覆盖全球后缀
  `.KS/.KQ/.HK/.T/.SS/.SZ`），但 yfinance 是非官方抓取（限流/易碎/无 SLA），
  生产上应置于 DSA 现有多源 `data_provider` 之后，而非直接依赖。
- **实现**：确定性纯 Python 指标核心（SMA/EMA/Wilder-RSI/MACD/**ATR**/BIAS + 0-100 综合评分），
  与抓取解耦。**已实现**：`src/tiered_analysis/providers/technicals.py`。
- **注意**：
  - **ATR 是新增的**——现有 `stock_analyzer.py` 缺 ATR（已核对，`src/` 全库零命中），
    而 ATR 是后续波动率止损 / 风险仓位的标准输入，必须补上。
  - **筹码分布 (chip distribution)** 是 A 股散户文化概念，作为 CN 可选叠加，不对美股展示。
- **地域结论**：**一次实现、全球通用（~90%）**。US 扩展这一维度基本免费。

### 2.2 基本面 Fundamentals — **NUMERIC**，地域耦合度高（数据源）

- **类型**：NUMERIC（估值/成长/盈利/资产负债健康度等结构化数字）。
- **数据源（逐市场，无单一全覆盖厂商）**：
  - 美股 US：**SEC EDGAR XBRL**（权威原始报表，VT 已示范 `financial_statements_tool.py:316`）
    + Yahoo 概要（估值比率、财报日）。
  - A 股 CN：AkShare / 东方财富（估值、成长、机构、资金流、龙虎榜、概念）——DSA 已有且最深。
  - 港股 HK：东方财富 F10 / Yahoo。
  - 韩股 KR：**空白**——需 DART（申报）/ Naver / 付费源。yfinance 对 KR 基本面很薄。
- **实现**：定义**统一归一化 schema**（valuation / growth / profitability /
  balance-sheet health），每市场一个 adapter 填充。DSA 已有此 seam
  （`AkshareFundamentalAdapter` / `YfinanceFundamentalAdapter`），沿用扩展。
- **重要澄清（已核对）**：Yahoo **只有概要数字**，不是"文档"；且**海外覆盖不均**
  （港股 ownership 常返回 `ok:true` 但空段——静默留白，比报错更坏）。
  Yahoo 可作 US v1 兜底，深度需原生源。
- **地域结论**：**数据源必须逐市场定制**，但 schema 统一。US 扩展的主要工作量之一。

### 2.3 宏观 Macro — **拆成两半**

宏观其实是两种不同的东西：

**(a) 经济指标 Economic indicators — NUMERIC，地域耦合度低**
- **类型**：NUMERIC（利率/CPI/GDP/失业/PMI 等时间序列）。
- **数据源**：FRED（含大量国际序列）/ OECD / World Bank / Trading Economics 可"一处取多国"
  核心集；各国央行（BOK ECOS 韩、PBoC/NBS 中、BOJ 日）作原生增强。TA 已示范 FRED
  (`dataflows/fred.py`) + Polymarket。
- **实现要点**：经济数据**低频**（月/季）且**同一市场所有 ticker 共享**——
  **按地域每日缓存一次，绝不按 ticker 拉取**。极便宜。以美国为主的共享底盘
  （US 利率、DXY、油、VIX）对每个市场都是有效背景。
- **地域结论**：**一次性共享 feed 覆盖 ~70%**，本地央行数据是增强项。

**(b) 市场内部 Market internals — NUMERIC，地域耦合度高（按交易所）**
- **类型**：NUMERIC（宽度、涨跌停家数、板块/概念轮动、成交额）。
- **本质上按交易所**：A 股宽度对美股无意义；涨跌停板概念在美股不存在、在韩股为 ±30%。
  必须对每个交易所在其全市场universe上计算。
- **DSA 现状（已核对 `market_analyzer.py`）**：仅 A 股产出**结构化**内部数据
  (`limit_up_count`/`top_concepts`/`top_sectors`, `:96-105`)；美/港/日/韩走**另一分支**
  (`:197`) 只做货币格式化的 LLM prose review，**没有**结构化宽度/涨停数据。
- **⚠️ 不可用 LLM 搜索实现**：市场内部是**全市场数值聚合**，搜索抓不到、会编造。
  必须走数据集 feed（AkShare 提供）。
- **地域结论**：**完全逐交易所**；部分概念不可移植。v1 **可延后**。

### 2.4 情绪 Sentiment — **TEXTUAL**，地域耦合度最高

- **类型**：**TEXTUAL**。情绪天然是语言 + 平台绑定：StockTwits/Reddit（美英）、
  雪球/股吧/微博（中）、Naver 종토방（韩）。**没有跨市场统一情绪源**。
- **实现（推荐 LLM + 搜索 + 引用，而非写死爬虫）**：
  - 给 LLM 联网搜索 + `read_url` 工具，让它检索、综合、**给出可核验引用**。语言无关、代码极少、
    自适应新源。这正是 VT 的 default-research 模式。
  - **诚实认知**：通用搜索抓到的多是**新闻/博客**，不是股吧/雪球/Naver 的**真实散户情绪**
    （那些是 JS/App 墙、登录墙、索引差）。所以本法得到的是**新闻情绪**，不是散户情绪——
    对 v1 足够，但**不是差异化**。真正的原生散户情绪源逐市场后补，做好了能胜过三个参考仓库。
- **引用的硬规则**：引用必须是**工具真实抓取**的产物，不能是模型断言的 URL
  （LLM 会编造看似合理的引用、张冠李戴）。需验证 URL 可达、引文真实存在。
- **建议：引用扩展到全部四维**——NUMERIC 引用**数据源**（Yahoo/FRED/申报），
  TEXTUAL 引用**文章**。用户可自查，是很强的信任特性。
- **地域结论**：**完全逐市场**，最重的逐市场投入。

### 2.5 汇总表 / Summary

| 维度 | 类型 | 地域定制 | v1 数据源 | LLM-搜索可行? |
| --- | --- | --- | --- | --- |
| 技术面 Technicals | NUMERIC | 极低 | Yahoo OHLCV（后置于 data_provider） | ❌ 不需要 |
| 基本面 Fundamentals | NUMERIC | 高（源） | US=EDGAR/Yahoo；CN=AkShare | ❌ 需数据源 |
| 宏观-经济 Macro-econ | NUMERIC | 低 | FRED/OECD（按地域每日缓存） | ❌ 需数据源 |
| 宏观-内部 Macro-internals | NUMERIC | 高（交易所） | AkShare(CN)；其余延后 | ❌ 绝不用搜索 |
| 情绪 Sentiment | **TEXTUAL** | 最高 | LLM+搜索+引用（通用兜底） | ✅ 适合 |

---

## 3. 决策层设计 / Decision layer

### 3.1 方向 vs 仓位数量 / Direction vs sizing

- **v1 只给方向**（买/持/卖 + 入场/止损/目标价这些"狙击点"），**不给 shares/$ 数量**。
- **原因**：eval/回测负担来自**虚假精度**。"买入，入场≈1800，止损1750"是定性判断，
  DSA 已在产出、用户已接受；"**买 137 股**"是量化声明，一旦印出数字就欠一个论证（回测）。
  所以 **sizing 与 backtesting 是耦合的，一起延后**。
- **v1 仍要做的两件便宜事**（为未来铺路）：
  1. **输出 schema 预留 sizing 槽位**（`capital`/`risk_fraction`/`shares`），即使 v1 不填。
  2. **从第一天起记录每条推荐 + 后续价格路径**——这是未来回测/eval 的原料，事后重建极痛。

### 3.2 仓位数量是确定性计算，不是 LLM 的活 / Sizing is deterministic

经典风险法（v2+ 实现）：

```
shares = (account_capital × risk_fraction) / (entry_price − stop_loss)
```

- DSA 的"狙击点"已产出 `entry` 与 `stop_loss`（`report_schema.py:92-98`），
  只需再要两个输入：**用户资金** 与 **单笔风险 %**（如 1%）。零 LLM 参与。
- **实现位置**：放进 DSA 现有的**护栏层**（`phase_decision_guardrail.py:314` 已在决策后
  改写建议），而不是 prompt。LLM 定方向，代码定数量——这正是 VT 的分工。
- **需要 ATR**：波动率自适应止损用 ATR（本层已补），比固定狙击点更稳健。

### 3.3 组合感知 / Portfolio awareness（Tier 4）

- 三个参考仓库都**假装**有组合感知（DSA 的 `portfolio_context` 从不进 prompt——已核对幻影；
  VT 的 committee 提示要"existing book"却无工具取持仓）。这是**净新增**空间。
- Tier 4 更难，因单票 sizing 忽略**相关性与总敞口**（5 个半导体票不是 5 个仓位，是 1 个赌注）。
  需要：逐板块/逐票敞口上限、相关性感知 sizing、可选 risk-parity/mean-variance（VT 已有
  `engines/base.py:139-157` 可借）。
- **起步简化**：组合 = 持仓 + 现金；先把**真实持仓喂进 Tier 2/3 的 prompt**
  （DSA 假装做、实际没做的那件事）+ 硬敞口上限。仅此即胜过三个参考仓库。

---

## 4. 分层结构 / Tier structure

| 层 | 输入 | 处理 | 输出 | 对应参考实现 |
| --- | --- | --- | --- | --- |
| **Tier 1** | ticker | 四维采集 → 一次 LLM 综合 | 报告 + **方向**（无数量） | ≈ 现 DSA（`core/pipeline.py:696`） |
| **Tier 2** | Tier 1 结果 | Bull/Bear 辩论 → 研究经理裁决 | 辩论报告 + 更新方向 + **首个仓位数量** | TA `graph/setup.py:122-138` |
| **Tier 3** | Tier 2 结果 | Conservative/Aggressive/Neutral 三方 | 风险报告 + 压测后的仓位与数量 | TA `graph/setup.py:140-165` |
| **Tier 4** | Tier 2/3 + 真实组合 | 相关性/敞口约束 | 组合级建议（数量按 book 调整） | 净新增（三仓库皆无） |

- 默认自选股每日只跑 **Tier 1**；用户可手动触发或开关自动更高层。
- 层与层之间是**确定性图**（借鉴 VT 的 YAML DAG + 拓扑调度 `runtime.py:256`：编排确定性、
  节点内 LLM 即兴）。节点 GUI（可编辑 prompt/边）**延后**（见 §7）。

---

## 5. 架构约定 / Architecture conventions

- **Provider 接口**（已实现 `src/tiered_analysis/providers/base.py`）：
  - `DimensionProvider`：每（维度 × 市场族）一个实现，声明 `NUMERIC` / `TEXTUAL`。
  - `DimensionResult`：统一返回体。NUMERIC 用 `payload`；TEXTUAL 用 `narrative` + `citations`。
  - `Coverage`：`full` / `partial` / **`unavailable`**——**显式降级**，不静默留白。
    这是对 DSA 现状（辅助数据静默降为 `None`/`[]`，`data_provider/base.py:401-445`）的纠正。
  - `is_actionable`：只有 NUMERIC 且有 payload 才为真——sizing 等数值消费者据此 gate，
    薄数据永不静默流入 share 数量。
- **失败处理原则**：借鉴 VT 的 fail-loud（错误作为结构化结果上抛给编排层，
  `agent/src/agent/tools.py:77-84`），而非 DSA 的静默 None/[]。用户据以下单的产品，
  "数据不完整"徽章比伪完整报告更可信。
- **编排 vs 执行**：LLM 决定**跑什么/叙述**；确定性引擎产出**每个数字**（回测、指标、加载器）。

---

## 6. 回测 / Backtesting（v3）

- **定义**：在历史价格上回放一套**决策规则**，先估计表现（收益/最大回撤/夏普）再冒真钱。
  VT 引擎逐 bar 走（`engines/base.py:503-548`），次 bar 开盘成交，跟踪现金/佣金，
  出净值曲线 + 蒙特卡洛置换/自助夏普 CI/walk-forward 验证（`validation.py`）。
- **在本产品的定位——回测"策略"更要回测"策略即我们的分层决策 policy"**：
  "若过去 2 年按 Tier-2 信号 + 我们的 sizing 规则跑我的自选股，收益/回撤如何？"
  这**验证了 sizing**（用户才敢信 share 数）并让分层可度量、可比较。
- **落地建议**：**不照搬** VT 的"LLM 写沙箱代码"重引擎；先做一个**确定性回放**我们自己
  tier 输出的小引擎。放在 sizing + 组合**之后**，因为要先有可回测的东西。

---

## 7. 聊天机器人 / MCP 与节点 GUI（延后）

- **Chatbot 控制网站**：把网站能力做成**内部服务函数**先行；MCP 是 1 天的适配层
  （VT 已示范 `mcp_server.py:66` FastMCP + 40+ `@mcp.tool`）。
  - 用 MCP：chatbot 是独立 runtime，或要第三方客户端（Claude Desktop）也能驱动。
  - 用直接 function-calling：chatbot 在同一后端内，省掉网络跳。
  - **写操作必须确认门控**（触发 tier、改持仓）——参照 VT 的 mandate + kill-switch。
- **节点/边 GUI 编辑器**（延后，代价高）：要先把工作流**外化为数据**（采 VT 的 YAML DAG +
  拓扑调度模型），DSA 现在是硬编码 Python pipeline。风险：用户可编辑 prompt = 破坏 eval 基线
  + prompt 注入面。做成"专家模式"、带版本与"恢复默认"，官方 tier 仍是祝福路径。

---

## 8. 版本路线图 / Roadmap

> 原则：不一次做完；每个增量自足、可验证、对 DSA 核心零/低风险。

### v1 — 基座 + Tier 1（方向，无数量）
- **[已完成本切片]** Provider 接口 + 数值/文本规则编码 + **技术面 provider**（含 ATR）+ 市场路由 + 离线测试。
- Tier 流水线骨架（Tier 1/2/3 stage + 共享 state，Tier 1 委托现有 DSA 分析）。
- 四维 provider 接线（技术面 numeric 已就绪；基本面 US=EDGAR/Yahoo；宏观-经济=FRED 按地域缓存；
  情绪=LLM+搜索+引用通用兜底）。
- **引用**接到四维；`coverage` 徽章在报告/UI 显式展示。
- **推荐日志**（记录建议 + 后续价格路径）。
- 输出 schema **预留 sizing 槽位**（不填）。
- 市场：先把**美股**四维跑通（技术面免费、宏观-经济 FRED 便宜、基本面 EDGAR、情绪搜索兜底）；
  A 股沿用 DSA 现有深度；**韩股**作为独立数据源里程碑。

### v2 — 数量化 + Tier 2/3
- **确定性仓位计算**（capital + risk% + entry/stop → shares），置于护栏层，默认关闭、opt-in。
- Tier 2（多空辩论）+ Tier 3（三方风险）接同一 sizing 引擎，数量随深度更新。
- 波动率止损用 ATR。

### v3 — 回测（验证 sizing）
- 确定性回放我们自己的 tier + sizing policy；收益/回撤/夏普 + 基础统计验证。
- 这是"敢印 share 数"的信任支柱，**优先于**花哨的 GUI/chatbot。

### v4 — 组合层（Tier 4）
- 真实持仓/现金进 Tier 2/3 prompt + 硬敞口上限；相关性感知；可选 risk-parity/mean-variance。

### v5+ — Chatbot/MCP，再节点/边 GUI
- 服务函数 → MCP 适配（写操作确认门控）。
- 工作流外化为 YAML DAG → 节点/边 GUI（专家模式 + 版本化）。
- 逐市场原生**散户情绪**源（雪球/股吧 / Naver），作为真正差异化。

---

## 9. 已实现清单 / Implemented so far（本切片 this slice）

- `src/tiered_analysis/providers/base.py`：`Market` / `SourceKind`(NUMERIC|TEXTUAL) /
  `Coverage`(full|partial|unavailable) / `Citation` / `DimensionResult` / `DimensionProvider`。
- `src/tiered_analysis/providers/technicals.py`：纯 Python 确定性指标
  （SMA/EMA/Wilder-RSI/MACD/**ATR**/BIAS + 0-100 评分），yfinance 抓取依赖隔离。
- `src/tiered_analysis/providers/registry.py`：`detect_market` + provider 路由
  （TODO：改委托 `data_provider/base.py:_market_tag` 作唯一真源）。
- `tests/test_tiered_technicals.py`：20 条离线确定性测试（无 numpy/pandas/网络）。
  已验证：RSI 命中 Wilder 教科书值 70.46；ATR 正确；评分合理区分健康回调(72)>超买直线(66)>下跌(30)。

## 10. 边界与治理 / Boundaries & governance

- 本包**不导入、不修改** `analyzer.py` 决策路径；作为独立能力先行。
- 技术面与 `stock_analyzer.py` 概念重叠，**长期应收敛**（后者偏 A 股且缺 ATR）；
  收敛前二者并存，但**不得**在决策链上重复计算。
- 依 `AGENTS.md`：commit/push 需**显式确认**；用户可见变更需同步 `docs/CHANGELOG.md`
  `[Unreleased]`（扁平格式 `- [类型] 描述`）与 `.env.example`（新增配置时）。
