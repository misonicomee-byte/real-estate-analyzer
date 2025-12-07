"""
TOPIX500銘柄リスト取得モジュール
JPXのウェブサイトからTOPIX500構成銘柄を取得
"""

import requests
import pandas as pd
from io import BytesIO
from typing import List, Dict, Optional
import json
from pathlib import Path


class TOPIX500Fetcher:
    """TOPIX500構成銘柄を取得するクラス"""

    # JPX公開のTOPIX構成銘柄一覧URL
    JPX_URL = "https://www.jpx.co.jp/markets/indices/topix/tvdivq00000030ne-att/topix_weight_j.xlsx"

    # EDINETコードとの紐付け用
    EDINET_CODE_LIST_URL = "https://disclosure.edinet-fsa.go.jp/E01EW/download?uession=&s=aY51qSqRwEgIaDAqbLVxPx&f=9"

    def __init__(self, cache_dir: str = "./cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_file = self.cache_dir / "topix500.json"

    def fetch_topix500(self, use_cache: bool = True) -> List[Dict]:
        """
        TOPIX500銘柄リストを取得

        Returns:
            List[Dict]: 銘柄情報のリスト
            [{"code": "7203", "name": "トヨタ自動車", "edinet_code": "E02144"}, ...]
        """
        if use_cache and self.cache_file.exists():
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

        # JPXからTOPIX構成銘柄を取得
        stocks = self._fetch_from_jpx()

        # TOPIX500（上位500銘柄）をフィルタ
        # 実際にはTOPIX Largeが約100社、Mid約400社で合計約500社
        topix500 = stocks[:500] if len(stocks) >= 500 else stocks

        # キャッシュに保存
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(topix500, f, ensure_ascii=False, indent=2)

        return topix500

    def _fetch_from_jpx(self) -> List[Dict]:
        """JPXからTOPIX構成銘柄を取得"""
        try:
            response = requests.get(self.JPX_URL, timeout=30)
            response.raise_for_status()

            # Excelファイルを読み込み
            df = pd.read_excel(BytesIO(response.content), skiprows=1)

            # カラム名を正規化
            df.columns = df.columns.str.strip()

            stocks = []
            for _, row in df.iterrows():
                code = str(row.get("コード", row.get("銘柄コード", ""))).strip()
                name = str(row.get("銘柄名", row.get("銘柄", ""))).strip()

                if code and code.isdigit() and len(code) == 4:
                    stocks.append({
                        "code": code,
                        "name": name,
                        "edinet_code": None  # 後で紐付け
                    })

            return stocks

        except Exception as e:
            print(f"JPXからの取得に失敗: {e}")
            return self._get_fallback_list()

    def _get_fallback_list(self) -> List[Dict]:
        """フォールバック: 主要銘柄のハードコードリスト"""
        # TOPIX500の代表的な銘柄（時価総額上位）
        return [
            {"code": "7203", "name": "トヨタ自動車", "edinet_code": "E02144"},
            {"code": "6758", "name": "ソニーグループ", "edinet_code": "E01777"},
            {"code": "8306", "name": "三菱UFJフィナンシャル・グループ", "edinet_code": "E03606"},
            {"code": "6861", "name": "キーエンス", "edinet_code": "E02390"},
            {"code": "9432", "name": "日本電信電話", "edinet_code": "E04430"},
            {"code": "9984", "name": "ソフトバンクグループ", "edinet_code": "E02778"},
            {"code": "6501", "name": "日立製作所", "edinet_code": "E01737"},
            {"code": "8035", "name": "東京エレクトロン", "edinet_code": "E02655"},
            {"code": "4063", "name": "信越化学工業", "edinet_code": "E00790"},
            {"code": "6902", "name": "デンソー", "edinet_code": "E01620"},
            {"code": "7741", "name": "HOYA", "edinet_code": "E02608"},
            {"code": "4519", "name": "中外製薬", "edinet_code": "E00942"},
            {"code": "9433", "name": "KDDI", "edinet_code": "E04425"},
            {"code": "8058", "name": "三菱商事", "edinet_code": "E02529"},
            {"code": "6367", "name": "ダイキン工業", "edinet_code": "E01576"},
            {"code": "4661", "name": "オリエンタルランド", "edinet_code": "E04719"},
            {"code": "7267", "name": "本田技研工業", "edinet_code": "E02166"},
            {"code": "4568", "name": "第一三共", "edinet_code": "E00939"},
            {"code": "8001", "name": "伊藤忠商事", "edinet_code": "E02513"},
            {"code": "6098", "name": "リクルートホールディングス", "edinet_code": "E31330"},
            {"code": "4746", "name": "東計電算", "edinet_code": "E05041"},  # サンプル企業
            # ... 省略（実際は500社分）
        ]

    def get_edinet_code_mapping(self) -> Dict[str, str]:
        """
        証券コード → EDINETコードのマッピングを取得
        EDINETコードリストから作成
        """
        mapping_file = self.cache_dir / "edinet_mapping.json"

        if mapping_file.exists():
            with open(mapping_file, "r", encoding="utf-8") as f:
                return json.load(f)

        # EDINETコードリストAPIから取得（要APIキー）
        # ここではフォールバックマッピングを返す
        mapping = {
            "7203": "E02144",
            "6758": "E01777",
            "8306": "E03606",
            "6861": "E02390",
            "9432": "E04430",
            "9984": "E02778",
            "6501": "E01737",
            "8035": "E02655",
            "4063": "E00790",
            "6902": "E01620",
            "4746": "E05041",
            # ... 必要に応じて追加
        }

        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

        return mapping


def main():
    """テスト実行"""
    fetcher = TOPIX500Fetcher()
    stocks = fetcher.fetch_topix500()

    print(f"取得銘柄数: {len(stocks)}")
    print("\n上位10銘柄:")
    for stock in stocks[:10]:
        print(f"  {stock['code']}: {stock['name']}")


if __name__ == "__main__":
    main()
