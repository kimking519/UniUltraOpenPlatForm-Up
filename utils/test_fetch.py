import sys
import json
import asyncio
from scrapling import fetch_all

async def test_lcsc(pn):
    # 立创商城搜索 URL
    url = f"https://so.szlcsc.com/global.html?k={pn}"
    # 这里先打个桩，后续会根据 scrapling 技能书完善具体的选择器
    print(f"Testing LCSC for {pn}...")

if __name__ == "__main__":
    pn = "ECASD41E336M040KA0"
    if len(sys.argv) > 1:
        pn = sys.argv[1]
    # 暂时先用简单的打印逻辑，稍后我会调用真正的 scrapling 逻辑
    print(f"Target: {pn}")
