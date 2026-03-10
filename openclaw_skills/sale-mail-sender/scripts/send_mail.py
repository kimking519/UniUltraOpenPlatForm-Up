#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sale-mail-sender 邮件发送脚本
通过 SMTP 发送邮件，支持标题/收件人/抄送/正文/附件

用法:
    # 最简发送（使用默认值）
    python send_mail.py

    # 指定收件人和主题
    python send_mail.py --to "xxx@example.com" --subject "报价汇总"

    # 带附件
    python send_mail.py --attachment "path/to/file.xlsx"

敏感信息配置（环境变量）:
    export MAIL_SENDER_EMAIL="your_email@example.com"
    export MAIL_SENDER_PASSWORD="your_app_key"
    export MAIL_DEFAULT_TO="default@example.com"
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path


def load_config():
    """
    从 config/mail_config.json 读取 SMTP 服务器配置
    """
    script_dir = Path(__file__).parent.parent
    config_path = script_dir / "config" / "mail_config.json"

    if not config_path.exists():
        return None

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_env_credentials():
    """
    从环境变量读取敏感信息
    返回: (sender_email, sender_password, default_to)
    """
    sender_email = os.environ.get("MAIL_SENDER_EMAIL", "")
    sender_password = os.environ.get("MAIL_SENDER_PASSWORD", "")
    default_to = os.environ.get("MAIL_DEFAULT_TO", "")

    return sender_email, sender_password, default_to


def resolve_path(path):
    """
    Windows/WSL 路径自动转换
    """
    if sys.platform != "win32" and path.startswith(("E:\\", "e:\\")):
        return "/mnt/e/" + path[3:].replace("\\", "/")
    return path


def generate_default_subject():
    """
    生成默认标题: Unicorn_YYYYMMDD_HHmmss
    """
    return datetime.now().strftime("Unicorn_%Y%m%d_%H%M%S")


def validate_email(email):
    """
    简单验证邮箱格式
    """
    if not email:
        return False
    return "@" in email and "." in email.split("@")[-1]


def send_email(
    smtp_host,
    smtp_port,
    smtp_ssl,
    sender_email,
    sender_password,
    sender_name,
    to_list,
    cc_list=None,
    subject=None,
    body=None,
    attachments=None,
):
    """
    发送邮件
    返回: (success, message)
    """
    try:
        # 构建邮件对象
        msg = MIMEMultipart()
        msg["From"] = f"{sender_name} <{sender_email}>"
        msg["To"] = ", ".join(to_list)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        msg["Subject"] = subject or generate_default_subject()

        # 添加正文
        if body:
            # 检测是否为 HTML
            if body.strip().startswith("<"):
                msg.attach(MIMEText(body, "html", "utf-8"))
            else:
                msg.attach(MIMEText(body, "plain", "utf-8"))

        # 添加附件
        if attachments:
            for att_path in attachments:
                att_path = resolve_path(att_path.strip())
                if not os.path.exists(att_path):
                    return False, f"附件不存在: {att_path}"

                with open(att_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    filename = os.path.basename(att_path)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename*=UTF-8''{filename}",
                    )
                    msg.attach(part)

        # 连接 SMTP 服务器并发送
        if smtp_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.starttls()

        server.login(sender_email, sender_password)

        # 收件人列表（包含抄送）
        recipients = to_list + (cc_list or [])
        server.sendmail(sender_email, recipients, msg.as_string())
        server.quit()

        return (
            True,
            f"邮件发送成功！收件人: {', '.join(to_list)}, 主题: {msg['Subject']}",
        )

    except smtplib.SMTPAuthenticationError:
        return False, "SMTP 认证失败：请检查邮箱和授权码是否正确"
    except smtplib.SMTPConnectError:
        return False, f"SMTP 连接失败：无法连接到 {smtp_host}:{smtp_port}"
    except smtplib.SMTPException as e:
        return False, f"SMTP 错误: {str(e)}"
    except Exception as e:
        return False, f"发送失败: {str(e)}"


def main():
    parser = argparse.ArgumentParser(
        description="发送邮件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 最简发送（使用默认值）
    python send_mail.py

    # 指定收件人和主题
    python send_mail.py --to "xxx@example.com" --subject "报价汇总"

    # 带正文
    python send_mail.py --body "这是邮件正文内容"

    # 带附件
    python send_mail.py --attachment "path/to/file.xlsx"

    # 完整示例
    python send_mail.py --to "a@x.com,b@x.com" --cc "c@x.com" --subject "报价" --body "请查收" --attachment "file.xlsx"
        """,
    )

    parser.add_argument("--to", "-t", help="收件人（多人用逗号分隔）")

    parser.add_argument("--cc", "-c", help="抄送人（多人用逗号分隔）")

    parser.add_argument(
        "--subject", "-s", help="邮件标题（默认: Unicorn_YYYYMMDD_HHmmss）"
    )

    parser.add_argument("--body", "-b", help="邮件正文（支持纯文本或 HTML）")

    parser.add_argument("--attachment", "-a", help="附件路径（多个用逗号分隔）")

    args = parser.parse_args()

    # 加载 SMTP 配置
    config = load_config()
    if not config:
        print("[FAIL] 配置文件不存在，请检查 config/mail_config.json")
        sys.exit(1)

    # 从环境变量读取敏感信息
    sender_email, sender_password, default_to = get_env_credentials()

    if not sender_email or not sender_password:
        print("[FAIL] 环境变量未设置，请先配置：")
        print("       export MAIL_SENDER_EMAIL='your_email@example.com'")
        print("       export MAIL_SENDER_PASSWORD='your_app_key'")
        sys.exit(1)

    # 解析收件人
    to_raw = args.to or default_to
    if not to_raw:
        print("[FAIL] 未指定收件人，请通过 --to 参数或设置 MAIL_DEFAULT_TO 环境变量")
        sys.exit(1)

    to_list = [email.strip() for email in to_raw.split(",") if email.strip()]

    # 验证收件人邮箱格式
    for email in to_list:
        if not validate_email(email):
            print(f"[FAIL] 收件人邮箱格式错误: {email}")
            sys.exit(1)

    # 解析抄送人
    cc_list = None
    if args.cc:
        cc_list = [email.strip() for email in args.cc.split(",") if email.strip()]
        for email in cc_list:
            if not validate_email(email):
                print(f"[FAIL] 抄送人邮箱格式错误: {email}")
                sys.exit(1)

    # 解析附件
    attachments = None
    if args.attachment:
        attachments = [p.strip() for p in args.attachment.split(",") if p.strip()]

    # 确认发送信息
    subject = args.subject or generate_default_subject()
    print(f"[INFO] 准备发送邮件...")
    print(f"       收件人: {', '.join(to_list)}")
    if cc_list:
        print(f"       抄送: {', '.join(cc_list)}")
    print(f"       主题: {subject}")
    if attachments:
        print(f"       附件: {len(attachments)} 个文件")

    # 发送邮件
    success, message = send_email(
        smtp_host=config["smtp_host"],
        smtp_port=config["smtp_port"],
        smtp_ssl=config.get("smtp_ssl", True),
        sender_email=sender_email,
        sender_password=sender_password,
        sender_name=config.get("sender_name", "Unicorn"),
        to_list=to_list,
        cc_list=cc_list,
        subject=subject,
        body=args.body,
        attachments=attachments,
    )

    if success:
        print(f"[OK] {message}")
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
