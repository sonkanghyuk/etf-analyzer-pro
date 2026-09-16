from __future__ import annotations

from functools import lru_cache
import re

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import yfinance as yf


def _name_key(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", str(text)).lower()


def _has_hangul(text: str) -> bool:
    return bool(re.search(r"[가-힣]", str(text)))


@lru_cache(maxsize=1)
def get_korean_etf_catalog() -> pd.DataFrame:
    """현재 국내 상장 ETF의 Symbol/Name 목록을 가져온다."""
    last_error = None
    for loader in (
        lambda: fdr.EtfListing("KR"),
        lambda: fdr.StockListing("ETF/KR"),
    ):
        try:
            df = loader()
            if isinstance(df, pd.DataFrame) and not df.empty and {"Symbol", "Name"}.issubset(df.columns):
                out = df[["Symbol", "Name"]].copy()
                out["Symbol"] = (
                    out["Symbol"].astype(str)
                    .str.extract(r"(\d+)", expand=False)
                    .str.zfill(6)
                )
                out["Name"] = out["Name"].astype(str).str.strip()
                out = out.dropna(subset=["Symbol", "Name"]).drop_duplicates("Symbol")
                out["name_key"] = out["Name"].map(_name_key)
                return out.reset_index(drop=True)
        except Exception as e:
            last_error = e
    raise RuntimeError(f"국내 ETF 목록을 불러오지 못했습니다: {last_error}")


def search_korean_etf_names(query: str, limit: int = 10) -> pd.DataFrame:
    """한글 ETF명 부분검색 결과를 반환한다."""
    q = _name_key(query)
    if not q:
        return pd.DataFrame(columns=["Symbol", "Name"])
    catalog = get_korean_etf_catalog()
    found = catalog[catalog["name_key"].str.contains(q, na=False)].copy()
    if found.empty:
        return found[["Symbol", "Name"]]
    found["exact"] = found["name_key"].eq(q)
    found["name_len"] = found["Name"].str.len()
    found = found.sort_values(["exact", "name_len", "Name"], ascending=[False, True, True])
    return found[["Symbol", "Name"]].head(limit).reset_index(drop=True)


def resolve_market_ticker(ticker: str) -> str:
    """미국 티커/국내 6자리 코드/국내 한글 ETF명을 Yahoo Finance 티커로 변환."""
    raw = str(ticker).strip()
    upper = raw.upper().replace("KRX:", "").replace("KSE:", "")

    if re.fullmatch(r"\d{6}", upper):
        return f"{upper}.KS"
    if re.fullmatch(r"\d{6}\.KS", upper):
        return upper

    if not _has_hangul(raw):
        return upper

    catalog = get_korean_etf_catalog()
    q = _name_key(raw)

    exact = catalog[catalog["name_key"] == q]
    if len(exact) == 1:
        return f"{exact.iloc[0]['Symbol']}.KS"

    contains = catalog[catalog["name_key"].str.contains(q, na=False)]
    if len(contains) == 1:
        return f"{contains.iloc[0]['Symbol']}.KS"

    if len(contains) > 1:
        candidates = ", ".join(
            f"{row.Name}({row.Symbol})" for row in contains.head(8).itertuples(index=False)
        )
        raise ValueError(
            f"'{raw}' 검색 결과가 여러 개입니다. ETF명을 더 정확히 입력하거나 6자리 코드를 사용하세요. 후보: {candidates}"
        )

    raise ValueError(
        f"'{raw}'에 해당하는 국내 상장 ETF를 찾지 못했습니다. 정확한 ETF명 또는 6자리 종목코드를 입력하세요."
    )


def _catalog_name_for_yahoo_ticker(yahoo_ticker: str) -> str | None:
    m = re.fullmatch(r"(\d{6})\.KS", str(yahoo_ticker).upper())
    if not m:
        return None
    try:
        catalog = get_korean_etf_catalog()
        hit = catalog[catalog["Symbol"] == m.group(1)]
        if not hit.empty:
            return str(hit.iloc[0]["Name"])
    except Exception:
        pass
    return None


def download_prices(tickers: list[str], start, end) -> tuple[pd.DataFrame, pd.DataFrame]:
    """한글 ETF명도 지원하는 가격 다운로드."""
    if not tickers:
        return pd.DataFrame(), pd.DataFrame()

    pairs = [(t, resolve_market_ticker(t)) for t in tickers]
    resolved = list(dict.fromkeys(r for _, r in pairs))

    raw = yf.download(
        tickers=resolved,
        start=start,
        end=end,
        auto_adjust=False,
        actions=True,
        progress=False,
        group_by="column",
        threads=True,
        multi_level_index=True,
    )
    if raw is None or raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        fields = raw.columns.get_level_values(0)
        price_field = "Adj Close" if "Adj Close" in fields else "Close"
        p = raw[price_field].copy()
        c = raw["Close"].copy() if "Close" in fields else p.copy()
        if isinstance(p, pd.Series):
            p = p.to_frame(name=resolved[0])
        if isinstance(c, pd.Series):
            c = c.to_frame(name=resolved[0])
    else:
        price_field = "Adj Close" if "Adj Close" in raw.columns else "Close"
        p = raw[[price_field]].copy()
        c = raw[["Close"]].copy() if "Close" in raw.columns else p.copy()
        p.columns = [resolved[0]]
        c.columns = [resolved[0]]

    prices = pd.DataFrame(index=p.index)
    closes = pd.DataFrame(index=c.index)
    for original, yahoo_symbol in pairs:
        if yahoo_symbol in p.columns:
            prices[original] = p[yahoo_symbol]
        if yahoo_symbol in c.columns:
            closes[original] = c[yahoo_symbol]

    return prices.dropna(how="all"), closes.dropna(how="all")


def trailing_12m_distribution_yield(ticker: str, latest_close: float | None) -> tuple[float | None, float | None]:
    try:
        yahoo_ticker = resolve_market_ticker(ticker)
        tk = yf.Ticker(yahoo_ticker)
        divs = tk.dividends
        if divs is None or len(divs) == 0:
            return 0.0, 0.0

        tz = getattr(divs.index, "tz", None)
        now = pd.Timestamp.now(tz=tz)
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
                    try:
                        candidates.append((f"{path}.{idx}", x.loc[idx]))
                    except Exception:
                        pass
            for col in x.columns:
                if "expense" in str(col).lower():
                    try:
                        candidates.append((f"{path}.{col}", x[col]))
                    except Exception:
                        pass

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
        if num is None:
            continue
        pct = num * 100 if 0 <= num <= 1 else num
        if 0 <= pct <= 10:
            return pct
    return None


def fetch_fund_snapshot(ticker: str) -> dict:
    original_ticker = ticker
    try:
        yahoo_ticker = resolve_market_ticker(ticker)
    except Exception as e:
        return {
            "ticker": original_ticker,
            "name": original_ticker,
            "expense_ratio_pct": None,
            "aum": None,
            "category": None,
            "holdings": pd.DataFrame(columns=["etf", "holding", "weight"]),
            "sectors": {},
            "holdings_scope": "없음",
            "error": str(e),
        }

    korean_name = _catalog_name_for_yahoo_ticker(yahoo_ticker)
    result = {
        "ticker": original_ticker,
        "name": korean_name or original_ticker,
        "expense_ratio_pct": None,
        "aum": None,
        "category": None,
        "holdings": pd.DataFrame(columns=["etf", "holding", "weight"]),
        "sectors": {},
        "holdings_scope": "없음",
        "error": None,
    }

    try:
        tk = yf.Ticker(yahoo_ticker)

        try:
            info = tk.info or {}
            if not korean_name:
                result["name"] = info.get("shortName") or info.get("longName") or original_ticker
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
            try:
                ov = fd.fund_overview
            except Exception:
                ov = None
            try:
                ops = fd.fund_operations
            except Exception:
                ops = None

            if result["expense_ratio_pct"] is None:
                result["expense_ratio_pct"] = _deep_find_expense({"overview": ov, "operations": ops})

            try:
                top = fd.top_holdings
                if isinstance(top, pd.DataFrame) and not top.empty:
                    tmp = top.copy().reset_index()
                    symbol_col = name_col = weight_col = None
                    for col in tmp.columns:
                        lc = str(col).lower()
                        if symbol_col is None and ("symbol" in lc or lc == "index"):
                            symbol_col = col
                        if name_col is None and "name" in lc:
                            name_col = col
                        if weight_col is None and ("holding percent" in lc or "weight" in lc or "percent" in lc):
                            weight_col = col

                    if name_col is None:
                        name_col = symbol_col
                    if weight_col is not None and name_col is not None:
                        h = pd.DataFrame({
                            "etf": original_ticker,
                            "holding": tmp[name_col].astype(str),
                            "weight": pd.to_numeric(tmp[weight_col], errors="coerce"),
                        })
                        valid = h["weight"].dropna()
                        if not valid.empty and valid.max() <= 1:
                            h["weight"] *= 100
                        result["holdings"] = h.dropna(subset=["weight"]).sort_values("weight", ascending=False)
                        result["holdings_scope"] = "Yahoo Top Holdings"
            except Exception:
                pass

            try:
                sec = fd.sector_weightings
                if isinstance(sec, dict):
                    result["sectors"] = {
                        str(k): (float(v) * 100 if isinstance(v, (int, float)) and v <= 1 else float(v))
                        for k, v in sec.items()
                        if isinstance(v, (int, float)) and pd.notna(v)
                    }
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

    def norm(s):
        return re.sub(r"\s+", "_", str(s).strip().lower())

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
    if "etf" not in out.columns:
        out["etf"] = fallback_etf or "ETF"

    out["etf"] = out["etf"].astype(str).str.strip().str.upper()
    out["holding"] = out["holding"].astype(str).str.strip()
    w = (
        out["weight"].astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    out["weight"] = pd.to_numeric(w, errors="coerce")
    valid = out["weight"].dropna()
    if not valid.empty and valid.max() <= 1.0:
        out["weight"] *= 100

    keep = [c for c in ["etf", "holding", "weight", "sector", "country"] if c in out.columns]
    out = out[keep].dropna(subset=["weight"])
    out = out[out["holding"] != ""]

    agg = {"weight": "sum"}
    for c in ["sector", "country"]:
        if c in out.columns:
            agg[c] = lambda x: x.dropna().astype(str).iloc[0] if len(x.dropna()) else ""

    return out.groupby(["etf", "holding"], as_index=False).agg(agg)
