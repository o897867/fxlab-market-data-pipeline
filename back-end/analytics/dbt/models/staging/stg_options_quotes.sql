-- OptionLens 报价链 staging：读 option/extract.py 落的 quotes Parquet 快照。
-- 只做类型转换/重命名/归一，1 行 = 1 个期权合约在某次快照的报价 + IV + 希腊值。
-- expiration 在 quotes 端点是 int YYYYMMDD（与 contracts 的字符串日期不同），此处归一为 date。

with source as (

    select * from read_parquet(
        '{{ var("option_snapshot_dir") }}/quotes/*.parquet', union_by_name = true)

),

renamed as (

    select
        underlying_code,
        code,                                              -- OPRA 合约码，两源 join 键
        upper(type)                              as option_type,   -- CALL / PUT
        cast(strike_price as double)             as strike,
        strptime(cast(expiration as varchar), '%Y%m%d')::date as expiration,
        cast(bid_price as double)                as bid,
        cast(ask_price as double)                as ask,
        cast(implied_volatility as double)       as iv,
        cast(bid_iv as double)                   as bid_iv,
        cast(ask_iv as double)                   as ask_iv,
        cast(delta as double)                    as delta,
        cast(gamma as double)                    as gamma,
        cast(theta as double)                    as theta,
        cast(vega as double)                     as vega,
        cast(rho as double)                      as rho,
        cast(theoretical_price as double)        as theo_price,
        cast(spot as double)                     as spot,
        cast(snapshot_ts as timestamp)           as snapshot_ts
    from source
    where code is not null

)

select * from renamed
