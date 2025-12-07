"""
地図表示ダッシュボード生成モジュール
Foliumを使用してインタラクティブな地図を生成
"""

import json
import folium
from folium import plugins
from typing import List, Dict, Optional
from pathlib import Path
from geopy.geocoders import Nominatim
import time


class MapGenerator:
    """不動産含み益マップ生成"""

    def __init__(self):
        self.geocoder = Nominatim(user_agent="real_estate_analyzer")
        self._coord_cache = {}

    def generate_company_map(
        self,
        company_name: str,
        stock_code: str,
        properties: List[Dict],
        output_path: str = "output/map.html"
    ) -> str:
        """
        企業の不動産マップを生成

        Args:
            company_name: 企業名
            stock_code: 証券コード
            properties: 評価済み不動産リスト
            output_path: 出力ファイルパス

        Returns:
            生成したHTMLファイルのパス
        """
        # 出力ディレクトリ作成
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # 座標付きの物件をフィルタ
        located_properties = self._add_coordinates(properties)

        if not located_properties:
            return self._generate_empty_map(company_name, output_path)

        # 中心座標を計算
        center_lat = sum(p["lat"] for p in located_properties) / len(located_properties)
        center_lng = sum(p["lng"] for p in located_properties) / len(located_properties)

        # 地図作成
        m = folium.Map(
            location=[center_lat, center_lng],
            zoom_start=10,
            tiles="cartodbpositron"
        )

        # サマリー計算
        total_book = sum(p.get("book_value_million_yen", 0) or 0 for p in properties)
        total_estimated = sum(p.get("estimated_value_million_yen", 0) or 0 for p in properties)
        total_gain = sum(p.get("unrealized_gain_million_yen", 0) or 0 for p in properties)

        # マーカー追加
        for prop in located_properties:
            self._add_property_marker(m, prop)

        # タイトルとサマリーを追加
        title_html = self._generate_title_html(
            company_name, stock_code, total_book, total_estimated, total_gain
        )
        m.get_root().html.add_child(folium.Element(title_html))

        # 凡例追加
        legend_html = self._generate_legend_html()
        m.get_root().html.add_child(folium.Element(legend_html))

        # サイドバー追加（物件リスト）
        sidebar_html = self._generate_sidebar_html(properties)
        m.get_root().html.add_child(folium.Element(sidebar_html))

        # 保存
        m.save(output_path)

        return output_path

    def _add_coordinates(self, properties: List[Dict]) -> List[Dict]:
        """物件に座標を追加"""
        result = []

        for prop in properties:
            address = prop.get("address", "")
            if not address:
                continue

            coords = self._geocode(address)
            if coords:
                prop_with_coords = prop.copy()
                prop_with_coords["lat"] = coords[0]
                prop_with_coords["lng"] = coords[1]
                result.append(prop_with_coords)

            time.sleep(0.5)  # レート制限対策

        return result

    def _geocode(self, address: str) -> Optional[tuple]:
        """住所から座標を取得"""
        if address in self._coord_cache:
            return self._coord_cache[address]

        try:
            location = self.geocoder.geocode(address, country_codes="jp")
            if location:
                result = (location.latitude, location.longitude)
                self._coord_cache[address] = result
                return result
        except Exception:
            pass

        return None

    def _add_property_marker(self, m: folium.Map, prop: Dict):
        """物件マーカーを追加"""
        gain = prop.get("unrealized_gain_million_yen", 0) or 0
        prop_type = prop.get("type", "不明")

        # 含み益に応じた色
        if gain > 500:
            color = "#10B981"  # 緑（大きな含み益）
        elif gain > 100:
            color = "#3B82F6"  # 青（中程度の含み益）
        elif gain > 0:
            color = "#6366F1"  # 紫（小さな含み益）
        else:
            color = "#6B7280"  # グレー（含み損または不明）

        # 賃貸は別色
        if prop_type == "賃貸":
            color = "#9CA3AF"  # 薄いグレー

        # ポップアップ内容
        popup_html = f"""
        <div style="font-family: 'Helvetica Neue', sans-serif; min-width: 250px;">
            <h4 style="margin: 0 0 10px 0; color: #1F2937;">{prop.get('name', '不明')}</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 4px 0; color: #6B7280;">所有形態</td>
                    <td style="padding: 4px 0; text-align: right;">{prop_type}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #6B7280;">住所</td>
                    <td style="padding: 4px 0; text-align: right; font-size: 12px;">{prop.get('address', '不明')}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #6B7280;">土地面積</td>
                    <td style="padding: 4px 0; text-align: right;">{prop.get('land_area_sqm', 'N/A'):,.0f} ㎡</td>
                </tr>
                <tr style="border-top: 1px solid #E5E7EB;">
                    <td style="padding: 8px 0 4px 0; color: #6B7280;">帳簿価額</td>
                    <td style="padding: 8px 0 4px 0; text-align: right;">¥{prop.get('book_value_million_yen', 0) or 0:,.0f}m</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #6B7280;">時価推計</td>
                    <td style="padding: 4px 0; text-align: right;">¥{prop.get('estimated_value_million_yen', 0) or 0:,.0f}m</td>
                </tr>
                <tr style="background: {'#D1FAE5' if gain > 0 else '#FEE2E2'};">
                    <td style="padding: 4px 8px; font-weight: bold;">含み益</td>
                    <td style="padding: 4px 8px; text-align: right; font-weight: bold; color: {'#059669' if gain > 0 else '#DC2626'};">
                        {'+' if gain > 0 else ''}¥{gain:,.0f}m
                    </td>
                </tr>
            </table>
            <p style="margin: 10px 0 0 0; font-size: 11px; color: #9CA3AF;">
                {prop.get('estimation_notes', '')}
            </p>
        </div>
        """

        # マーカーサイズ（含み益に応じて）
        radius = max(8, min(20, 8 + abs(gain) / 100))

        folium.CircleMarker(
            location=[prop["lat"], prop["lng"]],
            radius=radius,
            color=color,
            fill=True,
            fillColor=color,
            fillOpacity=0.7,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{prop.get('name', '不明')} (+¥{gain:,.0f}m)"
        ).add_to(m)

    def _generate_title_html(
        self,
        company_name: str,
        stock_code: str,
        total_book: float,
        total_estimated: float,
        total_gain: float
    ) -> str:
        """タイトルとサマリーのHTML"""
        return f"""
        <div style="
            position: fixed;
            top: 10px;
            left: 60px;
            z-index: 1000;
            background: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            font-family: 'Helvetica Neue', sans-serif;
        ">
            <h2 style="margin: 0 0 5px 0; font-size: 18px; color: #1F2937;">
                {company_name} 不動産含み益解析
            </h2>
            <p style="margin: 0 0 10px 0; font-size: 12px; color: #6B7280;">
                有価証券報告書 簿価 vs 公示地価・基準地価
            </p>
            <div style="display: flex; gap: 20px;">
                <div>
                    <div style="font-size: 11px; color: #6B7280;">保有土地簿価計</div>
                    <div style="font-size: 16px; font-weight: bold;">¥{total_book:,.0f} 百万円</div>
                </div>
                <div>
                    <div style="font-size: 11px; color: #6B7280;">含み益合計</div>
                    <div style="font-size: 16px; font-weight: bold; color: #10B981;">
                        +¥{total_gain:,.0f} 百万円
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_legend_html(self) -> str:
        """凡例HTML"""
        return """
        <div style="
            position: fixed;
            bottom: 30px;
            right: 10px;
            z-index: 1000;
            background: white;
            padding: 10px 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            font-family: 'Helvetica Neue', sans-serif;
            font-size: 12px;
        ">
            <div style="font-weight: bold; margin-bottom: 8px;">凡例 (Ownership)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;">
                <span style="display: inline-block; width: 12px; height: 12px; background: #10B981; border-radius: 50%; margin-right: 8px;"></span>
                自社保有 (Owned)
            </div>
            <div style="display: flex; align-items: center;">
                <span style="display: inline-block; width: 12px; height: 12px; background: #9CA3AF; border-radius: 50%; margin-right: 8px;"></span>
                賃貸 (Leased)
            </div>
        </div>
        """

    def _generate_sidebar_html(self, properties: List[Dict]) -> str:
        """サイドバー（物件リスト）HTML"""
        items_html = ""

        # 含み益順にソート
        sorted_props = sorted(
            properties,
            key=lambda x: x.get("unrealized_gain_million_yen", 0) or 0,
            reverse=True
        )

        for prop in sorted_props:
            gain = prop.get("unrealized_gain_million_yen", 0) or 0
            gain_color = "#10B981" if gain > 0 else "#DC2626"

            items_html += f"""
            <div style="
                padding: 12px;
                border-bottom: 1px solid #E5E7EB;
                cursor: pointer;
            " onmouseover="this.style.background='#F9FAFB'" onmouseout="this.style.background='white'">
                <div style="font-weight: 500; margin-bottom: 4px;">{prop.get('name', '不明')}</div>
                <div style="font-size: 11px; color: #6B7280; margin-bottom: 4px;">
                    {prop.get('address', '')[:30]}...
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">簿価: ¥{prop.get('book_value_million_yen', 0) or 0:,.0f}m</span>
                    <span style="color: {gain_color}; font-weight: bold;">
                        {'+' if gain > 0 else ''}¥{gain:,.0f}m
                    </span>
                </div>
            </div>
            """

        return f"""
        <div id="sidebar" style="
            position: fixed;
            top: 10px;
            left: 10px;
            width: 280px;
            max-height: calc(100vh - 20px);
            z-index: 999;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            font-family: 'Helvetica Neue', sans-serif;
            display: none;
        ">
            <div style="
                padding: 15px;
                border-bottom: 1px solid #E5E7EB;
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <span style="font-weight: bold;">物件一覧</span>
                <button onclick="document.getElementById('sidebar').style.display='none'" style="
                    background: none;
                    border: none;
                    font-size: 18px;
                    cursor: pointer;
                    color: #6B7280;
                ">×</button>
            </div>
            <div style="overflow-y: auto; max-height: calc(100vh - 80px);">
                {items_html}
            </div>
        </div>

        <button onclick="
            var sb = document.getElementById('sidebar');
            sb.style.display = sb.style.display === 'none' ? 'block' : 'none';
        " style="
            position: fixed;
            top: 120px;
            left: 60px;
            z-index: 1000;
            background: white;
            border: none;
            padding: 8px 12px;
            border-radius: 4px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            cursor: pointer;
            font-family: 'Helvetica Neue', sans-serif;
            font-size: 13px;
        ">
            📋 物件一覧
        </button>
        """

    def _generate_empty_map(self, company_name: str, output_path: str) -> str:
        """物件がない場合の空マップ"""
        m = folium.Map(
            location=[35.6812, 139.7671],  # 東京
            zoom_start=5,
            tiles="cartodbpositron"
        )

        error_html = f"""
        <div style="
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            z-index: 1000;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        ">
            <h2>{company_name}</h2>
            <p>位置情報を特定できる不動産が見つかりませんでした。</p>
        </div>
        """
        m.get_root().html.add_child(folium.Element(error_html))
        m.save(output_path)

        return output_path


def main():
    """テスト実行"""
    generator = MapGenerator()

    # テストデータ
    test_properties = [
        {
            "name": "本社",
            "type": "自社保有",
            "address": "神奈川県川崎市中原区新丸子東2-926-10",
            "land_area_sqm": 2500,
            "book_value_million_yen": 150,
            "estimated_value_million_yen": 718,
            "unrealized_gain_million_yen": 568,
            "estimation_notes": "基準地価: 川崎市中原区新丸子東5-14"
        },
        {
            "name": "第二事業所",
            "type": "自社保有",
            "address": "神奈川県川崎市中原区新丸子東5-14",
            "land_area_sqm": 1800,
            "book_value_million_yen": 200,
            "estimated_value_million_yen": 520,
            "unrealized_gain_million_yen": 320,
            "estimation_notes": "基準地価: 川崎市中原区"
        },
        {
            "name": "座間事業所 (IDC)",
            "type": "自社保有",
            "address": "神奈川県座間市緑ケ丘1-3-1",
            "land_area_sqm": 5000,
            "book_value_million_yen": 180,
            "estimated_value_million_yen": 526,
            "unrealized_gain_million_yen": 346,
            "estimation_notes": "基準地価: 座間市"
        }
    ]

    output_path = generator.generate_company_map(
        company_name="東計電算",
        stock_code="4746",
        properties=test_properties,
        output_path="output/test_map.html"
    )

    print(f"地図を生成しました: {output_path}")


if __name__ == "__main__":
    main()
