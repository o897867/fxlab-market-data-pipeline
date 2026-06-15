"""通用标的分析（从 xau_analysis 泛化）。

四类分析（日度统计 / 波动率 / 时段 / 周度）只依赖 OHLCV DataFrame，与标的无关。
XAU / DXY / US2Y 共用。指数（DXY/US2Y）无成交量，volume 相关字段会是 0/None——
价格/收益/波动率分析仍有效。US2Y 的 close 是收益率%，daily change_pct 偏噪声，
方向与水平仍可读。
"""

import io
from datetime import datetime, timezone

import numpy as np
import pandas as pd


def load_from_s3(s3, bucket: str, prefix: str) -> pd.DataFrame:
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    frames = []
    for obj in resp.get("Contents", []):
        if obj["Key"].endswith(".parquet"):
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            frames.append(pd.read_parquet(io.BytesIO(body)))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).drop_duplicates(subset=["open_time"]).sort_values("open_time")
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df


def _safe(val):
    import math
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        v = float(val)
        return v if math.isfinite(v) else None
    if isinstance(val, (np.ndarray,)):
        return [_safe(x) for x in val]
    if pd.isna(val):
        return None
    return val


def daily_stats(df: pd.DataFrame) -> list:
    daily = df.set_index("dt").resample("D").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), candle_count=("close", "count"),
    ).dropna(subset=["close"])
    daily["change_pct"] = daily["close"].pct_change() * 100
    daily["range_pct"] = (daily["high"] - daily["low"]) / daily["open"] * 100
    daily["gap"] = daily["open"] - daily["close"].shift(1)
    out = []
    for date, row in daily.iterrows():
        out.append({
            "date": date.strftime("%Y-%m-%d"),
            "open": _safe(row["open"]), "high": _safe(row["high"]), "low": _safe(row["low"]),
            "close": _safe(row["close"]), "volume": _safe(row["volume"]),
            "candle_count": _safe(row["candle_count"]),
            "change_pct": _safe(round(row["change_pct"], 3)) if pd.notna(row["change_pct"]) else None,
            "range_pct": _safe(round(row["range_pct"], 3)),
            "gap": _safe(round(row["gap"], 2)) if pd.notna(row["gap"]) else None,
        })
    return out


def volatility_analysis(daily_records: list) -> dict:
    df = pd.DataFrame(daily_records)
    df["date"] = pd.to_datetime(df["date"])
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    returns = np.insert(np.diff(closes) / closes[:-1], 0, 0)
    vol_5 = pd.Series(returns).rolling(5).std() * np.sqrt(252)
    vol_10 = pd.Series(returns).rolling(10).std() * np.sqrt(252)
    vol_20 = pd.Series(returns).rolling(20).std() * np.sqrt(252)
    tr = np.maximum(highs[1:] - lows[1:],
                    np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
    atr = pd.Series(np.insert(tr, 0, highs[0] - lows[0])).ewm(span=14).mean()
    current_vol = float(vol_20.iloc[-1]) if pd.notna(vol_20.iloc[-1]) else 0
    vol_percentile = float((vol_20.dropna() < current_vol).mean() * 100)
    regime = "low" if vol_percentile < 33 else ("high" if vol_percentile > 66 else "medium")
    records = []
    for i, row in df.iterrows():
        records.append({
            "date": row["date"].strftime("%Y-%m-%d"), "close": _safe(row["close"]),
            "vol_5d": _safe(round(vol_5.iloc[i], 4)) if pd.notna(vol_5.iloc[i]) else None,
            "vol_10d": _safe(round(vol_10.iloc[i], 4)) if pd.notna(vol_10.iloc[i]) else None,
            "vol_20d": _safe(round(vol_20.iloc[i], 4)) if pd.notna(vol_20.iloc[i]) else None,
            "atr_14": _safe(round(atr.iloc[i], 4)) if pd.notna(atr.iloc[i]) else None,
        })
    return {"current_regime": regime, "current_vol_20d": _safe(round(current_vol, 4)),
            "vol_percentile": _safe(round(vol_percentile, 1)), "series": records}


def session_analysis(df: pd.DataFrame) -> dict:
    sessions = {"asian": (0, 8), "london": (8, 16), "newyork": (13, 22)}
    df = df.copy()
    df["hour"] = df["dt"].dt.hour
    df["date_str"] = df["dt"].dt.strftime("%Y-%m-%d")
    results = {}
    for name, (start, end) in sessions.items():
        sess = df[(df["hour"] >= start) & (df["hour"] < end)]
        if sess.empty:
            continue
        d = sess.groupby("date_str").agg(open=("open", "first"), close=("close", "last"),
                                         high=("high", "max"), low=("low", "min"), volume=("volume", "sum"))
        d["return_pct"] = (d["close"] - d["open"]) / d["open"] * 100
        d["range_pct"] = (d["high"] - d["low"]) / d["open"] * 100
        results[name] = {
            "avg_return_pct": _safe(round(d["return_pct"].mean(), 4)),
            "win_rate": _safe(round((d["return_pct"] > 0).mean() * 100, 1)),
            "avg_range_pct": _safe(round(d["range_pct"].mean(), 3)),
            "avg_volume": _safe(round(d["volume"].mean(), 0)),
            "trading_days": len(d),
        }
    return results


def weekly_summary(daily_records: list) -> list:
    df = pd.DataFrame(daily_records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    weekly = df.resample("W-FRI").agg(open=("open", "first"), high=("high", "max"),
                                      low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).dropna(subset=["close"])
    weekly["return_pct"] = (weekly["close"] - weekly["open"]) / weekly["open"] * 100
    out = []
    for week_end, row in weekly.iterrows():
        week_start = week_end - pd.Timedelta(days=4)
        wd = df[(df.index >= week_start) & (df.index <= week_end)]
        best = worst = None
        if not wd.empty and "change_pct" in wd.columns:
            valid = wd.dropna(subset=["change_pct"])
            if not valid.empty:
                best = valid["change_pct"].idxmax().strftime("%Y-%m-%d")
                worst = valid["change_pct"].idxmin().strftime("%Y-%m-%d")
        out.append({
            "week_ending": week_end.strftime("%Y-%m-%d"), "open": _safe(row["open"]),
            "high": _safe(row["high"]), "low": _safe(row["low"]), "close": _safe(row["close"]),
            "volume": _safe(row["volume"]), "return_pct": _safe(round(row["return_pct"], 3)),
            "trend": "up" if row["return_pct"] > 0 else "down", "best_day": best, "worst_day": worst,
        })
    return out


def analyze(df: pd.DataFrame, name: str) -> dict:
    """跑全部四类分析，键名带 {name}_ 前缀。"""
    if df.empty:
        return {"error": f"No {name} data"}
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_range": {"from": df["dt"].min().strftime("%Y-%m-%d"),
                       "to": df["dt"].max().strftime("%Y-%m-%d")},
        "total_candles": len(df),
    }
    ds = daily_stats(df)
    return {
        f"{name}_daily_stats": {**meta, "results": ds},
        f"{name}_volatility": {**meta, "results": volatility_analysis(ds)},
        f"{name}_sessions": {**meta, "results": session_analysis(df)},
        f"{name}_weekly": {**meta, "results": weekly_summary(ds)},
    }
