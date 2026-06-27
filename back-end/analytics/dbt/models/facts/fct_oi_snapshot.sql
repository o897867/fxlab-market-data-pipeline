-- ★ v2 时序基石：每个交易日 × 标的 × 到期日 × 行权价 的 call/put 未平仓量一行。
-- 从全部历史 Parquet 派生（同 fct_iv_snapshot，每次 dbt run 重算全历史，幂等）。
-- 喂 v2-C 的「墙的演变」（大 OI 价位随时间如何移动）。

with c as (

    select *, cast(snapshot_ts as date) as snapshot_date
    from {{ ref('stg_options_contracts') }}
    where open_interest is not null and open_interest > 0

)

select
    underlying_code,
    snapshot_date,
    expiration,
    strike,
    sum(case when option_type = 'CALL' then open_interest else 0 end) as call_oi,
    sum(case when option_type = 'PUT'  then open_interest else 0 end) as put_oi
from c
group by underlying_code, snapshot_date, expiration, strike
