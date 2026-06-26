-- 面板①预期范围：每 (标的, 到期日) 一行。
-- expected_move = S × ATM_IV × √T（≈ 1 个标准差、68% 区间）。
-- 校验列 straddle_em_check：由 ATM 跨式价反推的 1 标准差。
--   ATM 跨式价 ≈ 0.7979 × S × σ × √T（标准结果），故 1 标准差 ≈ 跨式价 / 0.7979。
--   它应与 expected_move 接近（高 IV 下因 skew / 价差会有 ~10% 偏差，属正常校验容差）。

with chain as (

    select * from {{ ref('int_option_chain') }}
    where t_years > 0 and iv is not null

),

ranked as (

    -- 按到 spot 的距离给行权价排名；rk=1 即最接近现价的那个行权价（含其 call & put）
    select *,
        dense_rank() over (
            partition by underlying_code, expiration
            order by abs(strike - spot)
        ) as rk
    from chain

),

atm as (

    select
        underlying_code,
        expiration,
        any_value(spot)                                          as spot,
        any_value(t_years)                                       as t,
        avg(iv)                                                  as atm_iv,        -- call/put IV 取均
        sum(case when option_type = 'CALL' then mid end)         as atm_call_mid,
        sum(case when option_type = 'PUT'  then mid end)         as atm_put_mid
    from ranked
    where rk = 1
    group by underlying_code, expiration

)

select
    underlying_code,
    expiration,
    spot,
    t                                                       as t_years,
    atm_iv,
    spot * atm_iv * sqrt(t)                                 as expected_move_usd,
    spot - spot * atm_iv * sqrt(t)                          as band_low,
    spot + spot * atm_iv * sqrt(t)                          as band_high,
    atm_iv * sqrt(t)                                        as pct,
    (atm_call_mid + atm_put_mid) / 0.7979                   as straddle_em_check
from atm
