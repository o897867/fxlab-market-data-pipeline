-- OptionLens 链宽表：两源 join（quotes ⋈ contracts ON code）成一张可用链。
-- 这是 doc 里「两个 staging 源 → 一张表」的核心活。
-- 只保留每个标的的最新一张快照（v1 是当前链）；附上 mid、年化到期时间 T、moneyness。

with latest as (

    -- 每个标的最近一次快照时刻
    select underlying_code, max(snapshot_ts) as snap
    from {{ ref('stg_options_quotes') }}
    group by 1

),

q as (

    select sq.*
    from {{ ref('stg_options_quotes') }} sq
    join latest l
      on sq.underlying_code = l.underlying_code
     and sq.snapshot_ts     = l.snap

),

c as (

    select sc.code, sc.open_interest, sc.oi_date, sc.close_price, sc.multiplier, sc.style, sc.status
    from {{ ref('stg_options_contracts') }} sc
    join latest l
      on sc.underlying_code = l.underlying_code
     and sc.snapshot_ts     = l.snap

)

select
    q.underlying_code,
    q.code,
    q.option_type,
    q.strike,
    q.expiration,
    q.snapshot_ts,
    q.spot,
    -- 报价
    q.bid,
    q.ask,
    (q.bid + q.ask) / 2.0                               as mid,
    case when q.ask > 0 then (q.ask - q.bid) / q.ask end as rel_spread,   -- 价差占比，流动性指示
    -- IV / 希腊值
    q.iv,
    q.delta,
    q.gamma,
    q.theta,
    q.vega,
    q.theo_price,
    -- 持仓（来自 contracts，截至昨收）
    c.open_interest,
    c.oi_date,
    c.multiplier,
    -- 派生：年化到期时间 T（日历日/365）、价值状态
    greatest(date_diff('day', cast(q.snapshot_ts as date), q.expiration), 0) / 365.0 as t_years,
    date_diff('day', cast(q.snapshot_ts as date), q.expiration)                       as days_to_expiry,
    q.strike / nullif(q.spot, 0)                                                      as moneyness
from q
left join c on q.code = c.code
