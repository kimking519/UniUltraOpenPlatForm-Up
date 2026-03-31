import json, re
from scrapling.fetchers import StealthyFetcher

pn = "LD1117A-ADJ"
url = f"https://so.szlcsc.com/global.html?k={pn}"
page = StealthyFetcher.fetch(url, headless=True)
html = page.text

match = re.search(r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', html, re.S)
if match:
    data = json.loads(match.group(1))
    soData = data.get('props', {}).get('pageProps', {}).get('soData', {})
    searchResult = soData.get('searchResult', {})
    records = searchResult.get('productRecordList', [])
    print(f"Found {len(records)} records in JSON")
    for r in records:
        vo = r.get('productVO', {})
        print(f" - MPN: {vo.get('productModel')}")

# Try CSS
oversea_cards = page.css('section.style__OverseasCard-sc-x6e07z-0')
print(f"Found {len(oversea_cards)} overseas cards via CSS")
