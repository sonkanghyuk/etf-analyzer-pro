from __future__ import annotations
import numpy as np
import pandas as pd

TRADING_DAYS = 252

def max_drawdown(price: pd.Series) -> float:
    s = pd.to_numeric(price, errors="coerce").dropna()
    if len(s) < 2:
        return float("nan")
    peak = s.cummax()
    dd = s / peak - 1.0
    return float(dd.min())

def performance_metrics(price: pd.Series, risk_free_rate: float = 0.0) -> dict:
    s = pd.to_numeric(price, errors="coerce").dropna()
    if len(s) < 2:
        return {
            "return_pct": np.nan, "cagr_pct": np.nan, "volatility_pct": np.nan,
            "mdd_pct": np.nan, "sharpe": np.nan, "days": len(s)
        }

    daily = s.pct_change().dropna()
    total_return = s.iloc[-1] / s.iloc[0] - 1.0
    elapsed_days = max((s.index[-1] - s.index[0]).days, 1)
    years = elapsed_days / 365.25

    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    vol = daily.std(ddof=1) * np.sqrt(TRADING_DAYS) if len(daily) > 1 else np.nan

    rf_daily = (1 + risk_free_rate) ** (1 / TRADING_DAYS) - 1
    excess = daily - rf_daily
    sharpe = (
        excess.mean() / excess.std(ddof=1) * np.sqrt(TRADING_DAYS)
        if len(excess) > 1 and excess.std(ddof=1) > 0 else np.nan
    )

    return {
        "return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "volatility_pct": vol * 100,
        "mdd_pct": max_drawdown(s) * 100,
        "sharpe": sharpe,
        "days": len(s),
    }

def normalized_prices(prices: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    out = prices.copy()
    for c in out.columns:
        s = out[c].dropna()
        if not s.empty:
            out[c] = out[c] / s.iloc[0] * base
    return out

def drawdown_frame(prices: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=prices.index)
    for c in prices.columns:
        s = prices[c]
        out[c] = (s / s.cummax() - 1.0) * 100
    return out

def overlap_score(a: pd.DataFrame, b: pd.DataFrame) -> float:
    if a.empty or b.empty:
        return np.nan
    aa = a[["holding", "weight"]].copy()
    bb = b[["holding", "weight"]].copy()
    aa["key"] = aa["holding"].astype(str).str.strip().str.upper()
    bb["key"] = bb["holding"].astype(str).str.strip().str.upper()
    merged = aa.merge(bb, on="key", how="inner", suffixes=("_a", "_b"))
    if merged.empty:
        return 0.0
    return float(np.minimum(merged["weight_a"], merged["weight_b"]).sum())

def overlap_matrix(holdings: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    m = pd.DataFrame(index=tickers, columns=tickers, dtype=float)
    groups = {t: holdings[holdings["etf"] == t] for t in tickers}
    for a in tickers:
        for b in tickers:
            if a == b:
                m.loc[a, b] = 100.0
            else:
                m.loc[a, b] = overlap_score(groups[a], groups[b])
    return m

def hhi(weights_pct: pd.Series) -> float:
    w = pd.to_numeric(weights_pct, errors="coerce").dropna() / 100
    return float((w ** 2).sum() * 10000)

def concentration_label(value: float) -> str:
    if pd.isna(value):
        return "-"
    if value < 1000:
        return "분산형"
    if value < 1800:
        return "중간 집중"
    return "고집중"

def monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    monthly = prices.resample("ME").last().pct_change() * 100
    monthly.index = monthly.index.to_period("M").astype(str)
    return monthly

def annual_returns(prices: pd.DataFrame) -> pd.DataFrame:
    annual = prices.resample("YE").last().pct_change() * 100
    annual.index = annual.index.year.astype(str)
    return annual
