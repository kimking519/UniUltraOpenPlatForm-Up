### 场景：销售提取需求

**用户输入：**
> “帮我记一下，韩国客户 C002 刚在微信上说要找 2500 个 CC0603KRX7R9BB104，国巨的。他们希望 0.02 元搞定，月底要货。”

**OpenClaw 动作：**
1. 识别客户：`C002` (韩国客户)
2. 识别型号：`CC0603KRX7R9BB104`
3. 识别品牌：`YAGEO` (国巨)
4. 识别数量：`2500`
5. 识别价格：`0.02`
6. 处理备注：`月底要货`

**执行命令：**
```bash
python openclaw_skills/sale-input-needs/scripts/auto_input.py --cli_id "C002" --mpn "CC0603KRX7R9BB104" --brand "YAGEO" --qty 2500 --price 0.02 --remark "月底要货"
```
