"""
주식 스크리닝 엔진
S&P 500 종목을 가져와 투자 기준에 따라 필터링하고 점수를 매김
"""

import yfinance as yf
import pandas as pd
import time
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def get_sp500_tickers() -> list[str]:
    """Wikipedia에서 S&P 500 티커 목록 가져오기"""
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        )
        tickers = tables[0]["Symbol"].tolist()
        return [t.replace(".", "-") for t in tickers]
    except Exception as e:
        logger.error(f"S&P 500 로드 실패: {e}")
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
            "UNH", "JNJ", "V", "XOM", "JPM", "PG", "HD", "CVX", "MA", "ABBV",
            "MRK", "LLY", "KO", "PEP", "COST", "BAC", "MCD", "TMO", "CSCO",
            "ABT", "WMT", "ACN", "DHR", "TXN", "NEE", "BMY", "RTX", "PM",
            "ORCL", "INTC", "HON", "QCOM", "IBM", "SBUX", "GE", "CAT", "DE",
            "MMM", "GS", "BLK", "AXP", "SPGI", "AMAT", "LRCX", "KLAC", "MCHP",
            "ADI", "REGN", "GILD", "AMGN", "VRTX", "ISRG", "SYK", "BSX", "MDT",
            "ZTS", "CI", "HUM", "CVS", "MCK", "ADP", "PAYX", "FIS", "FISV",
        ]


def get_stock_data(ticker: str) -> Optional[dict]:
    """단일 종목의 재무 데이터 조회"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or info.get("quoteType") not in ("EQUITY", "ETF"):
            return None

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price:
            return None

        return {
            "ticker": ticker,
            "name": info.get("longName", ticker),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "price": price,
            "market_cap": info.get("marketCap"),
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "dividend_yield": info.get("dividendYield"),
            "earnings_growth": info.get("earningsGrowth"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margins": info.get("profitMargins"),
            "peg": info.get("pegRatio"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
        }
    except Exception as e:
        logger.debug(f"{ticker} 조회 실패: {e}")
        return None


def score_stock(stock_data: dict, criteria: list[dict]) -> tuple[float, dict]:
    """주식을 기준에 따라 점수 계산"""
    total_weight = sum(c["weight"] for c in criteria)
    earned_weight = 0.0
    criterion_results = {}

    for criterion in criteria:
        field = criterion["field"]
        val = stock_data.get(field)
        min_val = criterion.get("min")
        max_val = criterion.get("max")
        weight = criterion["weight"]
        name = criterion["name"]

        if val is None:
            criterion_results[name] = {"met": False, "value": None, "reason": "데이터 없음"}
            continue

        met = True
        if min_val is not None and val < min_val:
            met = False
        if max_val is not None and val > max_val:
            met = False

        if met:
            bonus = 1.0
            if min_val is not None and min_val != 0 and val > min_val:
                bonus = min(1.5, 1.0 + (val / min_val - 1.0) * 0.25)
            elif max_val is not None and max_val != 0 and val < max_val:
                bonus = min(1.5, 1.0 + (1.0 - val / max_val) * 0.5)
            earned_weight += weight * bonus

        criterion_results[name] = {
            "met": met,
            "value": val,
            "min": min_val,
            "max": max_val,
            "format": criterion.get("format", ".2f"),
        }

    score = (earned_weight / total_weight) * 100 if total_weight > 0 else 0
    return round(score, 1), criterion_results


def run_screener(
    strategy: dict,
    tickers: Optional[list[str]] = None,
    sector_filter: Optional[str] = None,
    top_n: int = 20,
    delay: float = 0.3,
    progress_callback: Optional[Callable] = None,
    use_tqdm: bool = True,
) -> pd.DataFrame:
    """전략에 따라 주식 스크리닝 실행"""
    if tickers is None:
        tickers = get_sp500_tickers()

    criteria = strategy["criteria"]
    results = []
    total = len(tickers)
    found_count = 0

    pbar = None
    if use_tqdm:
        from tqdm import tqdm
        pbar = tqdm(tickers, desc="  분석 중", unit="종목", ncols=80)
        ticker_iter = pbar
    else:
        ticker_iter = tickers

    for current, ticker in enumerate(ticker_iter, 1):
        if pbar:
            pbar.set_postfix({"현재": ticker})

        data = get_stock_data(ticker)
        if data is None:
            if progress_callback:
                progress_callback(current, total, ticker, found_count)
            time.sleep(delay * 0.5)
            continue

        if sector_filter and data.get("sector", "").lower() != sector_filter.lower():
            if progress_callback:
                progress_callback(current, total, ticker, found_count)
            continue

        score, criterion_results = score_stock(data, criteria)
        met_count = sum(1 for v in criterion_results.values() if v.get("met"))

        if met_count < len(criteria) * 0.4:
            if progress_callback:
                progress_callback(current, total, ticker, found_count)
            time.sleep(delay * 0.3)
            continue

        found_count += 1
        results.append({
            **data,
            "score": score,
            "met_count": met_count,
            "total_criteria": len(criteria),
            "criteria_results": criterion_results,
        })

        if progress_callback:
            progress_callback(current, total, ticker, found_count)

        time.sleep(delay)

    if pbar:
        pbar.close()

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
    return df
