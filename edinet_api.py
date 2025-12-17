"""
EDINET API連携モジュール
有価証券報告書の取得・解析
"""

import requests
import zipfile
import io
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import time


class EDINETClient:
    """EDINET APIクライアント"""

    BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"

    def __init__(self, api_key: Optional[str] = None, cache_dir: str = "./cache/edinet"):
        self.api_key = api_key or os.environ.get("EDINET_API_KEY", "")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_document_list(
        self,
        date: Optional[str] = None,
        doc_type: str = "120"  # 120: 有価証券報告書
    ) -> List[Dict]:
        """
        指定日の書類一覧を取得

        Args:
            date: 日付 (YYYY-MM-DD形式)。Noneの場合は昨日
            doc_type: 書類種別 (120=有報, 140=四半期報告書)

        Returns:
            書類情報のリスト
        """
        if date is None:
            date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        url = f"{self.BASE_URL}/documents.json"
        params = {
            "date": date,
            "type": 2,  # 2: メタデータのみ
            "Subscription-Key": self.api_key
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("metadata", {}).get("status") != "200":
                print(f"EDINET API エラー: {data}")
                return []

            results = data.get("results", [])

            # 有価証券報告書のみフィルタ
            filtered = [
                doc for doc in results
                if doc.get("docTypeCode") == doc_type
            ]

            return filtered

        except Exception as e:
            print(f"書類一覧取得エラー: {e}")
            return []

    def search_annual_report(
        self,
        edinet_code: str,
        fiscal_year: Optional[int] = None
    ) -> Optional[Dict]:
        """
        指定企業の有価証券報告書を検索

        効率化された検索：
        1. 直近6ヶ月を優先
        2. 決算発表時期（5-6月）を重点的に検索
        3. キャッシュを活用

        Args:
            edinet_code: EDINETコード (例: "E02144")
            fiscal_year: 事業年度。Noneの場合は直近

        Returns:
            書類情報
        """
        if fiscal_year is None:
            fiscal_year = datetime.now().year - 1

        # キャッシュファイルパス
        cache_file = self.cache_dir / f"{edinet_code}_annual_report.json"

        # キャッシュが30日以内なら使用
        if cache_file.exists():
            import json
            cache_age = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days
            if cache_age < 30:
                try:
                    with open(cache_file, 'r') as f:
                        cached = json.load(f)
                        print(f"キャッシュから取得: {edinet_code}")
                        return cached
                except:
                    pass

        # 優先検索期間（決算発表時期: 5-6月、11-12月）
        priority_months = [5, 6, 11, 12]

        # まず優先期間を検索（過去2年、3日間隔で検索）
        # - 最初の6ヶ月: 全ての日を検索（3日間隔）
        # - 6ヶ月〜2年: 優先月のみ検索（5,6,11,12月、3日間隔）
        # 3日間隔なら約66%の確率で提出日にヒットする
        for days_ago in range(0, 730, 3):
            date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            month = int(date.split('-')[1])

            # 優先月でない場合はスキップ（最初の6ヶ月は全て検索）
            if days_ago > 180 and month not in priority_months:
                continue

            docs = self.get_document_list(date=date)

            for doc in docs:
                if doc.get("edinetCode") == edinet_code:
                    # キャッシュに保存
                    import json
                    with open(cache_file, 'w') as f:
                        json.dump(doc, f)
                    return doc

            # APIレート制限回避（3日間隔なので短めに）
            time.sleep(0.2)

        return None

    def download_document(
        self,
        doc_id: str,
        output_type: int = 2  # 1: ZIP, 2: PDF
    ) -> Optional[bytes]:
        """
        書類をダウンロード

        Args:
            doc_id: 書類管理番号
            output_type: 1=ZIP(XBRL), 2=PDF

        Returns:
            ファイルのバイナリデータ
        """
        cache_file = self.cache_dir / f"{doc_id}.{'zip' if output_type == 1 else 'pdf'}"

        if cache_file.exists():
            return cache_file.read_bytes()

        url = f"{self.BASE_URL}/documents/{doc_id}"
        params = {
            "type": output_type,
            "Subscription-Key": self.api_key
        }

        try:
            response = requests.get(url, params=params, timeout=120)
            response.raise_for_status()

            # キャッシュに保存
            cache_file.write_bytes(response.content)

            return response.content

        except Exception as e:
            print(f"書類ダウンロードエラー: {e}")
            return None

    def extract_property_section(self, doc_id: str) -> Optional[str]:
        """
        有価証券報告書から「主要な設備の状況」セクションを抽出

        Args:
            doc_id: 書類管理番号

        Returns:
            セクションのテキスト
        """
        # ZIPファイルをダウンロード
        zip_data = self.download_document(doc_id, output_type=1)
        if not zip_data:
            return None

        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                # XBRLファイルを探す
                xbrl_files = [
                    f for f in zf.namelist()
                    if f.endswith('.htm') or f.endswith('.html')
                ]

                # 主要な設備の状況を含むファイルを検索
                for filename in xbrl_files:
                    content = zf.read(filename).decode('utf-8', errors='ignore')

                    if '主要な設備の状況' in content or '設備の状況' in content:
                        return self._clean_html(content)

            return None

        except Exception as e:
            print(f"ZIP解析エラー: {e}")
            return None

    def _clean_html(self, html: str) -> str:
        """HTMLタグを除去してテキスト化"""
        # 簡易的なHTMLクリーニング
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


class AnnualReportFetcher:
    """有価証券報告書取得の高レベルAPI"""

    def __init__(self, api_key: Optional[str] = None):
        self.client = EDINETClient(api_key)

    def fetch_property_info(
        self,
        stock_code: str,
        edinet_code: str,
        company_name: str
    ) -> Dict:
        """
        企業の不動産情報を取得

        Args:
            stock_code: 証券コード
            edinet_code: EDINETコード
            company_name: 企業名

        Returns:
            {
                "stock_code": "7203",
                "company_name": "トヨタ自動車",
                "doc_id": "S100XXXXX",
                "property_text": "主要な設備の状況のテキスト...",
                "fiscal_year": 2024
            }
        """
        result = {
            "stock_code": stock_code,
            "company_name": company_name,
            "edinet_code": edinet_code,
            "doc_id": None,
            "property_text": None,
            "fiscal_year": None,
            "error": None
        }

        try:
            # 有報を検索
            doc = self.client.search_annual_report(edinet_code)

            if not doc:
                result["error"] = "有価証券報告書が見つかりません"
                return result

            result["doc_id"] = doc.get("docID")
            result["fiscal_year"] = doc.get("periodEnd", "")[:4]

            # 設備セクションを抽出
            property_text = self.client.extract_property_section(result["doc_id"])

            if property_text:
                result["property_text"] = property_text
            else:
                result["error"] = "設備情報セクションの抽出に失敗"

        except Exception as e:
            result["error"] = str(e)

        return result


def main():
    """テスト実行"""
    fetcher = AnnualReportFetcher()

    # 東計電算でテスト
    result = fetcher.fetch_property_info(
        stock_code="4746",
        edinet_code="E05041",
        company_name="東計電算"
    )

    print(f"企業: {result['company_name']}")
    print(f"書類ID: {result['doc_id']}")
    print(f"エラー: {result.get('error')}")

    if result['property_text']:
        print(f"\n設備情報（先頭500文字）:")
        print(result['property_text'][:500])


if __name__ == "__main__":
    main()
