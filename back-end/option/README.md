# 期权透镜 OptionLens

把期权市场的信号翻译成正股交易者看得懂的人话。v1 三面板：**预期范围**、**问问市场**（目标价概率）、**押注分布**（OI）。完整设计见 [`期权透镜_落地文档.md`](期权透镜_落地文档.md)。

## 架构

```
InsightSentry REST  ──(每日收盘后拉当前链快照)──►  Parquet (option/data/snapshots/)
        │                                                │
        │  option/extract.py                             ▼
        │                                          dbt-duckdb (analytics/dbt)
        │                                          staging → int_option_chain → marts
        ▼                                                │
  option/panels.py  ◄───────── 读 mart_* ────────────────┘
        │
        ▼
  routers/option_router.py  (/api/option/*)  ──►  前端 React 页 OptionLens.jsx
```

- **抽取**：`option/extract.py` 拉三端点（`options/quotes` 报价+IV+希腊值、`options/contracts` OI、`symbols/quotes` 现价），三源各落一份 Parquet（故意不 join，留给 dbt）。
- **建模**：dbt-duckdb（`analytics/dbt`）。`stg_options_*` → `int_option_chain`（按 OPRA code join、附 T/moneyness）→ 三张 mart。
- **服务**：`option/panels.py` 读 marts 出「人话标题 + 原始数字」；`routers/option_router.py` 暴露 `/api/option/{symbols,expected-move,probability,distribution}`。
- **前端**：`front-end/src/pages/OptionLens.jsx`，编辑式终端浅色风，方向不靠红绿（青=赌涨/琥珀=买保护）。

## 计算核心（marts）

| mart | 算什么 |
|---|---|
| `mart_expected_move` | `S × ATM_IV × √T` 的 1 标准差区间；跨式价 /0.7979 反推做校验 |
| `mart_probability_curve` | call delta ≈ 风险中性 P(收在行权价之上)，供目标价插值 |
| `mart_strike_distribution` | 每价位 call/put OI + is_wall(top5) + max_pain + pc_ratio |

## 手动跑一遍

```bash
cd back-end && source venv/bin/activate
# 1. 拉快照（默认 OPTION_SYMBOLS：MU/SPY/ORCL/GOOG）
python -m option.extract
# 2. 建模
cd analytics/dbt && DBT_DUCKDB_PATH=$(pwd)/eventstudy.duckdb \
  dbt run --select stg_options_quotes stg_options_contracts stg_options_underlying \
    int_option_chain mart_expected_move mart_probability_curve mart_strike_distribution
dbt test --select int_option_chain mart_expected_move mart_probability_curve mart_strike_distribution
# 3. 命令行验面板
python -c "from option import panels; print(panels.expected_move('NASDAQ:MU')['headline'])"
```

## 每日自动刷新

`option/refresh.sh` = extract 全标的 + dbt run。装进 cron（美股收盘后，工作日 22:00 UTC）：

```bash
bash back-end/option/setup_cron.sh    # 幂等，重复运行不重复添加
```

日志在 `back-end/logs/option_refresh.log`。

## 重要约束（doc §10）

- **历史 IV/链 API 不给**，只有实时——IV Rank 这类时序指标靠每天落快照往后攒（v2）。
- **概率用 delta 是风险中性概率**，非真实世界概率、非预言；产品里诚实说明。
- **OI 是 T+1**（截至昨收），所有押注分布标注。
- **期货期权不支持**（无 GC/SOFR 期权），只有 OPRA 股票/ETF/指数。
- 流动性差的票 bid/ask 宽，v1 先锁 MU/SPY/ORCL/GOOG 这类。

## 标的

默认 `OPTION_SYMBOLS=NASDAQ:MU,AMEX:SPY,NYSE:ORCL,NASDAQ:GOOG`（环境变量可覆盖）。前端顶栏 ▾ 切换。
