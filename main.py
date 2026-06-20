# -*- coding: utf-8 -*-
"""
미국 주식 추천 프로그램
유명 투자자들의 기준으로 S&P 500 종목을 스크리닝
"""

import sys
import io
import argparse
import logging

# Windows 터미널 UTF-8 출력 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, IntPrompt, Confirm
from rich import box
from rich.columns import Columns
from rich.style import Style
import pandas as pd

from strategies import STRATEGIES, FIELD_LABELS
from screener import get_sp500_tickers, run_screener

console = Console()

SECTORS = [
    "Technology", "Healthcare", "Financials", "Consumer Discretionary",
    "Industrials", "Communication Services", "Consumer Staples",
    "Energy", "Utilities", "Real Estate", "Materials",
]


def format_value(val, fmt: str) -> str:
    if val is None:
        return "[dim]N/A[/dim]"
    try:
        if fmt == ".1%":
            return f"{val:.1%}"
        elif fmt == ".2f":
            return f"{val:.2f}"
        elif fmt == ".1f":
            return f"{val:.1f}"
        return str(val)
    except Exception:
        return str(val)


def format_market_cap(cap) -> str:
    if cap is None:
        return "N/A"
    if cap >= 1e12:
        return f"${cap/1e12:.1f}T"
    elif cap >= 1e9:
        return f"${cap/1e9:.1f}B"
    elif cap >= 1e6:
        return f"${cap/1e6:.1f}M"
    return f"${cap:.0f}"


def print_header():
    console.print()
    header = Panel(
        Text.assemble(
            ("  미국 주식 추천 프로그램  ", "bold white on dark_blue"),
            "\n",
            ("유명 투자자 기준 기반 S&P 500 스크리너", "dim"),
        ),
        border_style="blue",
        padding=(0, 2),
    )
    console.print(header)
    console.print()


def print_strategy_menu():
    console.print("[bold]▶ 투자 전략 선택[/bold]")
    console.print()

    panels = []
    for key, s in STRATEGIES.items():
        lines = [
            f"[bold {s['color']}]{s['name']}[/bold {s['color']}]\n",
            f"[dim]{s['korean_name']} | {s['style']}[/dim]\n\n",
            f"{s['description']}\n\n",
            "[dim]주요 기준:[/dim]\n",
        ]
        for c in s["criteria"][:3]:
            lines.append(f"  • {c['description']}\n")
        if len(s["criteria"]) > 3:
            lines.append(f"  [dim]... +{len(s['criteria'])-3}개 기준[/dim]\n")

        panels.append(Panel(
            "".join(lines),
            title=f"[{s['color']}][{list(STRATEGIES.keys()).index(key)+1}] {key}[/{s['color']}]",
            border_style=s["color"],
            width=38,
        ))

    # 2열로 출력
    for i in range(0, len(panels), 2):
        row = panels[i:i+2]
        console.print(Columns(row, equal=True))

    console.print(Panel(
        "[bold green][6] all[/bold green]  —  모든 전략을 동시에 실행하여 종합 점수로 비교",
        border_style="green",
    ))
    console.print()


def print_criteria_table(strategy: dict):
    color = strategy["color"]
    table = Table(
        title=f"[bold {color}]{strategy['name']} ({strategy['korean_name']}) 투자 기준[/bold {color}]",
        box=box.ROUNDED,
        border_style=color,
        show_lines=True,
    )
    table.add_column("지표", style="bold", width=12)
    table.add_column("기준", width=22)
    table.add_column("가중치", justify="center", width=8)

    for c in strategy["criteria"]:
        parts = []
        if c["min"] is not None and c["min"] != 0:
            parts.append(f"≥ {c['min']:.0%}" if "%" in c.get("format","") or c["field"] in ("roe","profit_margins","earnings_growth","revenue_growth","dividend_yield") else f"≥ {c['min']}")
        if c["max"] is not None:
            parts.append(f"≤ {c['max']:.0%}" if "%" in c.get("format","") or c["field"] in ("roe","profit_margins","earnings_growth","revenue_growth","dividend_yield") else f"≤ {c['max']}")
        criterion_str = " & ".join(parts) if parts else "—"

        weight_bar = "★" * int(c["weight"]) + ("½" if c["weight"] % 1 else "")
        table.add_row(c["name"], criterion_str, f"[yellow]{weight_bar}[/yellow]")

    console.print(table)
    console.print()


def print_results(df: pd.DataFrame, strategy: dict):
    if df.empty:
        console.print("[red]조건을 충족하는 종목이 없습니다.[/red]")
        return

    color = strategy["color"]
    console.print()
    console.print(Panel(
        f"[bold {color}]{strategy['name']} ({strategy['korean_name']}) 추천 종목[/bold {color}]  "
        f"[dim]| {strategy['style']} | {len(df)}개 종목[/dim]",
        border_style=color,
    ))

    # 메인 결과 테이블
    table = Table(
        box=box.SIMPLE_HEAD,
        border_style="dim",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("순위", justify="center", width=4, style="dim")
    table.add_column("티커", style="bold cyan", width=7)
    table.add_column("기업명", width=22)
    table.add_column("섹터", width=18, style="dim")
    table.add_column("점수", justify="center", width=7)
    table.add_column("충족", justify="center", width=6)
    table.add_column("현재가", justify="right", width=9)
    table.add_column("시가총액", justify="right", width=9)
    table.add_column("PER", justify="right", width=7)
    table.add_column("PBR", justify="right", width=7)
    table.add_column("ROE", justify="right", width=7)
    table.add_column("D/E%", justify="right", width=7)
    table.add_column("순이익률", justify="right", width=8)

    for rank, row in df.iterrows():
        score = row.get("score", 0)
        met = row.get("met_count", 0)
        total = row.get("total_criteria", 1)

        # 점수에 따른 색상
        if score >= 80:
            score_style = "bold green"
        elif score >= 60:
            score_style = "yellow"
        else:
            score_style = "dim"

        met_ratio = met / total
        met_style = "green" if met_ratio >= 0.8 else ("yellow" if met_ratio >= 0.6 else "dim")

        pe_val = row.get("pe")
        pb_val = row.get("pb")
        roe_val = row.get("roe")
        de_val = row.get("debt_to_equity")
        pm_val = row.get("profit_margins")

        table.add_row(
            f"{rank + 1}",
            row.get("ticker", ""),
            (row.get("name", "")[:20] + "..") if len(row.get("name","")) > 22 else row.get("name",""),
            (row.get("sector","")[:16] + "..") if len(row.get("sector","")) > 18 else row.get("sector",""),
            f"[{score_style}]{score:.0f}점[/{score_style}]",
            f"[{met_style}]{met}/{total}[/{met_style}]",
            f"${row.get('price', 0):.2f}" if row.get("price") else "N/A",
            format_market_cap(row.get("market_cap")),
            f"{pe_val:.1f}" if pe_val else "N/A",
            f"{pb_val:.2f}" if pb_val else "N/A",
            f"{roe_val:.1%}" if roe_val else "N/A",
            f"{de_val:.1f}" if de_val else "N/A",
            f"{pm_val:.1%}" if pm_val else "N/A",
        )

    console.print(table)


def print_detail(row: pd.Series, strategy: dict):
    """종목 상세 분석 출력"""
    color = strategy["color"]
    ticker = row["ticker"]
    criteria_results = row.get("criteria_results", {})

    console.print()
    console.print(Panel(
        f"[bold]{ticker}[/bold] — {row.get('name','')}\n"
        f"[dim]{row.get('sector','')} | {row.get('industry','')}[/dim]",
        title=f"[{color}]상세 분석[/{color}]",
        border_style=color,
    ))

    detail_table = Table(box=box.ROUNDED, show_lines=True, border_style="dim")
    detail_table.add_column("투자 기준", width=16)
    detail_table.add_column("현재 값", justify="right", width=12)
    detail_table.add_column("기준", width=18)
    detail_table.add_column("결과", justify="center", width=8)

    for c in strategy["criteria"]:
        name = c["name"]
        result = criteria_results.get(name, {})
        val = result.get("value")
        met = result.get("met", False)
        fmt = result.get("format", ".2f")

        val_str = format_value(val, fmt)

        min_v = result.get("min")
        max_v = result.get("max")
        parts = []
        if min_v is not None and min_v != 0:
            min_str = f"{min_v:.1%}" if fmt == ".1%" else f"{min_v}"
            parts.append(f"≥ {min_str}")
        if max_v is not None:
            max_str = f"{max_v:.1%}" if fmt == ".1%" else f"{max_v}"
            parts.append(f"≤ {max_str}")
        crit_str = " & ".join(parts) if parts else "—"

        if result.get("reason") == "데이터 없음":
            status = "[dim]N/A[/dim]"
        elif met:
            status = "[bold green]✓ 충족[/bold green]"
        else:
            status = "[red]✗ 미충족[/red]"

        detail_table.add_row(name, val_str, crit_str, status)

    console.print(detail_table)


def run_all_strategies(tickers: list[str], top_n: int):
    """모든 전략 실행 후 종합 비교"""
    all_results = {}

    for key, strategy in STRATEGIES.items():
        console.print(f"\n[bold {strategy['color']}]▶ {strategy['name']} 전략 실행 중...[/bold {strategy['color']}]")
        df = run_screener(strategy, tickers=tickers, top_n=50)
        if not df.empty:
            all_results[key] = df.set_index("ticker")["score"].to_dict()

    if not all_results:
        console.print("[red]결과 없음[/red]")
        return

    # 각 전략에서 언급된 모든 종목 수집
    all_tickers = set()
    for scores in all_results.values():
        all_tickers.update(scores.keys())

    # 종합 점수 계산 (각 전략 점수 합산)
    combined = []
    for t in all_tickers:
        scores = {k: v.get(t, 0) for k, v in all_results.items()}
        avg = sum(scores.values()) / len(STRATEGIES)
        count = sum(1 for s in scores.values() if s > 0)
        combined.append({
            "ticker": t,
            "avg_score": round(avg, 1),
            "strategy_count": count,
            **{f"{k}_score": v for k, v in scores.items()},
        })

    result_df = pd.DataFrame(combined).sort_values("avg_score", ascending=False).head(top_n)

    console.print()
    console.print(Panel("[bold gold1]전략 종합 비교 — 최고 추천 종목[/bold gold1]", border_style="gold1"))

    table = Table(box=box.SIMPLE_HEAD, padding=(0, 1))
    table.add_column("순위", justify="center", width=4)
    table.add_column("티커", style="bold cyan", width=8)
    table.add_column("종합점수", justify="center", width=9)
    table.add_column("전략수", justify="center", width=6)
    for k, s in STRATEGIES.items():
        table.add_column(s["korean_name"][:4], justify="center", width=8, style=s["color"])

    for i, (_, row) in enumerate(result_df.iterrows()):
        avg = row["avg_score"]
        style = "bold green" if avg >= 60 else ("yellow" if avg >= 40 else "dim")

        score_cells = []
        for k in STRATEGIES.keys():
            s = row.get(f"{k}_score", 0)
            score_cells.append(f"{s:.0f}점" if s > 0 else "[dim]—[/dim]")

        table.add_row(
            str(i + 1),
            row["ticker"],
            f"[{style}]{avg:.0f}점[/{style}]",
            str(int(row["strategy_count"])),
            *score_cells,
        )

    console.print(table)


def interactive_mode():
    print_header()

    # 전략 선택
    print_strategy_menu()
    strategy_keys = list(STRATEGIES.keys())

    choice = Prompt.ask(
        "전략 선택 (1-6 또는 이름)",
        choices=["1", "2", "3", "4", "5", "6"] + strategy_keys + ["all"],
        default="1",
    )

    # 번호로 선택한 경우 변환
    if choice.isdigit():
        idx = int(choice) - 1
        if idx < len(strategy_keys):
            choice = strategy_keys[idx]
        else:
            choice = "all"

    # 종목 수
    top_n = IntPrompt.ask("\n추천 종목 수", default=15)

    # 섹터 필터
    use_sector = Confirm.ask("\n특정 섹터만 검색할까요?", default=False)
    sector_filter = None
    if use_sector:
        console.print("\n섹터 목록:")
        for i, s in enumerate(SECTORS, 1):
            console.print(f"  [{i}] {s}")
        sector_idx = IntPrompt.ask("섹터 번호", default=0)
        if 1 <= sector_idx <= len(SECTORS):
            sector_filter = SECTORS[sector_idx - 1]

    # 종목 수 제한 (빠른 실행)
    use_full = Confirm.ask(
        "\nS&P 500 전체(약 500종목, 수분 소요) 스캔? [No = 상위 100종목만]",
        default=False,
    )

    console.print("\n[bold]S&P 500 티커 목록 로딩 중...[/bold]")
    tickers = get_sp500_tickers()

    if not use_full:
        tickers = tickers[:100]  # 시가총액 상위 순

    console.print(f"[green]총 {len(tickers)}개 종목 분석 시작[/green]\n")

    if choice == "all":
        run_all_strategies(tickers, top_n)
    else:
        strategy = STRATEGIES[choice]
        console.print()
        print_criteria_table(strategy)

        df = run_screener(
            strategy,
            tickers=tickers,
            sector_filter=sector_filter,
            top_n=top_n,
        )

        print_results(df, strategy)

        # 상세 분석
        if not df.empty:
            show_detail = Confirm.ask(
                "\n특정 종목의 상세 분석을 볼까요?", default=False
            )
            if show_detail:
                ticker_input = Prompt.ask("티커 입력 (예: AAPL)").upper()
                match = df[df["ticker"] == ticker_input]
                if not match.empty:
                    print_detail(match.iloc[0], strategy)
                else:
                    console.print("[red]결과에 없는 종목입니다.[/red]")

    console.print("\n[dim]※ 본 프로그램은 투자 참고용이며 투자 권유가 아닙니다.[/dim]\n")


def cli_mode(args):
    """커맨드라인 인수 모드"""
    print_header()

    strategy_key = args.strategy
    if strategy_key not in STRATEGIES and strategy_key != "all":
        console.print(f"[red]알 수 없는 전략: {strategy_key}[/red]")
        console.print(f"사용 가능: {', '.join(STRATEGIES.keys())}, all")
        sys.exit(1)

    console.print(f"[dim]S&P 500 티커 로딩...[/dim]")
    tickers = get_sp500_tickers()
    if not args.full:
        tickers = tickers[:100]
    console.print(f"[green]{len(tickers)}개 종목 분석[/green]\n")

    if strategy_key == "all":
        run_all_strategies(tickers, args.top)
    else:
        strategy = STRATEGIES[strategy_key]
        print_criteria_table(strategy)
        df = run_screener(
            strategy,
            tickers=tickers,
            sector_filter=args.sector,
            top_n=args.top,
        )
        print_results(df, strategy)

    console.print("\n[dim]※ 투자 참고용이며 투자 권유가 아닙니다.[/dim]\n")


def main():
    parser = argparse.ArgumentParser(
        description="미국 주식 추천 프로그램 - 유명 투자자 기준 스크리너",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
전략 목록:
  buffett     Warren Buffett  (Quality Value)
  graham      Benjamin Graham (Deep Value)
  lynch       Peter Lynch     (GARP)
  greenblatt  Joel Greenblatt (Magic Formula)
  fisher      Philip Fisher   (Growth)
  all         모든 전략 종합 비교

예시:
  python main.py                          # 대화형 모드
  python main.py -s buffett               # 버핏 전략, 상위 100종목
  python main.py -s graham -t 20 --full  # 그레이엄 전략, S&P 500 전체
  python main.py -s lynch --sector Technology
  python main.py -s all -t 10
""",
    )
    parser.add_argument(
        "-s", "--strategy",
        choices=list(STRATEGIES.keys()) + ["all"],
        default=None,
        help="투자 전략 선택",
    )
    parser.add_argument("-t", "--top", type=int, default=15, help="추천 종목 수 (기본 15)")
    parser.add_argument("--sector", type=str, default=None, help="섹터 필터 (예: Technology)")
    parser.add_argument("--full", action="store_true", help="S&P 500 전체 스캔 (느림)")

    args = parser.parse_args()

    if args.strategy is None:
        interactive_mode()
    else:
        cli_mode(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
