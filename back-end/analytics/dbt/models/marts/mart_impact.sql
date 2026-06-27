-- 模块④影响面板：期权怎么影响正股。每 (标的, 到期日) 一行。
-- 三个子模块的数值（可信度标签在服务层 panels.impact 附，因其为每子模块的常量）：
--   A 磁吸位：max_pain + 大 OI 价位（来自 mart_strike_distribution）
--   B 事件预期：本到期 ATM IV vs 下一到期(baseline) → 近月异常抬升=市场在为事件定价
--   C 波动状态 GEX：Σcalls(γ·OI) − Σputs(γ·OI) × 100 × S² × 0.01
--      ⚠️ 符号取决于"做市商在 call 空 gamma、put 多 gamma"的【假设】，非观测事实。

with em as (

    select underlying_code, expiration, spot, atm_iv, t_years
    from {{ ref('mart_expected_move') }}

),

em_base as (

    -- baseline = 下一个到期日的 ATM IV（按到期排序取 lead）
    select *,
        lead(atm_iv) over (partition by underlying_code order by expiration) as baseline_iv
    from em

),

gex as (

    select
        underlying_code,
        expiration,
        sum(case when option_type = 'CALL' then coalesce(gamma, 0) * coalesce(open_interest, 0) else 0 end) as call_go,
        sum(case when option_type = 'PUT'  then coalesce(gamma, 0) * coalesce(open_interest, 0) else 0 end) as put_go
    from {{ ref('int_option_chain') }}
    where t_years > 0
    group by underlying_code, expiration

),

mp as (

    select
        underlying_code,
        expiration,
        any_value(max_pain_strike)                              as max_pain_strike,
        (array_agg(strike order by total_oi desc))[1:3]         as magnet_strikes
    from {{ ref('mart_strike_distribution') }}
    group by underlying_code, expiration

)

select
    e.underlying_code,
    e.expiration,
    e.spot,
    cast(round(e.t_years * 365) as integer)                                    as dte,
    -- B 事件预期
    e.atm_iv                                                                   as front_iv,
    e.baseline_iv,
    round((e.atm_iv / nullif(e.baseline_iv, 0) - 1) * 100, 1)                  as front_premium_pct,
    (e.baseline_iv is not null and e.atm_iv > e.baseline_iv * 1.10)            as event_flag,
    -- A 磁吸位
    mp.max_pain_strike,
    mp.magnet_strikes,
    -- C 波动状态 GEX
    (g.call_go - g.put_go) * 100 * e.spot * e.spot * 0.01                      as net_gex,
    case when (g.call_go - g.put_go) >= 0 then 'suppress' else 'amplify' end   as gex_regime
from em_base e
left join gex g on e.underlying_code = g.underlying_code and e.expiration = g.expiration
left join mp  on e.underlying_code = mp.underlying_code and e.expiration = mp.expiration
