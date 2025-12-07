"""
Claude APIを使用した有価証券報告書の不動産情報解析モジュール
"""

import os
import json
from typing import List, Dict, Optional
from anthropic import Anthropic


class PropertyExtractor:
    """Claude APIを使用して有報から不動産情報を抽出"""

    SYSTEM_PROMPT = """あなたは有価証券報告書から不動産情報を抽出する専門家です。
与えられたテキストから「主要な設備の状況」に記載されている不動産（土地・建物）の情報を
構造化されたJSONとして抽出してください。

出力形式:
{
    "properties": [
        {
            "name": "本社",
            "type": "自社保有" or "賃貸",
            "address": "東京都千代田区...",
            "land_area_sqm": 1234.56,
            "building_area_sqm": 5678.90,
            "book_value_million_yen": 100,
            "purpose": "本社・事務所",
            "notes": "備考があれば"
        }
    ],
    "total_land_book_value_million_yen": 500,
    "total_building_book_value_million_yen": 300,
    "extraction_notes": "抽出時の注意点や不明点"
}

重要な注意事項:
1. 金額は百万円単位に統一してください
2. 面積は平方メートル(㎡)に統一してください
3. 住所は可能な限り詳細に（番地まで）抽出してください
4. 自社保有（所有）か賃貸かを必ず区別してください
5. 土地と建物の帳簿価額が別々に記載されている場合は両方抽出してください
6. 情報が不明な場合はnullとしてください
7. 必ず有効なJSONのみを出力してください（説明文は不要）"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = Anthropic(api_key=self.api_key)

    def extract_properties(self, report_text: str, company_name: str) -> Dict:
        """
        有報テキストから不動産情報を抽出

        Args:
            report_text: 有価証券報告書のテキスト（主要な設備の状況セクション）
            company_name: 企業名

        Returns:
            抽出された不動産情報のDict
        """
        # テキストが長すぎる場合は切り詰め
        max_length = 50000
        if len(report_text) > max_length:
            report_text = report_text[:max_length] + "\n... (以下省略)"

        user_prompt = f"""以下は「{company_name}」の有価証券報告書から抽出した「主要な設備の状況」セクションです。
この中から不動産（土地・建物）に関する情報を抽出し、指定されたJSON形式で出力してください。

---
{report_text}
---

JSONのみを出力してください。"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=self.SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            # レスポンスからJSONを抽出
            content = response.content[0].text
            return self._parse_json_response(content)

        except Exception as e:
            return {
                "properties": [],
                "error": str(e),
                "extraction_notes": "Claude APIエラー"
            }

    def _parse_json_response(self, content: str) -> Dict:
        """レスポンスからJSONをパース"""
        # JSONブロックを探す
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            content = content[start:end].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            return {
                "properties": [],
                "error": f"JSONパースエラー: {e}",
                "raw_response": content[:1000]
            }

    def batch_extract(
        self,
        reports: List[Dict],
        progress_callback=None
    ) -> List[Dict]:
        """
        複数企業の有報を一括処理

        Args:
            reports: [{"company_name": "...", "report_text": "..."}, ...]
            progress_callback: 進捗コールバック関数

        Returns:
            抽出結果のリスト
        """
        results = []

        for i, report in enumerate(reports):
            company_name = report.get("company_name", "不明")
            report_text = report.get("report_text", "")

            if progress_callback:
                progress_callback(i + 1, len(reports), company_name)

            if not report_text:
                results.append({
                    "company_name": company_name,
                    "properties": [],
                    "error": "有報テキストがありません"
                })
                continue

            extracted = self.extract_properties(report_text, company_name)
            extracted["company_name"] = company_name
            extracted["stock_code"] = report.get("stock_code")

            results.append(extracted)

        return results


class PropertyAnalyzer:
    """抽出された不動産情報の分析"""

    @staticmethod
    def calculate_summary(properties: List[Dict]) -> Dict:
        """
        不動産情報のサマリーを計算

        Returns:
            {
                "total_properties": 10,
                "owned_properties": 7,
                "leased_properties": 3,
                "total_land_area_sqm": 50000,
                "total_book_value_million_yen": 1000,
                "by_purpose": {"本社": 2, "工場": 5, ...}
            }
        """
        summary = {
            "total_properties": 0,
            "owned_properties": 0,
            "leased_properties": 0,
            "total_land_area_sqm": 0,
            "total_building_area_sqm": 0,
            "total_land_book_value_million_yen": 0,
            "total_building_book_value_million_yen": 0,
            "by_purpose": {},
            "by_prefecture": {}
        }

        for prop in properties:
            summary["total_properties"] += 1

            if prop.get("type") == "自社保有":
                summary["owned_properties"] += 1
            else:
                summary["leased_properties"] += 1

            if prop.get("land_area_sqm"):
                summary["total_land_area_sqm"] += prop["land_area_sqm"]

            if prop.get("building_area_sqm"):
                summary["total_building_area_sqm"] += prop["building_area_sqm"]

            if prop.get("book_value_million_yen"):
                summary["total_land_book_value_million_yen"] += prop["book_value_million_yen"]

            # 用途別集計
            purpose = prop.get("purpose", "不明")
            summary["by_purpose"][purpose] = summary["by_purpose"].get(purpose, 0) + 1

            # 都道府県別集計
            address = prop.get("address", "")
            prefecture = PropertyAnalyzer._extract_prefecture(address)
            if prefecture:
                summary["by_prefecture"][prefecture] = summary["by_prefecture"].get(prefecture, 0) + 1

        return summary

    @staticmethod
    def _extract_prefecture(address: str) -> Optional[str]:
        """住所から都道府県を抽出"""
        prefectures = [
            "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
            "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
            "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
            "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
            "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
            "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
            "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"
        ]

        for pref in prefectures:
            if pref in address:
                return pref

        return None


def main():
    """テスト実行"""
    extractor = PropertyExtractor()

    # テスト用のサンプルテキスト
    sample_text = """
    【主要な設備の状況】

    1. 提出会社の状況

    事業所名: 本社
    所在地: 神奈川県川崎市中原区新丸子東2-926-10
    設備の内容: 本社事務所
    土地面積: 2,500㎡
    建物面積: 8,000㎡
    帳簿価額(土地): 150百万円
    帳簿価額(建物): 300百万円
    従業員数: 500名

    事業所名: 第二事業所
    所在地: 神奈川県川崎市中原区新丸子東5-14
    設備の内容: データセンター
    土地面積: 1,800㎡
    建物面積: 5,500㎡
    帳簿価額(土地): 200百万円
    帳簿価額(建物): 800百万円
    従業員数: 150名
    """

    result = extractor.extract_properties(sample_text, "東計電算")

    print("抽出結果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("properties"):
        summary = PropertyAnalyzer.calculate_summary(result["properties"])
        print("\nサマリー:")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
