# FXLab 落地路线图

> 从现有 XAU 管道到美股期权体检产品的实施计划
> 起始日期：2026-07-06

---

## ⚠️ 现实对齐（2026-07-06 整改）—— 先读这一节

**本路线图原稿是一份"绿地"计划，假设从零开始。但 OptionLens v2 已经用一套更好的架构把
阶段 0–2 的大半实现了。以下把原稿与代码现实对齐，作为真实起点。下面的原文（阶段 0–4）保留
作历史与愿景参考，但遇到冲突以本节为准。**

### 架构决策：以 dbt-duckdb 为准，废弃原稿的 SQLite 方案

| 原稿说要建 | 现实（已建，且更好） | 处置 |
|---|---|---|
| SQLite `options_snapshots` 表 + `ingest_options.py` | `option/extract.py` → **Parquet 快照** → dbt-duckdb | 原稿 SQLite 方案是倒退，**废弃** |
| 扩展 `export_to_s3.py` 导出期权 | `option/sync_s3.py`（P0 新建，幂等同步快照到 S3） | 用新模块，不改 export_to_s3 |
| 阶段 2 `translator.py` 翻译层 | **已内联在 `option/panels.py`**（翻译铁律已实现） | **已完成**，非缺口 |
| 阶段 4 probability curve | `mart_probability_curve` 已建 | **已完成** |
| Lambda `options_analysis()` | dbt-duckdb marts + `panels.py` | 架构不同，**无需 Lambda** |

### 四信号盘点

- ✅ Expected Move / Strike Concentration+P/C(当日) / Probability / Term Structure / Impact —— 已建并翻译好
- ❌ **IV Rank** —— `mart_iv_rank` 未建（`fct_iv_snapshot` 喂它的数据已在攒，约需 1 个月）
- ❌ **P/C 5 日趋势** —— 当前只有当日值（`fct_oi_snapshot` 已在攒，可做）

### ✅ P0 已完成（2026-07-06，不可逆时钟项）

1. **watchlist 4→18 只**：`option/config.py` `DEFAULT_SYMBOLS`。全部经 `get_quotes` 验过代码。
   科技核心(10)+ETF(3)+高波动(4)+ORCL。extract.py 加逐票 1.5s sleep 防 rate limit。
   → 今晚 22:00 UTC cron 起，18 只全部开始攒 IV/OI 历史。
2. **快照持久化到 S3**：新建 `option/sync_s3.py`，每日 dbt run 后幂等同步
   `data/snapshots/*.parquet` → `s3://fxlab-data-lake/raw/options/{table}/{SYM}/`，
   并做 freshness 断档检查（断档非零退出、日志可 grep）。已把既有 6 天×4 只历史全部回填上 S3。
3. **修 `refresh.sh`**：补建之前漏掉的 `mart_impact` / `mart_term_structure`，并接 `sync_s3`。

### ✅ P1 已完成（2026-07-06，铺好数据水管）

产品铁律复核：**系统只报"期权市场当前定价的客观统计"，不含任何预测或建议**。所有翻译文案
按此审过，剔除了"→留意是不是要发生""市场预期"等预测/建议语气；daily_report 带合规声明。

- **IV Rank**：`marts/mart_iv_rank.sql`（~30DTE ATM IV 对比历史窗口，`data_days` 冷启动标注）
  + `panels.iv_rank` + `GET /api/option/iv-rank`。
- **P/C 5 日趋势**：`marts/mart_pc_trend.sql`（全链 Σput/Σcall 今天 vs ~5交易日前 + trend）
  + `panels.pc_trend` + `GET /api/option/pc-trend`。
- **watchlist 聚合**：`panels.daily_report`（临近≤14天财报置顶、其余按 IV Rank 降序）
  + `GET /api/option/daily-report`；`GET /api/option/iv-board`（IV Rank 排行）；
  `GET /api/option/earnings-calendar`（未来两周）。
- refresh.sh 已把两张新 mart 纳入每日重建；dbt data_tests 全绿（iv_rank∈[0,100]、trend 枚举等）。
- 数据现状：IV Rank / P/C 趋势现有 6 天历史 → 前端与文案显示"数据积累中"，满 30 天后可信。

### ✅ P2 已完成（2026-07-06，前端 watchlist 首页）

- `front-end/src/pages/OptionLens.jsx`：新增 **WatchBoard 榜单视图**（默认落地页），消费
  `/api/option/daily-report`，每票一张卡（紧张度色点 + 本期波动 ±% 与区间 + P/C 情绪箭头 +
  临近财报角标），临近财报置顶、其余按 IV Rank 降序。点卡片下钻到既有单票详情（总览/影响/期限），
  详情页加"← 榜单"返回。SYMS 扩到 18 只（含中文名）。
- 冷启动诚实呈现：数据未满 30 天时紧张度显示"积累中"灰点 + 天数，不给贵贱结论。
- 榜单底部带合规声明。`vite build` 通过；5 个新端点 HTTP 200 实测通过（daily-report 返回 18 卡）。

### 剩余真实缺口（按优先级）

- ~~**Telegram 分发**~~ —— 本轮不做
- **P3**（需攒历史 / 经历一次财报）：`mart_prediction_scorecard`（implied vs realized）；付费墙
- **⚠️ 安全债**：`option/config.py` 里 InsightSentry token 硬编码进了仓库（fallback 值），应改为只读环境变量并轮换该 key

---

## 总览：8 周 5 个阶段

```
Week 0        Week 1–2        Week 3–4         Week 5–6         Week 7–8
──────        ────────        ────────         ────────         ────────
 验证            数据层          分析+翻译层       前端+分发         财报增强+付费墙
 ↓               ↓               ↓                ↓                ↓
手工出第一张    管道跑通        四信号自动产出    用户能看到        产品完整上线
日频报告       数据每天进来     翻译逻辑定型     频道开始推内容    Telegram 付费开通
```

关键原则：**每个阶段结束时必须有可展示的产出物**，不是"代码写完了"而是"能给一个人看到一个东西"。

---

## 阶段 0：API 验证 + 手工出品（第 0 周，7 月 6–12 日）

### 目标
验证 InsightSentry REST API 的期权端点能给你需要的数据，同时手工产出第一份日频报告发频道，验证内容方向。

### 任务清单

**Day 1-2：API 探路**

- [ ] 用现有 InsightSentry REST API key，手动调用以下端点，确认返回格式和字段：
  - `get_options_contracts` — 拿 NVDA 的期权合约列表，确认能拿到 expiry、strike、type（call/put）
  - `get_options_quotes` — 拿 NVDA ATM 附近 ±10 个 strike 的 bid/ask/OI/volume，确认字段完整性
  - `get_options_snapshot` — 确认和 quotes 的区别，看哪个更适合日频快照
  - `get_quotes` — 拿 NVDA 正股现价，确认能锚定 ATM strike
  - `get_earnings` — 拿未来两周财报日历，确认覆盖你的 watchlist
  - `get_symbol_history` — 拿 NVDA 过去一年日频收盘价，用于算 historical volatility
- [ ] 把每个端点的实际返回存成 JSON 样本文件（`samples/options_contracts_NVDA.json` 等）
- [ ] 记录 API 限制：rate limit、每次最多返回多少条、是否需要分页
- [ ] 确认一个关键问题：**能不能拿到 IV 字段？** 如果端点直接返回 implied volatility 就省了自己算；如果只给 bid/ask 则需要用 Black-Scholes 反推

**Day 3-4：手工计算四信号（以 NVDA 为例）**

用 Jupyter Notebook 或 Python 脚本，基于 Day 1-2 拉到的真实数据手工算一遍：

- [ ] **IV Rank**：取 NVDA 30-day ATM IV，对比过去 52 周的 IV 高低值，算百分位
  - 如果 API 没有历史 IV → 用 `get_symbol_history` 拿日频价格，算 historical volatility 作为参照系（先用 HV percentile 替代，v1 再积累 IV 历史）
- [ ] **Expected Move**：取最近周五到期的 ATM straddle（ATM call bid+ask midpoint + ATM put bid+ask midpoint），得出 ±$ 和 ±%
- [ ] **Strike Concentration**：把所有 strike 的 OI 和 volume 做分布图，标注 put 端和 call 端各自 OI 最大的 3 个 strike
- [ ] **P/C Ratio**：总 put OI / 总 call OI，如果能拿 5 天数据就画趋势

**Day 5-6：翻译 + 出品**

- [ ] 把上面四个信号翻译成人话，写成一张"NVDA 期权日报"：
  ```
  📊 NVDA 期权体检 | 2026-07-10
  
  🔴 紧张度：偏高
  当前期权市场紧张程度处于过去一年的前 18%，
  高于正常水平，说明市场对近期波动有较强预期。
  
  📐 本周定价波动：±4.2%（$121–$132）
  期权市场认为 NVDA 本周有约 68% 概率落在这个区间。
  
  🧱 关键价位
  下方：$118 put 堆了最大 OI — 市场认为这里有支撑
  上方：$140 call 集中放量 — 有人在赌突破
  
  📡 情绪风向：偏防守
  Put/Call 比 = 1.15，过去 5 天从 0.85 升至 1.15，
  防守情绪在升温。
  
  ⚠️ 以上为期权市场定价的客观统计，不构成投资建议。
  ```
- [ ] 用同样方法再做 1–2 只票（AMD、TSLA），总共 3 张卡片
- [ ] 发到频道，观察互动

**Day 7：复盘 + 决策**

- [ ] 记录 API 调用中遇到的所有问题（字段缺失、rate limit、数据延迟）
- [ ] 记录手工计算中哪些步骤最耗时（这些就是自动化的优先级）
- [ ] 记录翻译措辞中哪些地方拿不准（这些在后续迭代中打磨）
- [ ] 决定：继续推进 → 进阶段 1；方向需要调整 → 先修正产品定义

### 交付物
- `samples/` 目录：每个 API 端点的真实返回样本
- `notebooks/manual_report_NVDA.ipynb`：手工计算全过程
- 3 张发到频道的日频报告卡片
- `NOTES.md`：API 限制、遇到的问题、翻译措辞记录

### 阻塞风险
- InsightSentry 期权端点不返回 IV → 降级方案：用 Black-Scholes 从 bid/ask 中位价反推，需要增加计算逻辑
- 部分票期权流动性差（bid-ask spread 很大）→ 手工筛选流动性好的到期日和 strike 范围
- API rate limit 太紧 → 记录具体限制，阶段 1 设计批量调用策略

---

## 阶段 1：数据层（第 1–2 周，7 月 13–26 日）

### 目标
让期权数据每天自动进来、存好、上 S3。阶段结束时数据管道无人值守地跑。

### Week 1：Ingestion + Buffer

- [ ] **新建 SQLite 表结构**
  ```sql
  -- 期权快照（日频主表）
  CREATE TABLE options_snapshots (
      id INTEGER PRIMARY KEY,
      symbol TEXT NOT NULL,
      snapshot_date TEXT NOT NULL,      -- YYYY-MM-DD
      expiry TEXT NOT NULL,             -- 到期日
      strike REAL NOT NULL,
      option_type TEXT NOT NULL,        -- call/put
      bid REAL, ask REAL, mid REAL,
      iv REAL,                          -- 如果 API 提供
      oi INTEGER, volume INTEGER,
      delta REAL,                       -- 如果 API 提供
      underlying_price REAL,
      captured_at INTEGER NOT NULL,     -- unix timestamp
      UNIQUE(symbol, snapshot_date, expiry, strike, option_type)
  );

  -- 财报日历
  CREATE TABLE earnings_events (
      id INTEGER PRIMARY KEY,
      symbol TEXT NOT NULL,
      report_date TEXT NOT NULL,
      report_time TEXT,                 -- BMO/AMC
      eps_estimate REAL,
      revenue_estimate REAL,
      captured_at INTEGER NOT NULL,
      UNIQUE(symbol, report_date)
  );
  ```
- [ ] **写 ingestion 脚本** `ingest_options.py`
  - 输入：watchlist（先硬编码核心层 15-20 只）
  - 对每只票：拿正股现价 → 确定 ATM → 拉 ATM ±15 strikes × 最近 3 个到期日 → 写入 SQLite
  - 做好 rate limit 控制（两次调用之间 sleep）
  - 错误处理：单只票失败不阻塞整个 watchlist，记录 log 继续
- [ ] **写 ingestion 脚本** `ingest_earnings.py`
  - 调用 `get_earnings`，未来 30 天的财报事件，upsert 到 SQLite
- [ ] **systemd timer 配置**
  - `ingest_options.py` 每天 UTC 21:30 执行（美东收盘后 30 分钟）
  - `ingest_earnings.py` 每天执行一次（和 options 同一个 timer chain）
- [ ] **跑 3 天观察数据质量**
  - 检查：每只票是否都有数据？OI/volume 是否合理？有没有空值？

### Week 2：Export + S3

- [ ] **扩展 `export_to_s3.py`**
  - 新增 `options_snapshots` 和 `earnings_events` 两张表的导出逻辑
  - 复用现有 watermark CDC 机制（watermark key: `options_last_captured_at`, `earnings_last_captured_at`）
  - S3 路径：`raw/options/{symbol}/year=YYYY/month=MM/{symbol}_options_YYYY-MM.parquet`
  - 复用 merge-on-upload 去重逻辑
- [ ] **验证 S3 数据**
  - 手动跑一次 export，检查 Parquet 文件是否正确
  - 用 pandas 读回来验证行数、字段、去重是否正确
- [ ] **端到端测试**
  - 让 ingestion + export 自动跑 2 天
  - 检查 S3 上是否每天都有新增数据
  - 检查 watermark 推进是否正确

### 交付物
- `ingest_options.py`、`ingest_earnings.py` 在 EC2 上自动运行
- SQLite 中有 3+ 天的期权快照数据
- S3 上有对应的 Parquet 文件
- 扩展后的 `export_to_s3.py`

### Done 标准
在你不干预的情况下，连续 3 天 EC2 自动拉数据 → SQLite → S3，零报错。

---

## 阶段 2：分析 + 翻译层（第 3–4 周，7 月 27 日 – 8 月 9 日）

### 目标
Lambda 自动产出四信号 + 翻译文案，输出 JSON 到 S3，FastAPI 能读到。

### Week 3：四个核心分析模块

- [ ] **`iv_rank.py`**
  - 输入：`options_snapshots` 中某 symbol 的 30-day ATM IV 时间序列
  - 计算：当前 IV 在过去 N 天（初期数据不够 252 天时用已有天数）的百分位
  - 冷启动处理：数据不足 30 天时标注"数据积累中，参考价值有限"
  - 输出：`{ "symbol": "NVDA", "iv_current": 0.42, "iv_rank": 82, "iv_high_52w": 0.58, "iv_low_52w": 0.25, "data_days": 45 }`

- [ ] **`expected_move.py`**
  - 输入：最近周五到期的 ATM straddle mid price + 正股现价
  - 计算：expected_move_pct = straddle_mid / underlying_price；上下界 = price ± expected_move
  - 输出：`{ "symbol": "NVDA", "expiry": "2026-08-07", "expected_move_pct": 4.2, "range_low": 121.3, "range_high": 131.8, "straddle_price": 5.25, "underlying": 126.5 }`

- [ ] **`strike_concentration.py`**
  - 输入：跨财报到期日（或最近月度到期日）的全部 strike OI + volume
  - 计算：分别找 put 端和 call 端 OI 最大的 top-3 strike，标注其 OI 值和占总 OI 的百分比
  - 输出：`{ "symbol": "NVDA", "put_walls": [{"strike": 118, "oi": 45000, "pct": 12.3}...], "call_walls": [...], "max_pain": 125 }`

- [ ] **`put_call_ratio.py`**
  - 输入：最近 5 个交易日的 total put OI 和 total call OI
  - 计算：每日 P/C ratio + 5 日趋势方向（上升/持平/下降）
  - 输出：`{ "symbol": "NVDA", "pc_ratio_today": 1.15, "pc_ratio_5d_ago": 0.85, "trend": "rising" }`

- [ ] **整合入 Lambda handler**
  - 扩展现有 `handler.py`，增加 `options_analysis()` 入口
  - 对 watchlist 每只票跑四个模块，汇总成一个 JSON
  - 输出到 S3：`results/options/{date}/daily_report.json`

### Week 4：翻译层 + FastAPI

- [ ] **翻译引擎 `translator.py`**
  - 输入：四信号的原始 JSON
  - 输出：每只票的人话翻译文案（中文）
  - 翻译规则硬编码（不用 LLM，规则够了）：
    ```python
    def translate_iv_rank(data):
        rank = data["iv_rank"]
        if rank >= 80:
            level = "偏高"
            desc = f"当前期权市场紧张程度处于过去一年的前 {100-rank}%，高于正常水平"
        elif rank >= 50:
            level = "中等"
            desc = f"处于过去一年的 {100-rank}% 位置，属于正常范围"
        else:
            level = "偏低"
            desc = f"处于过去一年的后 {100-rank}%，市场情绪相对平静"
        return {"level": level, "description": desc}
    ```
  - 同样逻辑覆盖 expected_move、strike_concentration、put_call_ratio
  - **所有翻译文案末尾自动附加合规声明**

- [ ] **FastAPI 新增端点**
  ```
  GET /api/options/daily-report              → 全部 watchlist 的日频概览（按 IV rank 排序）
  GET /api/options/daily-report/{symbol}      → 单只票完整四信号 + 翻译
  GET /api/options/earnings-calendar          → 未来两周财报排期
  GET /api/options/iv-rank                    → watchlist IV rank 排行
  ```

- [ ] **端到端验证**
  - Lambda 手动 invoke → S3 JSON → FastAPI 读取 → curl 验证返回格式
  - 对照阶段 0 手工报告，确认自动产出和手工结果一致

### 交付物
- 四个分析模块在 Lambda 上运行
- `translator.py` 产出中文翻译
- FastAPI 新增 4 个端点可访问
- 至少 5 只票的日频报告可通过 API 获取

### Done 标准
`curl https://your-domain/api/options/daily-report/NVDA` 返回完整的四信号 + 中文翻译 JSON，数据来自当天自动运行的管道而非手工。

---

## 阶段 3：前端 + 分发（第 5–6 周，8 月 10–23 日）

### 目标
用户能在浏览器看到产品，频道开始常规推送。

### Week 5：React 前端

- [ ] **首页（Watchlist Overview）**
  - 调用 `/api/options/daily-report`
  - 卡片列表，每只票一张卡，按 IV rank 排序
  - 每张卡片显示：ticker、紧张度色块（绿/黄/红）、本周定价波动范围、P/C ratio 箭头
  - 有财报的票自动置顶 + 标注"X 天后财报"
  - 设计调性参考产品计划书：冷静、概率感、去焦虑化

- [ ] **个股详情页**
  - 调用 `/api/options/daily-report/{symbol}`
  - 四信号完整展示 + 翻译文案
  - OI 分布可视化（横轴 strike、纵轴 OI，put/call 双色条形图）
  - IV rank 趋势图（折线，随数据积累逐渐丰富）

- [ ] **财报日历页**
  - 调用 `/api/options/earnings-calendar`
  - 未来两周时间线，标注 BMO/AMC

### Week 6：Telegram Bot + 频道内容流程

- [ ] **复用 MacroPulse bot 架构**
  - 新建一个 Telegram 频道（先做公开频道，付费墙后加）
  - bot 每天美股收盘后 1 小时自动发送：watchlist 中 IV rank top-5 的摘要
  - 格式精简：一条消息覆盖 5 只票，每只 2 行

- [ ] **频道视频素材工作流**
  - 从自动生成的日频报告中，每周选 2–3 只票深度解读
  - 建立模板：屏幕录制 dashboard + 人话解读 voiceover
  - 关键：免费内容做"教育"（"你知道期权市场今天给 NVDA 的体检结果吗"），不做"推荐"

- [ ] **用户反馈收集**
  - 在前端和 Telegram 加一个反馈入口（简单的"有用/没用"按钮）
  - 记录到 SQLite，用于后续优化翻译质量

### 交付物
- React 前端三个页面上线可访问
- Telegram bot 每日自动推送
- 频道发出至少 3 期基于自动化数据的内容
- 反馈收集机制运行

### Done 标准
一个从未见过这个产品的人，能通过频道内容 → 点击链接 → 在浏览器看到 NVDA 的四信号报告 → 在 Telegram 收到每日摘要。完整用户路径跑通。

---

## 阶段 4：财报增强 + 付费墙（第 7–8 周，8 月 24 日 – 9 月 6 日）

> 时间点刚好赶上 Q2 财报季尾声和 Q3 季初，可以用真实财报验证。

### Week 7：财报分析模块

- [ ] **`implied_vs_realized.py`**
  - 需要历史数据：过去 N 次财报的隐含波动 vs 实际波动
  - 冷启动方案：前几次靠手工回填（用 `get_symbol_history` 拿财报日前后价格，手工算实际波动），之后系统自动积累
  - 输出："过去 8 次财报中，6 次实际波动小于期权定价"

- [ ] **`probability_curve.py`（Breeden-Litzenberger）**
  - 输入：某到期日的完整 call 价格曲线（strike vs mid price）
  - 计算：对 call 价格关于 strike 求二阶导 → 风险中性概率密度
  - 平滑方法：先对 call mid 做三次样条插值，再求导（避免离散数据的噪音）
  - 输出：概率密度曲线的离散点 + 关键分位数（10%、25%、50%、75%、90%）

- [ ] **财报卡片模板**
  - 在日频四信号基础上叠加：贵贱判断 + 概率曲线 + 历史对照
  - 前端增加财报卡片专属视图

### Week 8：付费墙 + 上线

- [ ] **Telegram 付费频道设置**
  - 新建私有频道，通过 bot 管理订阅
  - 付费用户：完整日频报告 + 财报 playbook + 历史查询
  - 免费用户：保持公开频道的精简版摘要

- [ ] **前端付费层**（可选，v1 不强求）
  - 免费：首页概览（紧张度 + 波动范围）
  - 付费：个股详情页完整四信号 + 财报分析
  - 技术实现：简单 token 验证即可，不需要复杂的用户系统

- [ ] **上线 checklist**
  - [ ] 数据管道连续运行 7 天无报错
  - [ ] 翻译文案人工审核（逐字检查合规措辞）
  - [ ] 频道发出"产品上线"公告
  - [ ] 定价确认：$X/月
  - [ ] 退款/取消订阅流程确认

### 交付物
- 完整产品上线：日频报告 + 财报分析 + 付费通道
- 第一批付费用户（哪怕只有个位数）

### Done 标准
有人付了钱，每天能收到报告，没来找你投诉数据有问题。

---

## 持续运营（上线后）

| 周期 | 动作 |
|------|------|
| 每天 | 检查管道运行日志（5 分钟，逐步加 alerting 自动化） |
| 每周 | 选 2–3 只票出频道深度内容 |
| 每两周 | 审核翻译质量：措辞是否准确、有没有误导性表述 |
| 每月 | 回顾 IV rank 历史数据质量、implied vs realized 命中率 |
| 每季度 | 财报季复盘：卡片准确度、用户反馈、续费率 |

---

## 风险登记簿

| 风险 | 影响 | 缓解方案 |
|------|------|----------|
| InsightSentry 期权端点字段不全（缺 IV、缺 greeks） | 阶段 2 复杂度大增 | 阶段 0 Day 1-2 立即验证，不行就换数据源（CBOE、Yahoo Finance options API） |
| 冷启动问题：IV 历史数据不够算 IV rank | 前几周百分位不准 | 用 HV percentile 过渡，明确标注"数据积累中"，30 天后切换 |
| watchlist 中部分票期权流动性差 | 数据噪音大 | 入选核心层的硬性条件：ATM straddle bid-ask spread < 5%，否则降级或剔除 |
| API rate limit 限制日频拉 15-20 只票 | ingestion 超时或被封 | 阶段 0 记录实际限制，设计 batch + sleep 策略 |
| 翻译措辞踩合规红线 | 法律风险 | 所有翻译模板人工审核，"建议"/"应该" 等词加入黑名单自动拦截 |
| 做了 8 周没人付费 | 沉没成本 | 阶段 0 的频道验证就是止损阀；整个管道仍然是简历资产 |

---

## 技术债务（已知，刻意接受）

v1 阶段刻意不做、留给后续迭代的事：

- 不做用户注册系统（Telegram 订阅管理足够）
- 不做自选股（v1 只有固定核心层 watchlist）
- 不做实时刷新（日频够了）
- 不做移动端适配（先确保桌面端可用）
- 不做历史财报回填自动化（手工回填前 8-12 次）
- 不做 alerting/CloudWatch（手动查日志）
- 不做多语言（只做中文）

这些都是 v2 的事。v1 的唯一目标是：**让第一个付费用户觉得每天打开有价值。**
