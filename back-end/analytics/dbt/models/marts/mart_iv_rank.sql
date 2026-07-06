-- 时序面板：IV Rank / IV Percentile —— 现在期权比过去（最多一年）贵还是便宜。
-- 依赖 fct_iv_snapshot 的历史积累（doc §4）。这是唯一"现在不做以后补不回来"的信号，
-- 数据少时不藏——照样出，靠 data_days 让下游标注"数据积累中，参考价值有限"。
--
-- 每 (标的) 一行 = 该标的"当前"的 IV 站位：
--   iv_current  最新交易日的 ~30DTE ATM IV（取最接近 30 天到期的那档作恒定期限代理，
--               避免不同天挑到不同到期日导致的锯齿）
--   iv_rank     (iv_current − iv_low) / (iv_high − iv_low) × 100
--   iv_percentile 过去窗口里 IV 低于今天的天数占比 × 100
--   data_days   已积累的快照天数（冷启动标注用；< 30 天时 rank 参考价值有限）

with per_day as (

    -- 每 (标的, 快照日) 取最接近 30DTE 的一档 ATM IV 作当日代表值
    select
        underlying_code,
        snapshot_date,
        atm_iv,
        row_number() over (
            partition by underlying_code, snapshot_date
            order by abs(dte - 30), dte
        ) as rn
    from {{ ref('fct_iv_snapshot') }}
    where atm_iv is not null and atm_iv > 0

),

daily as (

    select underlying_code, snapshot_date, atm_iv as iv_30d
    from per_day
    where rn = 1

),

latest as (

    select underlying_code, max(snapshot_date) as as_of
    from daily
    group by underlying_code

),

windowed as (

    -- 只取每个标的最近 ~1 年（252 交易日≈365 日历日）窗口
    select d.*
    from daily d
    join latest l on d.underlying_code = l.underlying_code
    where d.snapshot_date >= l.as_of - interval 365 day

),

stats as (

    select
        underlying_code,
        min(iv_30d)                   as iv_low,
        max(iv_30d)                   as iv_high,
        count(distinct snapshot_date) as data_days
    from windowed
    group by underlying_code

),

curr as (

    select w.underlying_code, w.iv_30d as iv_current, l.as_of
    from windowed w
    join latest l
      on w.underlying_code = l.underlying_code and w.snapshot_date = l.as_of

),

pctile as (

    -- 过去窗口里 iv_30d 严格低于今天的天数占比
    select
        c.underlying_code,
        sum(case when w.iv_30d < c.iv_current then 1 else 0 end)::double
            / nullif(count(*), 0) * 100 as iv_percentile
    from curr c
    join windowed w on w.underlying_code = c.underlying_code
    group by c.underlying_code

)

select
    c.underlying_code,
    c.as_of,
    c.iv_current,
    s.iv_low,
    s.iv_high,
    case
        when s.iv_high > s.iv_low
        then (c.iv_current - s.iv_low) / (s.iv_high - s.iv_low) * 100
        else null   -- 高低相等（数据太少/无波动）→ rank 无意义，下游据 data_days 标注积累中
    end as iv_rank,
    p.iv_percentile,
    s.data_days
from curr c
join stats  s on c.underlying_code = s.underlying_code
join pctile p on c.underlying_code = p.underlying_code
