#!/bin/bash
# 一次性：把 OptionLens 每日刷新装进 crontab（美股收盘后，工作日 22:00 UTC）。
# 幂等：重复运行不会重复添加。运行：bash back-end/option/setup_cron.sh
set -euo pipefail

JOB="0 22 * * 1-5 /root/shopback/ShopBack_PP/back-end/option/refresh.sh"

current="$(crontab -l 2>/dev/null || true)"
if echo "$current" | grep -qF "option/refresh.sh"; then
  echo "已存在 option/refresh.sh 的 cron，跳过。"
else
  printf '%s\n%s\n' "$current" "$JOB" | crontab -
  echo "✅ 已添加：$JOB"
fi
crontab -l | grep "option/refresh.sh"
