"""
Gemini AI 服务模块
用于邮件智能回复建议等功能
"""
import os
import re
from google import genai
from google.genai import types

# 模型ID
MODEL_ID = "gemini-3-flash-preview"

_client = None

# 邮件中常见的无意义内容模式
NOISE_PATTERNS = [
    # 签名档
    r'(?m)^[-]{2,}\s*$.*',  # -- 签名分隔线
    r'(?i)(best\s*regards|kind\s*regards|regards|cheers|sincerely|yours\s*faithfully|yours\s*truly)[,\s]*.*?(?=\n\n|\Z)',
    r'(?i)(祝好|此致|敬礼|顺颂商祺|商祺|谨启|拜上).*?(?=\n\n|\Z)',
    r'(?i)(发自.{0,10}手机|发自.{0,10}邮箱|来自.{0,10}手机|来自.{0,10}邮箱)',
    r'(?i)(sent from my (iphone|ipad|android|mobile|device))',

    # 法律声明/免责声明
    r'(?i)(disclaimer|confidential|privileged|legal notice|法律声明|免责声明|保密|机密).*?(?=\n\n|\Z)',
    r'(?i)此邮件.*?保密.*?(?=\n\n|\Z)',
    r'(?i)本邮件.*?机密.*?(?=\n\n|\Z)',
    r'(?i)if you have received this email in error.*?(?=\n\n|\Z)',

    # 邮件系统自动添加的内容
    r'(?i)(此邮件由.*?发送|this email was sent by).*?(?=\n\n|\Z)',
    r'(?i)(点击.*?退订|click.*?unsubscribe|取消订阅|退订链接)',
    r'(?i)(您收到此邮件是因为.*?|you are receiving this email because).*?(?=\n\n|\Z)',
    r'(?i)(不想再收到.*?|don\'t want to receive).*?(?=\n\n|\Z)',

    # 营销页脚
    r'(?i)(follow us on|关注我们|扫码关注|微信公众号|微博|linkedin|twitter|facebook).{0,50}$',
    r'(?i)(visit our website|访问我们|官网).*?(?=\n\n|\Z)',

    # 多余空白
    r'\n{3,}',  # 连续3个以上换行
    r'[ \t]+$',  # 行尾空白
]

def clean_email_content(content: str, max_length: int = 2000) -> str:
    """
    清理邮件内容，去除无意义部分，减少token消耗

    Args:
        content: 原始邮件内容
        max_length: 最大保留长度

    Returns:
        清理后的邮件内容
    """
    if not content:
        return ""

    # 如果是HTML，先提取纯文本
    if '<' in content and '>' in content:
        # 移除HTML标签
        text = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&nbsp;|&#160;', ' ', text)
        text = re.sub(r'&[a-z]+;', '', text)
        content = text

    # 移除引用的历史邮件（转发链）
    # 常见格式: "On ... wrote:", "-----Original Message-----", "发件人:", "From:"
    content = re.split(r'(?i)(^[-]{3,}.*?original message.*?[-]{3,}|on .+?wrote:|发件人[：:]\s*$|^from[：:]\s*$)', content)[0]

    # 应用噪音模式清理
    for pattern in NOISE_PATTERNS:
        content = re.sub(pattern, '', content, flags=re.DOTALL | re.IGNORECASE)

    # 清理多余空白
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = re.sub(r'[ \t]+', ' ', content)
    content = content.strip()

    # 限制长度
    if len(content) > max_length:
        content = content[:max_length] + "..."

    return content

def get_gemini_client():
    """获取 Gemini 客户端（单例）"""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return None
        _client = genai.Client(api_key=api_key)
    return _client

def is_gemini_configured() -> bool:
    """检查 Gemini API Key 是否已配置"""
    return bool(os.environ.get("GEMINI_API_KEY"))

def set_gemini_api_key(api_key: str) -> bool:
    """
    设置 Gemini API Key 到环境变量

    Args:
        api_key: Gemini API Key

    Returns:
        是否设置成功
    """
    try:
        # 设置到当前进程环境变量
        os.environ["GEMINI_API_KEY"] = api_key

        # 重置客户端，下次使用时会重新初始化
        global _client
        _client = None

        return True
    except Exception as e:
        print(f"Set Gemini API Key error: {e}")
        return False

def set_gemini_api_key_permanent(api_key: str) -> dict:
    """
    永久设置 Gemini API Key 到系统环境变量

    Args:
        api_key: Gemini API Key

    Returns:
        {"windows": bool, "wsl": bool} 表示各平台是否设置成功
    """
    import platform
    import subprocess

    result = {"windows": False, "wsl": False, "message": ""}

    # 先设置到当前进程
    os.environ["GEMINI_API_KEY"] = api_key
    global _client
    _client = None

    # 检测当前环境
    is_wsl = False
    if platform.system() == 'Linux':
        try:
            with open('/proc/version', 'r') as f:
                if 'microsoft' in f.read().lower():
                    is_wsl = True
        except:
            pass

    if platform.system() == 'Windows' or is_wsl:
        # Windows 环境 - 使用 setx 命令（比 PowerShell 快得多）
        try:
            subprocess.run(
                ["setx", "GEMINI_API_KEY", api_key],
                check=True,
                capture_output=True,
                timeout=5
            )
            result["windows"] = True
        except Exception as e:
            result["message"] += f"Windows 设置失败: {str(e)}\n"

        # 如果是 WSL，同时设置到 WSL 环境
        if is_wsl:
            try:
                # 写入 ~/.bashrc
                bashrc_path = os.path.expanduser("~/.bashrc")
                export_line = f'export GEMINI_API_KEY="{api_key}"\n'

                # 检查是否已存在
                existing = False
                if os.path.exists(bashrc_path):
                    with open(bashrc_path, 'r') as f:
                        content = f.read()
                        if 'GEMINI_API_KEY' in content:
                            existing = True

                if not existing:
                    with open(bashrc_path, 'a') as f:
                        f.write(f'\n# Gemini API Key\n{export_line}')
                result["wsl"] = True
            except Exception as e:
                result["message"] += f"WSL 设置失败: {str(e)}\n"

    return result

def get_gemini_api_key() -> str:
    """获取当前配置的 Gemini API Key（部分隐藏）"""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key and len(api_key) > 8:
        return api_key[:4] + "****" + api_key[-4:]
    return api_key

def detect_language(text: str) -> str:
    """
    检测文本语言类型

    Returns:
        'ko' - 韩语
        'en' - 英语
        'zh' - 中文
        'ja' - 日语
    """
    if not text:
        return 'en'

    # 韩文字符范围
    korean_pattern = re.compile(r'[\uac00-\ud7af]+')
    # 中文字符范围
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
    # 日文假名
    japanese_pattern = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]+')

    korean_count = len(korean_pattern.findall(text))
    chinese_count = len(chinese_pattern.findall(text))
    japanese_count = len(japanese_pattern.findall(text))

    # 计算非ASCII字符比例
    non_ascii = len(re.findall(r'[^\x00-\x7F]', text))

    if korean_count > 0 and korean_count >= chinese_count:
        return 'ko'
    elif japanese_count > 0 and japanese_count >= chinese_count:
        return 'ja'
    elif chinese_count > 0:
        return 'zh'
    elif non_ascii == 0:
        return 'en'
    else:
        return 'en'


def get_language_prompt(language: str) -> str:
    """根据语言类型返回对应的提示语"""
    prompts = {
        'ko': """
回复格式要求（韩语商务邮件风格）：
1. 开头使用: 안녕하십니까
2. 自我介绍: 유니콘테크 Joy Kim입니다.
3. 正文内容简洁专业
4. 结尾使用: 추가 문의 사항이 있으시면 언제든지 연락 주시기 바랍니다.
5. 祝福语: 오늘도 평온하고 풍요로운 하루 되십시요. 감사합니다.
6. 落款: 김정 올림(Joy Kim) / Unicorn Technology

全程使用韩语，语气专业礼貌。签名会由系统自动添加，不需要在回复中包含签名。""",
        'en': """
回复格式要求：
请使用英语撰写专业的商务邮件回复，语气礼貌专业。签名会由系统自动添加，不需要在回复中包含签名。""",
        'zh': """
回复格式要求：
请使用中文撰写专业的商务邮件回复，语气礼貌专业。签名会由系统自动添加，不需要在回复中包含签名。""",
        'ja': """
回复格式要求：
请使用日语撰写专业的商务邮件回复，语气礼貌专业。签名会由系统自动添加，不需要在回复中包含签名。"""
    }
    return prompts.get(language, prompts['en'])


def extract_inquiry_table(email_content: str, email_subject: str, language: str) -> dict:
    """
    提取询价信息并整理成表格

    Returns:
        {"is_inquiry": bool, "table": str, "items": list}
    """
    client = get_gemini_client()
    if not client:
        return {"is_inquiry": False, "table": "", "items": []}

    try:
        cleaned_content = clean_email_content(email_content)

        # 判断是否是询价邮件并提取信息
        system_instruction = """你是一个邮件分析专家。请分析邮件内容，判断是否为电子元器件询价邮件。

如果是询价邮件，请提取以下信息并返回JSON格式：
{
    "is_inquiry": true,
    "items": [
        {
            "no": "序号",
            "mpn": "型号",
            "brand": "品牌",
            "qty": "数量",
            "datasheet": "规格书链接或状态",
            "remark": "备注"
        }
    ]
}

如果不是询价邮件，返回：
{"is_inquiry": false, "items": []}

注意：
1. 只返回JSON，不要其他文字
2. 如果邮件中没有明确的信息，对应字段填空字符串
3. 型号(MPN)是最重要的，必须仔细识别
4. 数量要识别数字和单位（如K表示千）"""

        prompt = f"""请分析以下邮件是否为询价邮件，如果是则提取元器件信息：

主题：{email_subject}

内容：
{cleaned_content}

请返回JSON格式的结果："""

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=2000,
            temperature=0.1,
        )

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=config
        )

        # 解析JSON响应
        import json
        response_text = response.text.strip()

        # 移除可能的markdown代码块标记
        if response_text.startswith("```"):
            response_text = re.sub(r'^```json?\s*', '', response_text)
            response_text = re.sub(r'\s*```$', '', response_text)

        result = json.loads(response_text)

        if result.get("is_inquiry") and result.get("items"):
            items = result["items"]
            # 根据语言生成表格
            if language == 'ko':
                table_header = "| No. | 모델명(MPN) | 브랜드 | 수량 | 데이터시트 | 비고 |\n|-----|-------------|--------|------|------------|------|"
            elif language == 'en':
                table_header = "| No. | MPN | Brand | Qty | Datasheet | Remark |\n|-----|-----|-------|-----|-----------|--------|"
            elif language == 'zh':
                table_header = "| 序号 | 型号(MPN) | 品牌 | 数量 | 规格书 | 备注 |\n|------|-----------|------|------|--------|------|"
            else:
                table_header = "| No. | MPN | Brand | Qty | Datasheet | Remark |\n|-----|-----|-------|-----|-----------|--------|"

            table_rows = []
            for item in items:
                row = f"| {item.get('no', '')} | {item.get('mpn', '')} | {item.get('brand', '')} | {item.get('qty', '')} | {item.get('datasheet', '')} | {item.get('remark', '')} |"
                table_rows.append(row)

            table = table_header + "\n" + "\n".join(table_rows)

            return {
                "is_inquiry": True,
                "table": table,
                "items": items
            }

        return {"is_inquiry": False, "table": "", "items": []}

    except Exception as e:
        print(f"Extract inquiry error: {e}")
        return {"is_inquiry": False, "table": "", "items": []}


def suggest_email_reply(
    email_content: str,
    user_instruction: str,
    sender_name: str = "",
    email_subject: str = ""
) -> dict:
    """
    根据邮件内容和用户指示生成回复建议

    Args:
        email_content: 原邮件内容
        user_instruction: 用户想要回复的内容/方向
        sender_name: 发件人名称
        email_subject: 邮件主题

    Returns:
        {"success": bool, "reply": str, "error": str}
    """
    client = get_gemini_client()
    if not client:
        return {"success": False, "error": "Gemini API Key 未配置"}

    try:
        # 清理邮件内容，去除无意义部分
        cleaned_content = clean_email_content(email_content)

        # 检测原邮件语言
        detected_language = detect_language(cleaned_content + " " + email_subject)
        language_prompt = get_language_prompt(detected_language)

        # 检查是否是询价邮件并提取表格
        inquiry_result = extract_inquiry_table(email_content, email_subject, detected_language)

        # 构建系统提示
        system_instruction = f"""你是一个专业的邮件回复助手。请根据用户的指示和原邮件内容，生成一封专业、礼貌的邮件回复。

{language_prompt}

要求：
1. 回复内容要简洁明了，直接回应用户想要表达的内容
2. 语气要专业、礼貌
3. 不要添加多余的开头语如"以下是回复建议"等
4. 直接输出邮件正文内容，不需要主题
5. 不要在结尾添加签名，签名会由系统自动添加"""

        # 构建用户提示
        prompt = f"""请帮我撰写一封邮件回复。

原邮件主题：{email_subject}
发件人：{sender_name}

原邮件内容：
---
{cleaned_content}
---

我的回复意图：
{user_instruction}

请生成邮件回复内容："""

        # 配置生成参数
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=1000,
            temperature=0.7,
        )

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=config
        )

        reply_text = response.text

        # 如果是询价邮件，在回复中插入表格
        if inquiry_result["is_inquiry"]:
            # 在回复开头插入表格
            if detected_language == 'ko':
                table_intro = "\n\n요청하신 제품 정보입니다:\n\n"
            elif detected_language == 'zh':
                table_intro = "\n\n您询价的产品信息如下：\n\n"
            elif detected_language == 'en':
                table_intro = "\n\nHere is the product information you requested:\n\n"
            else:
                table_intro = "\n\nHere is the product information you requested:\n\n"

            reply_text = reply_text + table_intro + inquiry_result["table"]

        return {
            "success": True,
            "reply": reply_text,
            "language": detected_language,
            "is_inquiry": inquiry_result["is_inquiry"],
            "inquiry_items": inquiry_result["items"],
            "usage": {
                "prompt_tokens": response.usage_metadata.prompt_token_count if response.usage_metadata else 0,
                "output_tokens": response.usage_metadata.candidates_token_count if response.usage_metadata else 0
            }
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

def analyze_email(email_content: str) -> dict:
    """
    分析邮件内容

    Args:
        email_content: 邮件内容

    Returns:
        {"success": bool, "analysis": str, "error": str}
    """
    client = get_gemini_client()
    if not client:
        return {"success": False, "error": "Gemini API Key 未配置"}

    try:
        # 清理邮件内容
        cleaned_content = clean_email_content(email_content)

        system_instruction = """你是一个邮件分析助手。请分析邮件内容并提取以下信息：
1. 邮件主题/目的
2. 关键信息点
3. 是否需要回复
4. 建议的回复方向

请用简洁的中文回答。"""

        prompt = f"请分析以下邮件内容：\n\n{cleaned_content}"

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=500,
            temperature=0.3,
        )

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=config
        )

        return {
            "success": True,
            "analysis": response.text
        }

    except Exception as e:
        return {"success": False, "error": str(e)}