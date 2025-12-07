"""
国土交通省 地価公示・地価調査データ取得モジュール
住所から最寄りの基準地価を取得し、時価を推計
"""

import requests
import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import time


class LandPriceClient:
    """国土交通省 土地総合情報システムAPI クライアント"""

    # 国土交通省 不動産取引価格情報API
    API_URL = "https://www.land.mlit.go.jp/webland/api/TradeListSearch"

    # 地価公示・地価調査API（REINFOLIB）
    CHIKA_API_URL = "https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001"

    def __init__(self, cache_dir: str = "./cache/land_price"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.geocoder = Nominatim(user_agent="real_estate_analyzer")
        self._price_cache = {}

    def get_land_price_by_address(
        self,
        address: str,
        year: int = 2024
    ) -> Optional[Dict]:
        """
        住所から最寄りの公示地価を取得

        Args:
            address: 住所
            year: 調査年度

        Returns:
            {
                "address": "東京都千代田区...",
                "price_per_sqm": 1000000,
                "distance_km": 0.5,
                "survey_year": 2024,
                "land_use": "商業地"
            }
        """
        # 住所から座標を取得
        coords = self._geocode(address)
        if not coords:
            return None

        lat, lng = coords

        # 最寄りの地価データを検索
        price_data = self._search_nearest_price(lat, lng, year)

        return price_data

    def _geocode(self, address: str) -> Optional[Tuple[float, float]]:
        """住所から座標を取得"""
        cache_key = f"geocode_{address}"
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]

        try:
            # 日本の住所用に調整
            location = self.geocoder.geocode(address, country_codes="jp")

            if location:
                result = (location.latitude, location.longitude)
                self._price_cache[cache_key] = result
                return result

            # 住所を簡略化して再試行
            simplified = self._simplify_address(address)
            if simplified != address:
                location = self.geocoder.geocode(simplified, country_codes="jp")
                if location:
                    result = (location.latitude, location.longitude)
                    self._price_cache[cache_key] = result
                    return result

            return None

        except Exception as e:
            print(f"ジオコーディングエラー ({address}): {e}")
            return None

    def _simplify_address(self, address: str) -> str:
        """住所を簡略化（番地以降を削除）"""
        # 数字-数字-数字 のパターンを削除
        simplified = re.sub(r'\d+-\d+(-\d+)?$', '', address)
        # 「丁目」「番」「号」以降を削除
        simplified = re.sub(r'(\d+丁目|\d+番|\d+号).*$', r'\1', simplified)
        return simplified.strip()

    def _search_nearest_price(
        self,
        lat: float,
        lng: float,
        year: int
    ) -> Optional[Dict]:
        """座標から最寄りの地価データを検索"""

        # 都道府県コードを推定
        pref_code = self._estimate_prefecture_code(lat, lng)

        try:
            # 国土交通省APIで周辺の取引データを取得
            params = {
                "year": year,
                "area": pref_code,
                "from": f"{year}1",
                "to": f"{year}4"
            }

            response = requests.get(self.API_URL, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                trades = data.get("data", [])

                # 最寄りの土地取引を検索
                nearest = self._find_nearest_trade(trades, lat, lng)
                if nearest:
                    return nearest

        except Exception as e:
            print(f"地価API エラー: {e}")

        # フォールバック: 都道府県平均地価を返す
        return self._get_prefecture_average(pref_code, year)

    def _estimate_prefecture_code(self, lat: float, lng: float) -> str:
        """座標から都道府県コードを推定"""
        # 簡易的な判定（主要都市のみ）
        if 35.5 <= lat <= 35.9 and 139.4 <= lng <= 140.0:
            return "13"  # 東京都
        elif 35.3 <= lat <= 35.7 and 139.3 <= lng <= 139.8:
            return "14"  # 神奈川県
        elif 34.5 <= lat <= 35.0 and 135.3 <= lng <= 135.8:
            return "27"  # 大阪府
        elif 34.9 <= lat <= 35.3 and 136.7 <= lng <= 137.2:
            return "23"  # 愛知県
        else:
            return "13"  # デフォルト: 東京都

    def _find_nearest_trade(
        self,
        trades: List[Dict],
        lat: float,
        lng: float
    ) -> Optional[Dict]:
        """最寄りの取引データを検索"""
        nearest = None
        min_distance = float('inf')

        for trade in trades:
            # 土地のみの取引をフィルタ
            if trade.get("Type") != "宅地(土地)":
                continue

            # 住所から座標を取得（簡易）
            trade_address = trade.get("Municipality", "") + trade.get("DistrictName", "")
            trade_coords = self._geocode(trade_address)

            if trade_coords:
                distance = geodesic((lat, lng), trade_coords).km

                if distance < min_distance:
                    min_distance = distance
                    price_per_sqm = self._calculate_price_per_sqm(trade)

                    nearest = {
                        "address": trade_address,
                        "price_per_sqm": price_per_sqm,
                        "distance_km": round(distance, 2),
                        "survey_year": trade.get("Period", ""),
                        "land_use": trade.get("Use", "住宅地"),
                        "source": "国土交通省取引情報"
                    }

        return nearest

    def _calculate_price_per_sqm(self, trade: Dict) -> int:
        """取引データから㎡単価を計算"""
        try:
            price = int(trade.get("TradePrice", 0))
            area = float(trade.get("Area", 1))
            return int(price / area) if area > 0 else 0
        except (ValueError, TypeError):
            return 0

    def _get_prefecture_average(self, pref_code: str, year: int) -> Dict:
        """都道府県の平均地価を返す（フォールバック）"""
        # 主要都道府県の概算平均地価（円/㎡）
        averages = {
            "13": {"name": "東京都", "commercial": 2500000, "residential": 500000},
            "14": {"name": "神奈川県", "commercial": 800000, "residential": 250000},
            "27": {"name": "大阪府", "commercial": 1200000, "residential": 200000},
            "23": {"name": "愛知県", "commercial": 600000, "residential": 150000},
            "40": {"name": "福岡県", "commercial": 500000, "residential": 100000},
        }

        avg = averages.get(pref_code, {"name": "その他", "commercial": 300000, "residential": 80000})

        return {
            "address": avg["name"],
            "price_per_sqm": avg["commercial"],  # 商業地を使用
            "distance_km": None,
            "survey_year": year,
            "land_use": "商業地（都道府県平均）",
            "source": "概算平均値"
        }


class ValueEstimator:
    """不動産の時価推計"""

    def __init__(self):
        self.land_price_client = LandPriceClient()

    def estimate_market_value(self, property_info: Dict) -> Dict:
        """
        不動産の時価を推計

        Args:
            property_info: {
                "name": "本社",
                "address": "東京都千代田区...",
                "land_area_sqm": 1000,
                "book_value_million_yen": 100
            }

        Returns:
            {
                "name": "本社",
                "book_value_million_yen": 100,
                "estimated_value_million_yen": 500,
                "unrealized_gain_million_yen": 400,
                "price_per_sqm_used": 500000,
                "estimation_method": "近隣取引価格"
            }
        """
        result = {
            "name": property_info.get("name", "不明"),
            "address": property_info.get("address", ""),
            "type": property_info.get("type", "不明"),
            "land_area_sqm": property_info.get("land_area_sqm"),
            "book_value_million_yen": property_info.get("book_value_million_yen", 0),
            "estimated_value_million_yen": None,
            "unrealized_gain_million_yen": None,
            "price_per_sqm_used": None,
            "estimation_method": None,
            "estimation_notes": None
        }

        # 賃貸物件は含み益なし
        if property_info.get("type") == "賃貸":
            result["estimation_notes"] = "賃貸物件のため時価推計対象外"
            result["unrealized_gain_million_yen"] = 0
            return result

        address = property_info.get("address", "")
        land_area = property_info.get("land_area_sqm")

        if not address:
            result["estimation_notes"] = "住所情報なし"
            return result

        if not land_area:
            result["estimation_notes"] = "土地面積情報なし"
            return result

        # 地価を取得
        land_price = self.land_price_client.get_land_price_by_address(address)

        if land_price:
            price_per_sqm = land_price.get("price_per_sqm", 0)

            # 時価推計（土地のみ、建物は除外）
            estimated_value = (land_area * price_per_sqm) / 1_000_000  # 百万円単位

            book_value = property_info.get("book_value_million_yen", 0) or 0
            unrealized_gain = estimated_value - book_value

            result["estimated_value_million_yen"] = round(estimated_value, 0)
            result["unrealized_gain_million_yen"] = round(unrealized_gain, 0)
            result["price_per_sqm_used"] = price_per_sqm
            result["estimation_method"] = land_price.get("source", "地価データ")
            result["estimation_notes"] = f"基準地価: {land_price.get('address', '')} ({land_price.get('land_use', '')})"

        else:
            result["estimation_notes"] = "地価データ取得失敗"

        return result

    def estimate_company_portfolio(self, properties: List[Dict]) -> Dict:
        """
        企業全体の不動産ポートフォリオを評価

        Returns:
            {
                "total_book_value_million_yen": 1000,
                "total_estimated_value_million_yen": 2500,
                "total_unrealized_gain_million_yen": 1500,
                "properties": [...]
            }
        """
        evaluated_properties = []
        total_book = 0
        total_estimated = 0
        total_gain = 0

        for prop in properties:
            evaluated = self.estimate_market_value(prop)
            evaluated_properties.append(evaluated)

            if evaluated.get("book_value_million_yen"):
                total_book += evaluated["book_value_million_yen"]

            if evaluated.get("estimated_value_million_yen"):
                total_estimated += evaluated["estimated_value_million_yen"]

            if evaluated.get("unrealized_gain_million_yen"):
                total_gain += evaluated["unrealized_gain_million_yen"]

            # APIレート制限対策
            time.sleep(0.5)

        return {
            "total_book_value_million_yen": round(total_book, 0),
            "total_estimated_value_million_yen": round(total_estimated, 0),
            "total_unrealized_gain_million_yen": round(total_gain, 0),
            "properties": evaluated_properties
        }


def main():
    """テスト実行"""
    estimator = ValueEstimator()

    # テストデータ
    test_properties = [
        {
            "name": "本社",
            "type": "自社保有",
            "address": "神奈川県川崎市中原区新丸子東2-926-10",
            "land_area_sqm": 2500,
            "book_value_million_yen": 150
        },
        {
            "name": "第二事業所",
            "type": "自社保有",
            "address": "神奈川県川崎市中原区新丸子東5-14",
            "land_area_sqm": 1800,
            "book_value_million_yen": 200
        }
    ]

    result = estimator.estimate_company_portfolio(test_properties)

    print("=== 不動産評価結果 ===")
    print(f"簿価合計: {result['total_book_value_million_yen']:,.0f} 百万円")
    print(f"時価推計: {result['total_estimated_value_million_yen']:,.0f} 百万円")
    print(f"含み益: {result['total_unrealized_gain_million_yen']:,.0f} 百万円")

    print("\n=== 物件詳細 ===")
    for prop in result["properties"]:
        print(f"\n{prop['name']}:")
        print(f"  簿価: {prop.get('book_value_million_yen', 'N/A')} 百万円")
        print(f"  時価: {prop.get('estimated_value_million_yen', 'N/A')} 百万円")
        print(f"  含み益: {prop.get('unrealized_gain_million_yen', 'N/A')} 百万円")


if __name__ == "__main__":
    main()
