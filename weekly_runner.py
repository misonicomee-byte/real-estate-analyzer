#!/usr/bin/env python3
"""
週次バッチ実行スクリプト
前回の続きから指定数の企業を解析
"""

import argparse
import json
import os
from pathlib import Path
from datetime import datetime

from topix500 import TOPIX500Fetcher
from main import RealEstateAnalyzer


def get_progress(results_file: Path) -> dict:
    """進捗状況を取得"""
    if results_file.exists():
        with open(results_file, "r", encoding="utf-8") as f:
            results = json.load(f)

        analyzed_codes = {r["stock_code"] for r in results if not r.get("error")}
        return {
            "results": results,
            "analyzed_codes": analyzed_codes,
            "count": len(analyzed_codes)
        }

    return {
        "results": [],
        "analyzed_codes": set(),
        "count": 0
    }


def run_batch(batch_size: int = 10, output_dir: str = "./output"):
    """バッチ実行"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    results_file = output_path / "analysis_results.json"

    # 進捗を取得
    progress = get_progress(results_file)
    print(f"現在の進捗: {progress['count']}社 解析済み")

    # TOPIX500銘柄を取得
    fetcher = TOPIX500Fetcher()
    stocks = fetcher.fetch_topix500()
    edinet_mapping = fetcher.get_edinet_code_mapping()

    # 未解析の企業をフィルタ
    pending_stocks = [
        s for s in stocks
        if s["code"] not in progress["analyzed_codes"]
    ]

    print(f"未解析: {len(pending_stocks)}社")

    if not pending_stocks:
        print("全企業の解析が完了しています！")
        return

    # 今回解析する企業
    batch = pending_stocks[:batch_size]
    print(f"今回の解析対象: {len(batch)}社")

    # 解析実行
    analyzer = RealEstateAnalyzer(output_dir=output_dir)

    results = progress["results"].copy()

    for stock in batch:
        stock_code = stock["code"]
        company_name = stock["name"]
        edinet_code = stock.get("edinet_code") or edinet_mapping.get(stock_code)

        if not edinet_code:
            results.append({
                "stock_code": stock_code,
                "company_name": company_name,
                "error": "EDINETコードが見つかりません",
                "analyzed_at": datetime.now().isoformat()
            })
            continue

        result = analyzer.analyze_single_company(stock_code, company_name, edinet_code)
        results.append(result)

        # 中間保存
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    # 最終結果を保存
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # サマリー出力
    successful = [r for r in results if not r.get("error")]
    print(f"\n{'='*50}")
    print(f"バッチ完了")
    print(f"  今回: {len(batch)}社")
    print(f"  累計: {len(successful)}社 / {len(stocks)}社")
    print(f"  残り: {len(stocks) - len(successful)}社")
    print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(description="週次バッチ実行")
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=10,
        help="1回あたりの解析企業数（デフォルト: 10）"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="./output",
        help="出力ディレクトリ"
    )

    args = parser.parse_args()
    run_batch(batch_size=args.batch_size, output_dir=args.output)


if __name__ == "__main__":
    main()
