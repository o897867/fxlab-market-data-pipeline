#!/bin/bash
# OptionLens 每日刷新：拉当前链快照(全部 DEFAULT_SYMBOLS) → dbt 重建 marts。
# 由 cron 在美股收盘后调用（OI 为 T+1，IV/Greeks 取收盘时点）。失败不静默，进日志。
set -uo pipefail

ROOT=/root/shopback/ShopBack_PP/back-end
LOG="$ROOT/logs/option_refresh.log"
mkdir -p "$ROOT/logs"

cd "$ROOT" || exit 1
# shellcheck disable=SC1091
source venv/bin/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null

{
  echo "═════ $(date -u +'%Y-%m-%d %H:%M:%S UTC') OptionLens refresh ═════"
  python -m option.extract 2>&1
  # 财报日与 HV 变化都慢，无需每日刷——只在周一跑一次，省 InsightSentry 用量（约 ÷5）。
  # 缓存（earnings.json / hv.json）持久化，整周被 dbt/panels 复用。
  if [ "$(date -u +%u)" = "1" ]; then
    echo "── 周一：刷新财报日 + HV 缓存 ──"
    python -m option.earnings 2>&1        # 下次财报日缓存（事件预期用）
    python -m option.realized_vol 2>&1    # 已实现波动 HV 缓存（IV 冷启动期的贵贱参照）
  else
    echo "── 非周一：跳过财报/HV 刷新（复用上周一缓存）──"
  fi
  cd "$ROOT/analytics/dbt" || exit 1
  export DBT_DUCKDB_PATH="$ROOT/analytics/dbt/eventstudy.duckdb"
  # 全部期权 marts 一次重建：之前漏了 mart_impact / mart_term_structure，
  # 导致影响面板/期限结构面板读到陈旧数据。fct_* 是 IV/OI 时序基石，务必每日重算。
  dbt run --select stg_options_quotes stg_options_contracts stg_options_underlying \
      int_option_chain fct_iv_snapshot fct_oi_snapshot \
      mart_expected_move mart_probability_curve mart_strike_distribution \
      mart_impact mart_term_structure mart_iv_rank mart_pc_trend 2>&1
  # 快照持久化到 S3 + freshness 断档检查（不可逆资产的备份，见 sync_s3 docstring）。
  cd "$ROOT" || exit 1
  python -m option.sync_s3 2>&1
  echo "done $(date -u +'%H:%M:%S')"
} >> "$LOG" 2>&1
