-- 情绪信号：Put/Call OI 比 + 5 日趋势 —— 防守情绪在升温还是降温。
-- 依赖 fct_oi_snapshot 的历史积累。每 (标的) 一行 = 今天 vs ~5 交易日前的对比。
--   pc_today    最新交易日：全链 Σput_oi / Σcall_oi
--   pc_prev     ~5 交易日前（数据不足时取现有最早一天，days_back 标注实际跨度）
--   trend       rising(防守升温) / falling(防守降温) / flat（阈值 ±5%）
-- 冷启动：只有 1 天数据时 pc_prev = pc_today、trend = flat、days_back = 0。

with daily as (

    -- 每 (标的, 快照日) 的全链 P/C（跨全部到期日与行权价汇总）
    select
        underlying_code,
        snapshot_date,
        sum(put_oi)::double / nullif(sum(call_oi), 0) as pc_ratio
    from {{ ref('fct_oi_snapshot') }}
    group by underlying_code, snapshot_date
    having sum(call_oi) > 0

),

ordered as (

    select *,
        row_number() over (
            partition by underlying_code order by snapshot_date desc
        ) as days_ago   -- 1 = 最新交易日
    from daily

),

today as (

    select underlying_code, snapshot_date as as_of, pc_ratio as pc_today
    from ordered where days_ago = 1

),

prev as (

    -- 目标 ~5 交易日前(days_ago=6)；不足则退到现有最早一天
    select underlying_code, pc_ratio as pc_prev, snapshot_date as prev_date
    from ordered o
    where days_ago = (
        select least(6, max(days_ago)) from ordered o2
        where o2.underlying_code = o.underlying_code
    )

)

select
    t.underlying_code,
    t.as_of,
    t.pc_today,
    p.pc_prev,
    date_diff('day', p.prev_date, t.as_of) as days_back,
    case
        when p.pc_prev is null or p.pc_prev = 0 then 'flat'
        when t.pc_today > p.pc_prev * 1.05      then 'rising'
        when t.pc_today < p.pc_prev * 0.95      then 'falling'
        else 'flat'
    end as trend
from today t
left join prev p on t.underlying_code = p.underlying_code
