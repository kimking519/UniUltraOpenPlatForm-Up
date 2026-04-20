"""
邮件数据库操作层 - 分类模块
包含：已读/未读回执识别、退信识别、原始收件人提取
"""
import re
from typing import Dict, Optional
from Sills.base import get_db_connection


MAIL_TYPE_KEYWORDS = {
    # 已读回执 (mail_type = 1)
    'read': [
        'Read', '읽음', '已读', '開封', '讀取', 'Lesebestätigung',
        'Gelesen', 'Lu :', 'Letto', 'Lu', '已 x取', '_封'
    ],
    # 未读回执 (mail_type = 2)
    'unread': [
        '읽지 않음', 'Not read', '未開封', 'Nicht gelesen', 'Non letto',
        '未讀取', 'Automatic', 'Automatische', '未读', '自動', '未 _封', 'Non lu'
    ],
    # 系统退信 (mail_type = 3)
    'bounced': [
        '系统退信', 'Undeliverable', 'Returne', '배달되지 않음',
        'Delivery', 'failure', 'Return', 'Notice', 'Unzustellbar',
        'Benachrichtigung', 'Fehlgeschlagen', 'SPAM', '配信不能'
    ]
}

BOUNCE_RECIPIENT_PATTERNS = [
    # Standard format with colon
    r'Original-Recipient:\s*[rfc822;]*\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    r'Final-Recipient:\s*[rfc822;]*\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    # Chinese format - colon or space
    r'收件人[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    r'收件人\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    r'原始收件人[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    # English format - colon or space
    r'To[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    r'To\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    # Korean format
    r'받는 사람[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    r'수신자[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    # Delivery failed format
    r'Delivery failed:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    # Address format
    r'Address[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    # No such user format
    r'No such user\s*[<]?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})[>]?',
]


def extract_original_recipient(content: str) -> Optional[str]:
    """从退信内容中提取原始收件人"""
    if not content:
        return None

    for pattern in BOUNCE_RECIPIENT_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def classify_mail_by_subject(subject: str) -> int:
    """
    根据邮件标题分类邮件类型

    Args:
        subject: 邮件标题

    Returns:
        邮件类型: 0=正常, 1=已读回执, 2=未读回执, 3=系统退信
    """
    if not subject:
        return 0

    subject_upper = subject.upper()

    # 优先级1：检查系统退信（最高优先级）
    for kw in MAIL_TYPE_KEYWORDS['bounced']:
        if kw.upper() in subject_upper:
            return 3

    # 优先级2：检查未读回执（必须在已读之前，因为 "Not read" 包含 "read"）
    for kw in MAIL_TYPE_KEYWORDS['unread']:
        if kw.upper() in subject_upper:
            return 2

    # 优先级3：检查已读回执
    for kw in MAIL_TYPE_KEYWORDS['read']:
        if kw.upper() in subject_upper:
            return 1

    return 0


def classify_mails(account_id: int = None) -> Dict[str, int]:
    """
    批量分类邮件（对未分类的邮件进行标记）

    Args:
        account_id: 账户ID，None表示所有账户

    Returns:
        分类结果统计
    """
    result = {
        'total_processed': 0,
        'read_receipts': 0,
        'unread_receipts': 0,
        'bounced': 0,
        'recipients_extracted': 0
    }

    with get_db_connection() as conn:
        # 获取未分类的邮件
        if account_id:
            rows = conn.execute("""
                SELECT id, subject, content
                FROM uni_mail
                WHERE mail_type = 0 AND account_id = %s
            """, (account_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, subject, content
                FROM uni_mail
                WHERE mail_type = 0
            """).fetchall()

        for row in rows:
            mail_type = classify_mail_by_subject(row['subject'])

            if mail_type > 0:
                # 更新邮件类型
                conn.execute("""
                    UPDATE uni_mail SET mail_type = %s WHERE id = %s
                """, (mail_type, row['id']))

                if mail_type == 1:
                    result['read_receipts'] += 1
                elif mail_type == 2:
                    result['unread_receipts'] += 1
                elif mail_type == 3:
                    result['bounced'] += 1
                    # 提取原始收件人
                    recipient = extract_original_recipient(row['content'])
                    if recipient:
                        conn.execute("""
                            UPDATE uni_mail SET original_recipient = %s WHERE id = %s
                        """, (recipient, row['id']))
                        result['recipients_extracted'] += 1

                result['total_processed'] += 1

        conn.commit()

    return result