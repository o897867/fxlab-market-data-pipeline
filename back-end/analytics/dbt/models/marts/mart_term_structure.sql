-- 面板⑤期限结构：近月 vs 远月 IV，回答"市场觉得近期有事、还是远期"。
-- 每 (标的, 到期日) 一行；附该标的整条曲线的形态。
--   backwardation(近月>远月) = 近期有事(财报/事件)
--   contango(远月>近月) = 常态
-- 数据现成：mart_expected_move 已有各到期 ATM IV（抽取已拉最近 ~45 天多个到期）。

with em as (

    select
        underlying_code,
        expiration,
        spot,
        cast(round(t_years * 365) as integer) as dte,
        atm_iv
    from {{ ref('mart_expected_move') }}
    where t_years > 0 and atm_iv is not null

),

bounds as (

    -- 该标的曲线的近端(最小 dte)与远端(最大 dte) ATM IV
    select *,
        first_value(atm_iv) over (
            partition by underlying_code order by dte
            rows between unbounded preceding and unbounded following) as front_iv,
        last_value(atm_iv) over (
            partition by underlying_code order by dte
            rows between unbounded preceding and unbounded following) as back_iv
    from em

)

select
    underlying_code,
    expiration,
    spot,
    dte,
    atm_iv,
    front_iv,
    back_iv,
    case
        when front_iv > back_iv * 1.05 then 'backwardation'
        when back_iv  > front_iv * 1.05 then 'contango'
        else 'flat'
    end as shape_flag
from bounds
