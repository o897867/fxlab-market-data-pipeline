-- 面板③押注分布：每 (标的, 到期日, 行权价) 的 call/put 未平仓量 + 是否「墙」。
-- 并附 max_pain（期权买方整体最痛的价位=临近到期的磁吸位）与 pc_ratio（看跌/看涨）。
-- OI 截至昨收（int_option_chain.oi_date），下游标注。

with chain as (

    select * from {{ ref('int_option_chain') }}
    where open_interest is not null and open_interest > 0

),

per_strike as (

    select
        underlying_code,
        expiration,
        strike,
        any_value(spot)                                                 as spot,
        sum(case when option_type = 'CALL' then open_interest else 0 end) as call_oi,
        sum(case when option_type = 'PUT'  then open_interest else 0 end) as put_oi
    from chain
    group by underlying_code, expiration, strike

),

ranked as (

    select *,
        call_oi + put_oi as total_oi,
        row_number() over (
            partition by underlying_code, expiration
            order by call_oi + put_oi desc
        ) as oi_rank
    from per_strike

),

pc as (

    -- 每 (标的, 到期日) 的看跌/看涨 OI 比
    select underlying_code, expiration,
        sum(put_oi)::double / nullif(sum(call_oi), 0) as pc_ratio
    from per_strike
    group by underlying_code, expiration

),

pain as (

    -- 对每个候选行权价 K，算所有合约在标的=K 到期时的总内在价值；取最小者为 max_pain
    select c.underlying_code, c.expiration, cand.k,
        sum(
            case when c.option_type = 'CALL'
                 then greatest(cand.k - c.strike, 0) * c.open_interest
                 else greatest(c.strike - cand.k, 0) * c.open_interest end
        ) as total_pain
    from chain c
    join (select distinct underlying_code, expiration, strike as k from per_strike) cand
      on c.underlying_code = cand.underlying_code and c.expiration = cand.expiration
    group by c.underlying_code, c.expiration, cand.k

),

max_pain as (

    select underlying_code, expiration, k as max_pain_strike,
        row_number() over (partition by underlying_code, expiration order by total_pain asc) as rn
    from pain

)

select
    r.underlying_code,
    r.expiration,
    r.strike,
    r.spot,
    r.call_oi,
    r.put_oi,
    r.total_oi,
    r.oi_rank,
    (r.oi_rank <= 5)                  as is_wall,     -- 押注最多的前 5 个价位
    pc.pc_ratio,
    mp.max_pain_strike
from ranked r
left join pc      on r.underlying_code = pc.underlying_code and r.expiration = pc.expiration
left join max_pain mp on r.underlying_code = mp.underlying_code and r.expiration = mp.expiration and mp.rn = 1
