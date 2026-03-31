import json
import re
import concurrent.futures
from scrapling.fetchers import StealthyFetcher

class PriceEngine:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    def _clean_text(self, text):
        if not text: return ""
        # 剥离所有 HTML 标签
        return re.sub(r'<[^>]+>', '', str(text)).strip()

    def _extract_json(self, html):
        try:
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', html, re.S)
            if match:
                return json.loads(match.group(1))
        except: pass
        return None

    def check_lcsc(self, part_number):
        url = f"https://so.szlcsc.com/global.html?k={part_number}"
        results = []
        try:
            page = StealthyFetcher.fetch(url, headless=True, timeout=30000)
            html = page.text
            
            # 1. 尝试 JSON 提取
            data = self._extract_json(html)
            if data:
                def deep_scan(obj):
                    found = []
                    if isinstance(obj, dict):
                        # 立创产品特征：型号+ID
                        if ('productModel' in obj or 'lightProductModel' in obj or 'productName' in obj) and \
                           ('productId' in obj or 'productCode' in obj):
                            found.append(obj)
                        for v in obj.values():
                            found.extend(deep_scan(v))
                    elif isinstance(obj, list):
                        for item in obj:
                            found.extend(deep_scan(item))
                    return found

                all_items = deep_scan(data)
                for item in all_items:
                    mpn = self._clean_text(item.get('productModel') or item.get('lightProductModel') or item.get('productName'))
                    if not mpn: continue
                    
                    price = "询价"
                    p_list = item.get('productPriceList', [])
                    if p_list and isinstance(p_list, list):
                        price = f"¥{p_list[0].get('productPrice', '询价')}"
                    elif 'price' in item:
                        price = f"¥{item['price']}"

                    results.append({
                        "source": "LCSC-国内货源",
                        "mpn": mpn,
                        "brand": self._clean_text(item.get('productGradePlateName') or item.get('brandName') or "N/A"),
                        "price": price,
                        "stock": item.get('stockNumber') or item.get('validStockNumber', '现货'),
                        "link": f"https://item.szlcsc.com/{item.get('productId')}.html"
                    })

            # 2. 如果 JSON 还是没抓全，直接扫页面上的海外代购卡片 (LCSC 特有的渲染方式)
            oversea_cards = page.css('section.style__OverseasCard-sc-x6e07z-0')
            for card in oversea_cards:
                mpn_raw = card.css('span.LUCENE_HIGHLIGHT_CLASS::text').get() or card.css('span.text-\\[\\#333333\\]::text').get()
                results.append({
                    "source": "立创-海外代购",
                    "mpn": self._clean_text(mpn_raw) or part_number,
                    "brand": "海外直送",
                    "price": self._clean_text(card.css('ul li span.flex-1::text').get()) or "询价",
                    "stock": "海外库存",
                    "link": "https://so.szlcsc.com" + (card.css('a::attr(href)').get() or "")
                })

        except Exception as e:
            print(f"LCSC Error: {e}")
        return results

    def check_bomman(self, part_number):
        url = f"https://www.bomman.com/global-search?searchWord={part_number}"
        results = []
        try:
            page = StealthyFetcher.fetch(url, headless=True, timeout=30000)
            data = self._extract_json(page.text)
            if data:
                def scan_bomman(obj):
                    found = []
                    if isinstance(obj, dict):
                        if 'productVO' in obj or ('productModel' in obj and 'productId' in obj):
                            found.append(obj)
                        for v in obj.values():
                            found.extend(scan_bomman(v))
                    elif isinstance(obj, list):
                        for item in obj:
                            found.extend(scan_bomman(item))
                    return found
                
                for it in scan_bomman(data):
                    vo = it.get('productVO', it)
                    results.append({
                        "source": "圣禾堂",
                        "mpn": self._clean_text(vo.get('productModel')),
                        "brand": self._clean_text(vo.get('productGradePlateName') or "N/A"),
                        "price": f"¥{vo.get('productPriceList', [{}])[0].get('productPrice', '询价')}",
                        "stock": vo.get('stockNumber', 0),
                        "link": f"https://www.bomman.com/product/details/{vo.get('productId')}"
                    })
        except: pass
        return results

    def check_all(self, part_number):
        all_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            tasks = [executor.submit(self.check_lcsc, part_number), executor.submit(self.check_bomman, part_number)]
            for future in concurrent.futures.as_completed(tasks):
                try:
                    res = future.result()
                    if res: all_results.extend(res)
                except: pass
        
        # 移除死板过滤，改用去重
        final = []
        seen = set()
        for r in all_results:
            # 型号+价格作为唯一键去重
            key = f"{r['mpn']}_{r['price']}"
            if key not in seen:
                final.append(r)
                seen.add(key)
        
        # 按型号匹配度排序（完全匹配的排在前面）
        search_key = re.sub(r'[^a-zA-Z0-9]', '', part_number).lower()
        def match_score(x):
            m_clean = re.sub(r'[^a-zA-Z0-9]', '', str(x['mpn'])).lower()
            if search_key == m_clean: return 0
            if search_key in m_clean: return 1
            if m_clean in search_key: return 2
            return 3
            
        final.sort(key=match_score)
        return final

if __name__ == "__main__":
    import sys
    pn = sys.argv[1] if len(sys.argv) > 1 else "LD1117A-ADJ"
    engine = PriceEngine()
    print(json.dumps(engine.check_all(pn), indent=2, ensure_ascii=False))
