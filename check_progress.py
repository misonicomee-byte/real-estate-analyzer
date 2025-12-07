#!/usr/bin/env python3
"""進捗状況を確認してGitHub Actions出力形式で出力"""

import json
from pathlib import Path

results_file = Path('output/analysis_results.json')

if results_file.exists():
    with open(results_file, 'r') as f:
        results = json.load(f)
    successful = [r for r in results if not r.get('error')]
    count = len(successful)
else:
    count = 0

is_complete = 'true' if count >= 500 else 'false'

print(f'ANALYZED_COUNT={count}')
print(f'IS_COMPLETE={is_complete}')
