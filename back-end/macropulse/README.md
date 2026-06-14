# MacroPulse — Ingestion（第一期）

央行通讯抓取与归因系统的第一层：抓取 Fed/RBA/ECB 的声明/纪要/讲话，去重后写入
S3 raw 层，复用 FXLab 既有的数据湖（bucket `fxlab-data-lake`，region `ap-southeast-2`）。

本期只实现 **Fed（FOMC 声明 + 纪要正文）** 的 Ingestion。RBA / ECB、Diff 引擎、
鹰鸽抽取、归因回测见六周计划后续。

## 数据源

唯一可靠来源是 **FOMC 日历页** `monetarypolicy/fomccalendars.htm`，它同时列出：

- 声明 press 页：`/newsevents/pressreleases/monetaryYYYYMMDDa.htm`（声明正文 ~2.3k 字）
- 纪要**正文**页：`/monetarypolicy/fomcminutesYYYYMMDD.htm`（完整正文 ~4–5 万字）

URL 里的 `YYYYMMDD` 都是 FOMC 会议（结束）日，声明与纪要按会议日天然配对。

> ⚠️ 坑：「已发布纪要」的 *press release*（`monetary...a.htm`）只是一段三百字公告，
> **不是纪要正文**。正文必须抓 `fomcminutes` 页。早期实现抓错过，已修正。
>
> ⚠️ 年度 `{year}-press.htm` 存档页**不含 FOMC 声明链接**，不要用它做回填。

日历页覆盖近 ~5 年，满足「近三年」回填。更早历史需另接 `fomchistorical` 页（TODO）。

## S3 布局

```
raw/macro/fed/{statement|minutes}/year=YYYY/fed_{type}_{YYYY-MM-DD}.json   # 结构化
raw/macro/fed/{statement|minutes}/year=YYYY/fed_{type}_{YYYY-MM-DD}.html   # 原文存证
metadata/macro_ingest_manifest.json                                       # 幂等清单
```

`.json` 字段见 `models.py: RawDocument`（raw 层只含原文+元信息，**不含**鹰鸽打分/diff，
那是后续抽取引擎的事）。`content_hash` 用于去重与变更检测。

## 用法

```bash
cd back-end && source venv/bin/activate

# 回填全部历史（声明 + 纪要）。幂等，可反复跑
python -m macropulse.ingest backfill

# 只回填声明
python -m macropulse.ingest backfill --statements-only

# 只抓取+解析、不写 S3（验证解析质量）
python -m macropulse.ingest backfill --dry-run

# 增量：只抓日历页上尚未入库的新会议（Lambda 走这条）
python -m macropulse.ingest incremental
```

幂等策略：`backfill` 抓取每篇并按 `content_hash` 比对（能捕捉勘误重抓）；
`incremental` 对已在 manifest 的 `document_id` 免抓直接跳过（声明/纪要发布后不变）。

## 部署

`lambda/macropulse/handler.py` 是 Lambda 入口，调用 `run_incremental()`。约定与既有
`analytics-pipeline` 一致：EventBridge 定时触发，S3 权限由 IAM role 提供（代码不写凭证）。
打包时需把 `requests` / `beautifulsoup4` 随代码或 layer 一并打入，并把 `back-end/macropulse`
包加进部署 zip 的 import 路径。

环境变量（均有默认值，见 `config.py`）：`MACRO_S3_BUCKET`、`MACRO_S3_REGION`、
`MACRO_USER_AGENT`、`MACRO_REQUEST_DELAY`、`MACRO_BACKFILL_YEARS`。

## Diff 引擎（第二期·确定性层）

相邻两期 FOMC 声明的段落对齐 + 词级红线，**不依赖 LLM**，结果可肉眼复核。是
「AI 红线对比」的骨架；方向（hawkish/dovish）与强度标注留给后续 LLM 抽取层。

- 段落对齐：Needleman-Wunsch（sim≥0.98 未变 / ≥0.5 修改 / <0.5 拆删+增）
- 词级 diff：difflib，渲染为 wdiff 风格 `[-删-]{+增+}`
- 输出对接交接文档 `diffs_vs_previous` 的 section/old/new 字段（见 `diff.py`）

```bash
python -m macropulse.diff_cli --latest                 # 最近两期红线
python -m macropulse.diff_cli --pair 2026-03-18 2026-04-29
python -m macropulse.diff_cli --all                    # 所有相邻对的 summary
python -m macropulse.diff_cli --latest --json          # 结构化 JSON
```

> 已知：`2025-08-22` 是 Jackson Hole 特别声明（非常规 FOMC 政策声明，结构不同），
> 在相邻链里会表现为「改 0 / 全删增」。后续可在 diff 链中按 doc 子类型剔除。

## LLM 抽取层（第二周·鹰鸽打分）

Claude API（Opus 4.8）+ 结构化输出，对声明/纪要做 schema v0.1 打分：
overall_score(-5~+5) + 四维度(inflation/labor/balance_sheet_qt/forward_guidance,
各含 score/key_quote/confidence) + diff 方向标注 + needs_human_review。

设计要点：
- **key_quote 必须逐字**：代码侧校验是否为原文子串，违规自动标 needs_human_review
- **diff 的 old/new 不让模型转写**：来自确定性 diff 引擎，LLM 只标 direction/magnitude
- **三份锚点声明做分数校准**（2022-06-15 极鹰 / 2024-09-18 鸽 / 2024-01-31 中性），
  锚点块打 prompt cache 断点（回填/回归时 ~0.1x 计费）
- **回填走 Batch API（5 折）**；幂等 manifest 记录 (content_hash, prompt_hash)，
  改 prompt 须 bump `prompts.PROMPT_VERSION`
- Jackson Hole 类非常规声明不参与 diff 链（自身照常打分，无 diff）

```bash
# 前置：.env 配 ANTHROPIC_API_KEY（API 按量计费，与 Claude Max 订阅无关）
python -m macropulse.extraction.cli one --date 2026-04-29          # 单篇冒烟
python -m macropulse.extraction.cli one --date 2026-04-29 --type minutes
python -m macropulse.extraction.cli backfill --dry-run             # 只统计任务
python -m macropulse.extraction.cli backfill                       # Batch 全量回填
```

结果落 S3 `analysis/macro/fed/scores/{statement|minutes}/year=*/...json`。
成本（实测口径见 CLI 末尾用量报告）：全量回填约 $3（Batch 后），此后 <$1/年。

## 归因回测（第三周·项目灵魂）

把鹰鸽分数与声明后 XAU 实际价格反应对齐，算滚动方向命中率——ground truth=市场。

- **事件时刻 t0**：会议日 14:00 America/New_York（zoneinfo 自动处理夏/冬令时 →
  18:00/19:00 UTC），对齐 `xau_candles_1m.open_time`
- **窗口**：15min / 1h / 1d 的 XAU 收益（at-or-before 取价，超 180min 滞后判不可用）
- **方向约定**：鹰派→黄金跌、鸽派→黄金涨；命中 = sign(收益)==-sign(分数)，中性事件
  不计命中
- **聚合**：每窗口的命中率、Pearson(分数,收益)、鹰/鸽分组均值
- 结果落 S3 `analysis/macro/fed/attribution/backtest.json`

```bash
python -m macropulse.attribution.cli run            # 计算 + 报告 + 落 S3
python -m macropulse.attribution.cli run --dry-run  # 只打印不写
```

> ⚠️ **数据约束（重要）**：FXLab 仅有 XAU（无 DXY/US2Y），且 XAU 1m 历史从
> 2025-10 起——44 篇声明里只有约 5 篇有价格覆盖。当前是**方法论 POC**，样本 N 极小、
> 无统计显著性，每次新 FOMC 自动累积。补足需接 DXY/US2Y 数据源或更长 XAU 历史。
>
> 已知坑：别拿 `aws s3 ls` 输出 grep 日期——第一列是上传时间戳，会误匹配成事件日期。

## 合规

Fed 文档为公开出版物（FOIA / 公共领域），抓取风险低。本模块自报 User-Agent、
请求间隔默认 1s 限速。接入 RBA/ECB 前需各自确认官网 robots.txt 与使用条款。

## 测试

```bash
python -m pytest tests/macropulse/ --no-cov -q
```

覆盖：声明/纪要正文解析、样板段剔除、doc_type 分类、日历页列表与去重配对、
content_hash、manifest 幂等、ingest 的类型过滤与免抓跳过路径。全部 hermetic（不联网/不连 S3）。
