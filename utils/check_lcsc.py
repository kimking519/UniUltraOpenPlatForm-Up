from scrapling.fetchers import StealthyFetcher
import sys

def check_lcsc(pn):
    url = f"https://www.szlcsc.com/search?k={pn}"
    print(f"Fetching {url}...")
    try:
        page = StealthyFetcher.fetch(url, headless=True, timeout=30)
        # 尝试寻找价格。立创的搜索页通常会列出匹配的产品。
        # 我们寻找包含“￥”或者“价格”字样的内容
        # 简单的导出 HTML 供分析
        with open("lcsc_out.html", "w", encoding="utf-8") as f:
            f.write(page.content)
        
        # 常见选择器（根据经验猜测，后续可修正）
        # 价格通常在 .price-container 或类似的类中
        prices = page.css('.price::text').getall()
        stock = page.css('.stock::text').getall()
        
        print(f"Found prices: {prices}")
        print(f"Found stock: {stock}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    pn = sys.argv[1] if len(sys.argv) > 1 else "105-2201-201"
    check_lcsc(pn)
