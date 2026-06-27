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
  python -m option.earnings 2>&1   # 下次财报日缓存（事件预期用）
  cd "$ROOT/analytics/dbt" || exit 1
  export DBT_DUCKDB_PATH="$ROOT/analytics/dbt/eventstudy.duckdb"
  dbt run --select stg_options_quotes stg_options_contracts stg_options_underlying \
      int_option_chain fct_iv_snapshot fct_oi_snapshot \
      mart_expected_move mart_probability_curve mart_strike_distribution 2>&1
  echo "done $(date -u +'%H:%M:%S')"
} >> "$LOG" 2>&1
