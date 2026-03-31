import json
import os

class BrandAdvisor:
    def __init__(self):
        # 建立核心品牌知识库
        self.knowledge = {
            "Cinch": "Cinch 与 BEL, Johnson 同属 Bel Fuse 集团，型号 105-2201-201 规格完全一致，可互换。",
            "Johnson": "Johnson 已被 Cinch 收购，产品线已整合，目前多以 Cinch 或 BEL 品牌出货。",
            "BEL": "BEL (Bel Fuse) 是 Cinch 和 Johnson 的母公司，三者品牌在测试连接器上是 100% 兼容的。",
            "Murata": "村田 (Murata) 的聚合物电容 (ECAS系列) 具有极低的 ESR，是替代传统钽电容的高性能方案。",
            "TI": "德州仪器 (TI) 近期针对工业电源芯片有价格调整，建议关注现货库存以规避 4 月涨价潮。",
            "Samsung": "三星 MLCC 目前市场行情平稳，建议优先选择原厂正规分销渠道。"
        }

    def get_advice(self, mpn, brand=""):
        advice = []
        
        # 1. 根据品牌匹配
        if brand:
            for k, v in self.knowledge.items():
                if k.lower() in brand.lower():
                    advice.append(v)
        
        # 2. 根据型号特征匹配 (例如 105-2201 系列)
        if "105-2201" in mpn:
            advice.append("该系列为行业标准测试插孔，Cinch/Johnson/BEL 品牌通用。")
            
        return " ".join(advice) if advice else "建议核实原厂规格书，确保批次满足要求。"

if __name__ == "__main__":
    advisor = BrandAdvisor()
    print(advisor.get_advice("105-2201-201", "Cinch"))
