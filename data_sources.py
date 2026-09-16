from __future__ import annotations
import re
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        return out
    return out

def download_prices(tickers: list[str], start, end) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not tickers:
        return pd.DataFrame(), pd.DataFrame()
    raw = yf.download(tickers=tickers, start=start, end=end, auto_adjust=False, actions=True, progress=False, group_by="column", threads=True)
    if raw is None or raw.empty:
        return pd.DataFrame(), pd.DataFrame()
    if len(tickers) == 1:
        ticker = tickers[0]
        price_col = "Adj Close" if "Adj Close" in raw.columns else "Close"
        prices = raw[[price_col]].rename(columns={price_col: ticker})
        closes = raw[["Close"]].rename(columns={"Close": ticker}) if "Close" in raw.columns else prices.copy()
        return prices.dropna(how="all"), closes.dropna(how="all")
    field = "Adj Close" if ("Adj Close" in raw.columns.get_level_values(0)) else "Close"
    prices = raw[field].copy()
    closes = raw["Close"].copy() if "Close" in raw.columns.get_level_values(0) else prices.copy()
    prices = prices.reindex(columns=[t for t in tickers if t in prices.columns])
    closes = closes.reindex(columns=[t for t in tickers if t in closes.columns])
    return prices.dropna(how="all"), closes.dropna(how="all")

def trailing_12m_distribution_yield(ticker: str, latest_close: float | None) -> tuple[float | None, float | None]:
    try:
        tk = yf.Ticker(ticker)
        divs = tk.dividends
        if divs is None or len(divs) == 0:
            return 0.0, 0.0
        now = divs.index.max()
        cutoff = now - pd.Timedelta(days=365)
        amount = float(divs[divs.index > cutoff].sum())
        if latest_close and latest_close > 0:
            return amount, amount / latest_close * 100
        return amount, None
    except Exception:
        return None, None

def _deep_find_expense(obj):
    candidates = []
    def walk(x, path=""):
        if isinstance(x, dict):
            for k, v in x.items():
                key = str(k)
                newp = f"{path}.{key}" if path else key
                if "expense" in key.lower() or "annual report expense" in key.lower():
                    candidates.append((newp, v))
                walk(v, newp)
        elif isinstance(x, pd.DataFrame):
            for idx in x.index:
                if "expense" in str(idx).lower():
                    try: candidates.append((f"{path}.{idx}", x.loc[idx]))
                    except Exception: pass
            for col in x.columns:
                if "expense" in str(col).lower():
                    try: candidates.append((f"{path}.{col}", x[col]))
                    except Exception: pass
    walk(obj)
    def to_number(v):
        if isinstance(v, pd.Series):
            vals = pd.to_numeric(v, errors="coerce").dropna()
            return float(vals.iloc[0]) if not vals.empty else None
        if isinstance(v, (int, float, np.number)) and pd.notna(v):
            return float(v)
        if isinstance(v, str):
            m = re.search(r"[-+]?\d*\.?\d+", v.replace(",", ""))
            return float(m.group()) if m else None
        return None
    for _, val in candidates:
        num = to_number(val)
        if num is None: continue
        pct = num * 100 if 0 <= num <= 1 else num
        if 0 <= pct <= 10: return pct
    return None

def fetch_fund_snapshot(ticker: str) -> dict:
    result = {"ticker": ticker, "name": ticker, "expense_ratio_pct": None, "aum": None, "category": None, "holdings": pd.DataFrame(columns=["etf", "holding", "weight"]), "sectors": {}, "holdings_scope": "없음", "error": None}
    try:
        tk = yf.Ticker(ticker)
        try:
            info = tk.info or {}
            result["name"] = info.get("shortName") or info.get("longName") or ticker
            result["aum"] = info.get("totalAssets") or info.get("marketCap")
            result["category"] = info.get("category") or info.get("fundFamily")
            for k in ["annualReportExpenseRatio", "expenseRatio"]:
                v = info.get(k)
                if isinstance(v, (int, float)) and v is not None:
                    result["expense_ratio_pct"] = v * 100 if v <= 1 else v
                    break
        except Exception:
            pass
        try:
            fd = tk.funds_data
            try: ov = fd.fund_overview
            except Exception: ov = None
            try: ops = fd.fund_operations
            except Exception: ops = None
            if result["expense_ratio_pct"] is None:
                result["expense_ratio_pct"] = _deep_find_expense({"overview": ov, "operations": ops})
            try:
                top = fd.top_holdings
                if isinstance(top, pd.DataFrame) and not top.empty:
                    tmp = top.copy().reset_index()
                    symbol_col = name_col = weight_col = None
                    for c in tmp.columns:
                        lc = str(c).lower()
                        if symbol_col is None and ("symbol" in lc or lc == "index"): symbol_col = c
                        if name_col is None and "name" in lc: name_col = c
                        if weight_col is None and ("holding percent" in lc or "weight" in lc or "percent" in lc): weight_col = c
                    if name_col is None: name_col = symbol_col
                    if weight_col is not None and name_col is not None:
                        h = pd.DataFrame({"etf": ticker, "holding": tmp[name_col].astype(str), "weight": pd.to_numeric(tmp[weight_col], errors="coerce")})
                        if not h["weight"].dropna().empty and h["weight"].dropna().max() <= 1: h["weight"] *= 100
                        result["holdings"] = h.dropna(subset=["weight"]).sort_values("weight", ascending=False)
                        result["holdings_scope"] = "Yahoo Top Holdings"
            except Exception:
                pass
            try:
                sec = fd.sector_weightings
                if isinstance(sec, dict):
                    result["sectors"] = {str(k): (float(v) * 100 if isinstance(v, (int, float)) and v <= 1 else float(v)) for k, v in sec.items() if isinstance(v, (int, float)) and pd.notna(v)}
            except Exception:
                pass
        except Exception:
            pass
    except Exception as e:
        result["error"] = str(e)
    return result

def normalize_holdings_csv(df: pd.DataFrame, fallback_etf: str | None = None) -> pd.DataFrame:
    aliases = {
        "etf": ["etf", "ticker", "fund", "fund_ticker", "etf명", "etf이름", "종목코드"],
        "holding": ["holding", "security", "name", "company", "holding_name", "구성종목", "종목명", "보유종목"],
        "weight": ["weight", "weight_pct", "weight_percent", "비중", "비중(%)", "편입비중", "보유비중"],
        "sector": ["sector", "industry", "섹터", "업종"],
        "country": ["country", "nation", "국가", "지역"],
    }
    def norm(s): return re.sub(r"\s+", "_", str(s).strip().lower())
    normalized = {norm(c): c for c in df.columns}
    rename = {}
    for standard, names in aliases.items():
        for name in names:
            if norm(name) in normalized:
                rename[normalized[norm(name)]] = standard
                break
    out = df.rename(columns=rename).copy()
    if "holding" not in out.columns or "weight" not in out.columns:
        raise ValueError("CSV에는 최소 '구성종목(holding)'과 '비중(weight)' 열이 필요합니다.")
    if "etf" not in out.columns: out["etf"] = fallback_etf or "ETF"
    out["etf"] = out["etf"].astype(str).str.strip().str.upper()
    out["holding"] = out["holding"].astype(str).str.strip()
    w = out["weight"].astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False).str.strip()
    out["weight"] = pd.to_numeric(w, errors="coerce")
    valid = out["weight"].dropna()
    if not valid.empty and valid.max() <= 1.0: out["weight"] *= 100
    keep = [c for c in ["etf", "holding", "weight", "sector", "country"] if c in out.columns]
    out = out[keep].dropna(subset=["weight"])
    out = out[out["holding"] != ""]
    agg = {"weight": "sum"}
    for c in ["sector", "country"]:
        if c in out.columns: agg[c] = lambda x: x.dropna().astype(str).iloc[0] if len(x.dropna()) else ""
    return out.groupby(["etf", "holding"], as_index=False).agg(agg)
