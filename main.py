#!/usr/bin/env python3
"""
不動産含み益解析ツール
TOPIX500企業の有価証券報告書から不動産情報を抽出し、
公示地価と比較して含み益を可視化する
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from tqdm import tqdm
from dotenv import load_dotenv

from topix500 import TOPIX500Fetcher
from edinet_api import AnnualReportFetcher
from claude_parser import PropertyExtractor, PropertyAnalyzer
from land_price import ValueEstimator
from map_generator import MapGenerator


# 環境変数を読み込み
load_dotenv()


class RealEstateAnalyzer:
    """不動産含み益解析のメインクラス"""

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        edinet_api_key: Optional[str] = None,
        output_dir: str = "./output"
    ):
        self.anthropic_api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.edinet_api_key = edinet_api_key or os.environ.get("EDINET_API_KEY")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 各モジュールの初期化
        self.topix_fetcher = TOPIX500Fetcher()
        self.report_fetcher = AnnualReportFetcher(self.edinet_api_key)
        self.property_extractor = PropertyExtractor(self.anthropic_api_key)
        self.value_estimator = ValueEstimator()
        self.map_generator = MapGenerator()

    def analyze_single_company(
        self,
        stock_code: str,
        company_name: str,
        edinet_code: str
    ) -> Dict:
        """
        単一企業の不動産含み益を解析

        Returns:
            {
                "stock_code": "4746",
                "company_name": "東計電算",
                "total_book_value": 500,
                "total_estimated_value": 1500,
                "total_unrealized_gain": 1000,
                "properties": [...],
                "map_path": "output/4746_map.html"
            }
        """
        print(f"\n{'='*50}")
        print(f"解析開始: {company_name} ({stock_code})")
        print(f"{'='*50}")

        result = {
            "stock_code": stock_code,
            "company_name": company_name,
            "edinet_code": edinet_code,
            "analyzed_at": datetime.now().isoformat(),
            "total_book_value_million_yen": 0,
            "total_estimated_value_million_yen": 0,
            "total_unrealized_gain_million_yen": 0,
            "properties": [],
            "map_path": None,
            "error": None
        }

        try:
            # Step 1: 有価証券報告書を取得
            print("  [1/4] 有価証券報告書を取得中...")
            report = self.report_fetcher.fetch_property_info(
                stock_code, edinet_code, company_name
            )

            if report.get("error"):
                result["error"] = f"有報取得エラー: {report['error']}"
                print(f"  ⚠️ {result['error']}")
                return result

            if not report.get("property_text"):
                result["error"] = "設備情報セクションが見つかりません"
                print(f"  ⚠️ {result['error']}")
                return result

            print(f"  ✓ 有報取得完了 (書類ID: {report.get('doc_id')})")

            # Step 2: Claude APIで不動産情報を抽出
            print("  [2/4] 不動産情報を抽出中...")
            extracted = self.property_extractor.extract_properties(
                report["property_text"],
                company_name
            )

            if extracted.get("error"):
                result["error"] = f"抽出エラー: {extracted['error']}"
                print(f"  ⚠️ {result['error']}")
                return result

            properties = extracted.get("properties", [])
            print(f"  ✓ {len(properties)}件の不動産を抽出")

            if not properties:
                result["error"] = "不動産情報が抽出されませんでした"
                return result

            # Step 3: 地価データで時価を推計
            print("  [3/4] 時価を推計中...")
            evaluated = self.value_estimator.estimate_company_portfolio(properties)

            result["total_book_value_million_yen"] = evaluated["total_book_value_million_yen"]
            result["total_estimated_value_million_yen"] = evaluated["total_estimated_value_million_yen"]
            result["total_unrealized_gain_million_yen"] = evaluated["total_unrealized_gain_million_yen"]
            result["properties"] = evaluated["properties"]

            print(f"  ✓ 時価推計完了")
            print(f"    簿価合計: ¥{result['total_book_value_million_yen']:,.0f}m")
            print(f"    時価推計: ¥{result['total_estimated_value_million_yen']:,.0f}m")
            print(f"    含み益: ¥{result['total_unrealized_gain_million_yen']:,.0f}m")

            # Step 4: 地図を生成
            print("  [4/4] 地図を生成中...")
            map_path = self.output_dir / f"{stock_code}_map.html"
            self.map_generator.generate_company_map(
                company_name=company_name,
                stock_code=stock_code,
                properties=result["properties"],
                output_path=str(map_path)
            )
            result["map_path"] = str(map_path)
            print(f"  ✓ 地図生成完了: {map_path}")

        except Exception as e:
            result["error"] = str(e)
            print(f"  ❌ エラー: {e}")

        return result

    def analyze_topix500(
        self,
        limit: Optional[int] = None,
        skip_existing: bool = True
    ) -> List[Dict]:
        """
        TOPIX500全企業を解析

        Args:
            limit: 解析する企業数の上限（テスト用）
            skip_existing: 既存の解析結果をスキップするか

        Returns:
            解析結果のリスト
        """
        print("TOPIX500 不動産含み益解析を開始します")
        print("="*60)

        # 銘柄リスト取得
        stocks = self.topix_fetcher.fetch_topix500()
        edinet_mapping = self.topix_fetcher.get_edinet_code_mapping()

        if limit:
            stocks = stocks[:limit]

        print(f"対象銘柄数: {len(stocks)}")

        results = []
        results_file = self.output_dir / "analysis_results.json"

        # 既存結果を読み込み
        existing_results = {}
        if skip_existing and results_file.exists():
            with open(results_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
                existing_results = {r["stock_code"]: r for r in existing}
            print(f"既存の解析結果: {len(existing_results)}件")

        for stock in tqdm(stocks, desc="解析中"):
            stock_code = stock["code"]
            company_name = stock["name"]

            # 既存結果をスキップ
            if skip_existing and stock_code in existing_results:
                results.append(existing_results[stock_code])
                continue

            # EDINETコードを取得
            edinet_code = stock.get("edinet_code") or edinet_mapping.get(stock_code)

            if not edinet_code:
                results.append({
                    "stock_code": stock_code,
                    "company_name": company_name,
                    "error": "EDINETコードが見つかりません"
                })
                continue

            # 解析実行
            result = self.analyze_single_company(stock_code, company_name, edinet_code)
            results.append(result)

            # 中間結果を保存
            with open(results_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

        # サマリーを出力
        self._print_summary(results)

        return results

    def _print_summary(self, results: List[Dict]):
        """解析結果のサマリーを出力"""
        print("\n" + "="*60)
        print("解析完了 - サマリー")
        print("="*60)

        successful = [r for r in results if not r.get("error")]
        failed = [r for r in results if r.get("error")]

        total_book = sum(r.get("total_book_value_million_yen", 0) or 0 for r in successful)
        total_estimated = sum(r.get("total_estimated_value_million_yen", 0) or 0 for r in successful)
        total_gain = sum(r.get("total_unrealized_gain_million_yen", 0) or 0 for r in successful)

        print(f"解析成功: {len(successful)}社")
        print(f"解析失敗: {len(failed)}社")
        print(f"\n【集計結果】")
        print(f"  簿価合計: ¥{total_book:,.0f} 百万円")
        print(f"  時価推計: ¥{total_estimated:,.0f} 百万円")
        print(f"  含み益合計: ¥{total_gain:,.0f} 百万円")

        # 含み益トップ10
        top10 = sorted(
            successful,
            key=lambda x: x.get("total_unrealized_gain_million_yen", 0) or 0,
            reverse=True
        )[:10]

        print(f"\n【含み益トップ10】")
        for i, r in enumerate(top10, 1):
            print(f"  {i}. {r['company_name']} ({r['stock_code']}): "
                  f"+¥{r.get('total_unrealized_gain_million_yen', 0):,.0f}m")

    def generate_portfolio_map(self, results: List[Dict]) -> str:
        """
        全企業の不動産を1つの地図にプロット

        Returns:
            HTMLファイルのパス
        """
        all_properties = []

        for r in results:
            if r.get("error"):
                continue

            for prop in r.get("properties", []):
                prop_copy = prop.copy()
                prop_copy["company_name"] = r["company_name"]
                prop_copy["stock_code"] = r["stock_code"]
                all_properties.append(prop_copy)

        output_path = self.output_dir / "portfolio_map.html"

        # TODO: 全企業マップの実装
        print(f"全企業マップ生成: {len(all_properties)}件の不動産")

        return str(output_path)


def main():
    """CLI エントリーポイント"""
    parser = argparse.ArgumentParser(
        description="TOPIX500企業の不動産含み益を解析するツール"
    )

    parser.add_argument(
        "--company", "-c",
        type=str,
        help="解析する企業の証券コード（例: 4746）"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="TOPIX500全企業を解析"
    )

    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="解析する企業数の上限（テスト用）"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default="./output",
        help="出力ディレクトリ（デフォルト: ./output）"
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="既存の解析結果を無視して再解析"
    )

    args = parser.parse_args()

    # API キー確認
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY 環境変数を設定してください")
        print("  export ANTHROPIC_API_KEY='sk-ant-api03-...'")
        sys.exit(1)

    analyzer = RealEstateAnalyzer(output_dir=args.output)

    if args.company:
        # 単一企業の解析
        stock_code = args.company

        # EDINETコードを取得（簡易マッピング）
        edinet_mapping = analyzer.topix_fetcher.get_edinet_code_mapping()
        edinet_code = edinet_mapping.get(stock_code)

        if not edinet_code:
            print(f"エラー: 証券コード {stock_code} のEDINETコードが見つかりません")
            sys.exit(1)

        # 銘柄名を取得
        stocks = analyzer.topix_fetcher.fetch_topix500()
        company_name = next(
            (s["name"] for s in stocks if s["code"] == stock_code),
            f"企業{stock_code}"
        )

        result = analyzer.analyze_single_company(stock_code, company_name, edinet_code)

        # 結果を保存
        output_file = Path(args.output) / f"{stock_code}_result.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"\n結果を保存しました: {output_file}")

        if result.get("map_path"):
            print(f"地図ファイル: {result['map_path']}")

    elif args.all:
        # TOPIX500全企業を解析
        results = analyzer.analyze_topix500(
            limit=args.limit,
            skip_existing=not args.no_cache
        )

        print(f"\n解析結果: {args.output}/analysis_results.json")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
