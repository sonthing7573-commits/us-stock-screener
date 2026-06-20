# -*- coding: utf-8 -*-
"""
FastAPI 웹 서버 - 미국 주식 추천 프로그램
브라우저에서 실시간으로 스크리닝 진행 상황과 결과 확인
"""

import sys
import math
import json
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

sys.path.insert(0, str(Path(__file__).parent))

app = FastAPI(title="미국 주식 분석 도구")
_executor = ThreadPoolExecutor(max_workers=2)

TEMPLATE = Path(__file__).parent / "templates" / "index.html"


def _safe(val):
    """NaN/Inf를 None으로 변환"""
    if val is None:
        return None
    try:
        if math.isnan(float(val)) or math.isinf(float(val)):
            return None
    except (TypeError, ValueError):
        pass
    return val


def _serialize_row(row, df_dict=None) -> dict:
    """DataFrame 행을 JSON 직렬화 가능한 dict로 변환"""
    fields = [
        "ticker", "name", "sector", "industry", "price", "market_cap",
        "pe", "forward_pe", "pb", "roe", "debt_to_equity", "current_ratio",
        "dividend_yield", "earnings_growth", "revenue_growth",
        "profit_margins", "peg", "ev_ebitda", "score", "met_count", "total_criteria",
    ]
    r = {f: _safe(row.get(f)) for f in fields}

    cr = row.get("criteria_results") or {}
    r["criteria"] = [
        {
            "name": name,
            "met": bool(res.get("met", False)),
            "value": _safe(res.get("value")),
            "min": _safe(res.get("min")),
            "max": _safe(res.get("max")),
            "format": res.get("format", ".2f"),
            "reason": res.get("reason", ""),
        }
        for name, res in cr.items()
    ]
    return r


@app.get("/", response_class=HTMLResponse)
async def index():
    return TEMPLATE.read_text(encoding="utf-8")


@app.get("/screen")
async def screen(
    strategy: str = Query("buffett"),
    top: int = Query(15),
    sector: str = Query(""),
    full: bool = Query(False),
):
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def do_screen():
        from strategies import STRATEGIES
        from screener import get_sp500_tickers, run_screener

        tickers = get_sp500_tickers()
        if not full:
            tickers = tickers[:100]

        if strategy == "all":
            _run_all(loop, queue, STRATEGIES, tickers, sector, top, run_screener)
        else:
            strat = STRATEGIES.get(strategy)
            if not strat:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "error", "message": f"알 수 없는 전략: {strategy}"},
                )
                loop.call_soon_threadsafe(queue.put_nowait, None)
                return

            total = len(tickers)
            found = [0]

            def cb(current, total_, ticker, found_count):
                found[0] = found_count
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "progress",
                        "current": current,
                        "total": total_,
                        "ticker": ticker,
                        "found": found_count,
                        "pct": round(current / total_ * 100) if total_ else 0,
                        "step_label": strat["name"],
                    },
                )

            df = run_screener(
                strat,
                tickers=tickers,
                sector_filter=sector or None,
                top_n=top,
                progress_callback=cb,
                use_tqdm=False,
            )

            results = [_serialize_row(row) for _, row in df.iterrows()] if not df.empty else []
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "done", "results": results, "strategy": strategy},
            )

        loop.call_soon_threadsafe(queue.put_nowait, None)

    def _run_all(loop, queue, STRATEGIES, tickers, sector, top, run_screener):
        all_scores: dict[str, dict] = {}
        all_data: dict[str, dict] = {}
        total_tickers = len(tickers)
        num_strats = len(STRATEGIES)

        for strat_idx, (strat_key, strat) in enumerate(STRATEGIES.items()):
            def make_cb(si, sname):
                def cb(current, total_, ticker, found_count):
                    overall = (si * total_tickers + current)
                    overall_total = num_strats * total_tickers
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {
                            "type": "progress",
                            "current": overall,
                            "total": overall_total,
                            "ticker": ticker,
                            "found": found_count,
                            "pct": round(overall / overall_total * 100),
                            "step_label": f"{sname} ({si+1}/{num_strats})",
                        },
                    )
                return cb

            df = run_screener(
                strat,
                tickers=tickers,
                sector_filter=sector or None,
                top_n=len(tickers),
                progress_callback=make_cb(strat_idx, strat["name"]),
                use_tqdm=False,
            )

            if df.empty:
                continue

            for _, row in df.iterrows():
                t = row["ticker"]
                if t not in all_data:
                    all_data[t] = {
                        f: _safe(row.get(f))
                        for f in ["ticker", "name", "sector", "industry",
                                  "price", "market_cap", "pe", "pb", "roe",
                                  "debt_to_equity", "profit_margins",
                                  "earnings_growth", "revenue_growth", "peg"]
                    }
                    all_scores[t] = {}
                all_scores[t][strat_key] = _safe(row.get("score")) or 0

        combined = []
        for t, scores in all_scores.items():
            avg = sum(scores.values()) / num_strats
            combined.append({
                **all_data[t],
                "score": round(avg, 1),
                "met_count": len(scores),
                "total_criteria": num_strats,
                "criteria": [
                    {
                        "name": STRATEGIES[k]["name"],
                        "met": k in scores,
                        "value": scores.get(k),
                        "min": 0,
                        "max": None,
                        "format": ".0f",
                        "reason": "" if k in scores else "기준 미충족",
                    }
                    for k in STRATEGIES
                ],
            })

        combined.sort(key=lambda x: x["score"], reverse=True)
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "done", "results": combined[:top], "strategy": "all"},
        )

    loop.run_in_executor(_executor, do_screen)

    async def event_stream():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    yield 'data: {"type":"error","message":"타임아웃"}\n\n'
                    break
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import webbrowser, threading, uvicorn

    def open_browser():
        import time; time.sleep(1)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)
