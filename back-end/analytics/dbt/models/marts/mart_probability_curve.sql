-- 面板②问问市场：每 (标的, 到期日, call 行权价) 一行的概率曲线。
-- call delta ≈ 风险中性下「到期收在该行权价之上」的概率，InsightSentry 直接给。
-- 服务层拿目标价 X 在相邻行权价间对 prob_above 线性插值即可。
-- 诚实：这是市场定价的概率、非真实世界概率（delta 为风险中性）。

with calls as (

    select *
    from {{ ref('int_option_chain') }}
    where option_type = 'CALL'
      and t_years > 0
      and delta is not null

)

select
    underlying_code,
    expiration,
    strike,
    spot,
    t_years,
    delta                                          as call_delta,
    least(greatest(delta, 0), 1)                   as prob_above,   -- 收在行权价之上
    1 - least(greatest(delta, 0), 1)               as prob_below
from calls
