-- OptionLens 标的现价 staging：快照那一刻的标的 last_price，供链对齐 spot。

select
    code                            as underlying_code,
    cast(last_price as double)      as spot,
    cast(snapshot_ts as timestamp)  as snapshot_ts
from read_parquet(
    '{{ var("option_snapshot_dir") }}/underlying/*.parquet', union_by_name = true)
where last_price is not null
