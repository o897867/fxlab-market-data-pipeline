"""OptionLens —— 把期权市场信号翻译成正股交易者看得懂的人话。

v1 三面板：预期范围 / 问问市场(目标价概率) / 押注分布(OI)。
数据源 InsightSentry REST；每日拉一张当前链快照落 Parquet → dbt-duckdb 建模。
见 option/期权透镜_落地文档.md。
"""
