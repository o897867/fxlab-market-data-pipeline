-- OptionLens 合约 staging：读 contracts Parquet 快照，拿未平仓量 OI。
-- OI 是 T+1（open_interest_date 为前一交易日收盘），下游一律标注「截至昨收」。

with source as (

    select * from read_parquet(
        '{{ var("option_snapshot_dir") }}/contracts/*.parquet', union_by_name = true)

),

renamed as (

    select
        underlying_code,
        code,
        upper(type)                          as option_type,
        cast(strike_price as double)         as strike,
        cast(expiration as date)             as expiration,
        try_cast(open_interest as bigint)    as open_interest,
        try_cast(open_interest_date as date) as oi_date,
        try_cast(close_price as double)      as close_price,
        try_cast(multiplier as integer)      as multiplier,
        style,
        status,
        cast(snapshot_ts as timestamp)       as snapshot_ts
    from source
    where code is not null

)

select * from renamed
