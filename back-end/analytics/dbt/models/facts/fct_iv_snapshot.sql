-- ★ v2 时序基石（v1 就该默默跑）：每个交易日 × 标的 × 到期日 的 ATM IV 一行。
-- 历史链不含过期合约、无法回填 —— 靠 extract 每天写一张带日期的 Parquet 往后攒；
-- 本模型从全部历史 Parquet 派生（每次 dbt run 重算全历史，幂等、不会漂）。
-- 喂 v2-C 的 IV Rank / IV Percentile / 财报 IV crush。
--
-- 注意：不能只用 int_option_chain（那只取最新一张快照）——这里要全历史，
-- 故直接从 stg_options_quotes（read_parquet 全量）按 snapshot_date 聚合。

with q as (

    select *, cast(snapshot_ts as date) as snapshot_date
    from {{ ref('stg_options_quotes') }}
    where iv is not null and spot > 0
      -- 排除当日到期(0DTE)：其 ATM IV 数学上可达数千%、对 IV Rank/crush 无意义
      and date_diff('day', cast(snapshot_ts as date), expiration) >= 1

),

ranked as (

    -- 每 (标的, 快照日, 到期日) 内，按到现价距离给行权价排名；rk=1=最接近(含其 call&put)
    select *,
        dense_rank() over (
            partition by underlying_code, snapshot_date, expiration
            order by abs(strike - spot)
        ) as rk
    from q

)

select
    underlying_code,
    snapshot_date,
    expiration,
    avg(iv)                                                  as atm_iv,
    any_value(spot)                                          as spot,
    any_value(date_diff('day', snapshot_date, expiration))  as dte
from ranked
where rk = 1
group by underlying_code, snapshot_date, expiration
