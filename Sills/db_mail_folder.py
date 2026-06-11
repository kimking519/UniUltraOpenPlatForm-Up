"""
邮件数据库操作层 - 文件夹管理模块
包含：文件夹CRUD、过滤规则、自动分类、邮件移动
"""
from typing import Optional, Dict, List, Any
from Sills.base import get_db_connection


# ==================== 邮件文件夹管理 ====================

def get_folders(account_id: int = None, exclude_system: bool = True) -> List[Dict[str, Any]]:
    """
    获取文件夹列表

    Args:
        account_id: 账户ID
        exclude_system: 是否排除系统文件夹（前端已硬编码的文件夹）

    Returns:
        文件夹列表
    """
    # 前端已硬编码的系统文件夹名称，不需要动态加载
    system_folder_names = ['收件箱', '已发送', '草稿箱', '垃圾邮件', '黑名单邮件', '回收站']

    with get_db_connection() as conn:
        if account_id is not None:
            if exclude_system:
                # 排除系统文件夹
                placeholders = ','.join('?' * len(system_folder_names))
                rows = conn.execute(
                    f"SELECT * FROM mail_folder WHERE (account_id = ? OR account_id IS NULL) AND folder_name NOT IN ({placeholders}) ORDER BY sort_order, id",
                    [account_id] + system_folder_names
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mail_folder WHERE account_id = ? OR account_id IS NULL ORDER BY sort_order, id",
                    (account_id,)
                ).fetchall()
        else:
            if exclude_system:
                # 排除系统文件夹
                placeholders = ','.join('?' * len(system_folder_names))
                rows = conn.execute(
                    f"SELECT * FROM mail_folder WHERE folder_name NOT IN ({placeholders}) ORDER BY sort_order, id",
                    system_folder_names
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mail_folder ORDER BY sort_order, id"
                ).fetchall()
        return [dict(row) for row in rows]


def get_folder_by_id(folder_id: int) -> Optional[Dict[str, Any]]:
    """获取单个文件夹"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM mail_folder WHERE id = ?", (folder_id,)).fetchone()
        if row:
            return dict(row)
    return None


def get_or_create_sent_folder(account_id: int = None) -> int:
    """
    获取或创建已发送文件夹

    Args:
        account_id: 账户ID

    Returns:
        已发送文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在已发送文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '已发送' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '已发送'"
            ).fetchone()

        if row:
            return row[0]

        # 创建已发送文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('已发送', '📤', 10, account_id)
        )
        conn.commit()
        print(f"[DB] 创建已发送文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def get_or_create_draft_folder(account_id: int = None) -> int:
    """
    获取或创建草稿箱文件夹

    Args:
        account_id: 账户ID

    Returns:
        草稿箱文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在草稿箱文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '草稿箱' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '草稿箱'"
            ).fetchone()

        if row:
            return row[0]

        # 创建草稿箱文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('草稿箱', '📝', 20, account_id)
        )
        conn.commit()
        print(f"[DB] 创建草稿箱文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def get_or_create_spam_folder(account_id: int = None) -> int:
    """
    获取或创建垃圾邮件文件夹

    Args:
        account_id: 账户ID

    Returns:
        垃圾邮件文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在垃圾邮件文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '垃圾邮件' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '垃圾邮件'"
            ).fetchone()

        if row:
            return row[0]

        # 创建垃圾邮件文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('垃圾邮件', '🗑️', 100, account_id)
        )
        conn.commit()
        print(f"[DB] 创建垃圾邮件文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def get_or_create_system_folder(account_id: int = None) -> int:
    """
    获取或创建系统邮件文件夹

    Args:
        account_id: 账户ID

    Returns:
        系统邮件文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在系统邮件文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '系统邮件' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '系统邮件'"
            ).fetchone()

        if row:
            return row[0]

        # 创建系统邮件文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('系统邮件', '🔔', 90, account_id)
        )
        conn.commit()
        print(f"[DB] 创建系统邮件文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def get_or_create_blacklist_folder(account_id: int = None) -> int:
    """
    获取或创建黑名单文件夹

    Args:
        account_id: 账户ID

    Returns:
        黑名单文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在黑名单文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '黑名单' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '黑名单'"
            ).fetchone()

        if row:
            return row[0]

        # 创建黑名单文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('黑名单', '🚫', 110, account_id)
        )
        conn.commit()
        print(f"[DB] 创建黑名单文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def add_folder(folder_data: Dict[str, Any]) -> int:
    """添加文件夹"""
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id)
            VALUES (?, ?, ?, ?)
        """, (
            folder_data.get('folder_name'),
            folder_data.get('folder_icon', 'folder'),
            folder_data.get('sort_order', 0),
            folder_data.get('account_id')
        ))
        conn.commit()
        return cursor.lastrowid


def update_folder(folder_id: int, folder_data: Dict[str, Any]) -> bool:
    """更新文件夹"""
    with get_db_connection() as conn:
        result = conn.execute("""
            UPDATE mail_folder SET folder_name = ?, folder_icon = ?, sort_order = ?
            WHERE id = ?
        """, (
            folder_data.get('folder_name'),
            folder_data.get('folder_icon', 'folder'),
            folder_data.get('sort_order', 0),
            folder_id
        ))
        conn.commit()
        return result.rowcount > 0


def delete_folder(folder_id: int) -> bool:
    """删除文件夹（关联邮件移回收件箱）"""
    with get_db_connection() as conn:
        # 将该文件夹的邮件移回收件箱（folder_id = NULL）
        conn.execute("UPDATE uni_mail SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
        # 删除文件夹（规则会级联删除）
        result = conn.execute("DELETE FROM mail_folder WHERE id = ?", (folder_id,))
        conn.commit()
        return result.rowcount > 0


def get_mail_count_by_folder(folder_id: int, account_id: int = None) -> int:
    """获取文件夹中的邮件数量"""
    with get_db_connection() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE folder_id = ? AND account_id = ? AND is_sent = 0",
                (folder_id, account_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE folder_id = ? AND is_sent = 0",
                (folder_id,)
            ).fetchone()
        return row[0] if row else 0


# ==================== 邮件过滤规则管理 ====================

def get_filter_rules(folder_id: int = None) -> List[Dict[str, Any]]:
    """获取过滤规则列表"""
    with get_db_connection() as conn:
        if folder_id:
            rows = conn.execute(
                "SELECT r.*, f.folder_name FROM mail_filter_rule r " +
                "LEFT JOIN mail_folder f ON r.folder_id = f.id " +
                "WHERE r.folder_id = ? ORDER BY r.priority DESC, r.id",
                (folder_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT r.*, f.folder_name FROM mail_filter_rule r " +
                "LEFT JOIN mail_folder f ON r.folder_id = f.id " +
                "ORDER BY r.priority DESC, r.id"
            ).fetchall()
        return [dict(row) for row in rows]


def add_filter_rule(rule_data: Dict[str, Any]) -> int:
    """添加过滤规则"""
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO mail_filter_rule (folder_id, keyword, priority, is_enabled)
            VALUES (?, ?, ?, ?)
        """, (
            rule_data.get('folder_id'),
            rule_data.get('keyword'),
            rule_data.get('priority', 0),
            rule_data.get('is_enabled', 1)
        ))
        conn.commit()
        return cursor.lastrowid


def update_filter_rule(rule_id: int, rule_data: Dict[str, Any]) -> bool:
    """更新过滤规则"""
    with get_db_connection() as conn:
        result = conn.execute("""
            UPDATE mail_filter_rule SET keyword = ?, priority = ?, is_enabled = ?
            WHERE id = ?
        """, (
            rule_data.get('keyword'),
            rule_data.get('priority', 0),
            rule_data.get('is_enabled', 1),
            rule_id
        ))
        conn.commit()
        return result.rowcount > 0


def delete_filter_rule(rule_id: int) -> bool:
    """删除过滤规则"""
    with get_db_connection() as conn:
        result = conn.execute("DELETE FROM mail_filter_rule WHERE id = ?", (rule_id,))
        conn.commit()
        return result.rowcount > 0


# ==================== 自动分类功能 ====================

def auto_classify_emails(account_id: int = None) -> Dict[str, int]:
    """
    自动分类邮件（根据规则匹配标题）
    支持多关键词，用逗号分隔，如：报价,invoice,quote

    Returns:
        {classified_count: 已分类邮件数, rule_count: 使用规则数}
    """
    # 获取所有启用的规则，按优先级降序
    with get_db_connection() as conn:
        rules = conn.execute("""
            SELECT r.*, f.folder_name
            FROM mail_filter_rule r
            JOIN mail_folder f ON r.folder_id = f.id
            WHERE r.is_enabled = 1
            ORDER BY r.priority DESC, r.id
        """).fetchall()

        if not rules:
            return {"classified_count": 0, "rule_count": 0}

        # 获取未分类的收件箱邮件
        if account_id is not None:
            emails = conn.execute("""
                SELECT id, subject FROM uni_mail
                WHERE is_sent = 0 AND folder_id IS NULL AND account_id = ?
            """, (account_id,)).fetchall()
        else:
            emails = conn.execute("""
                SELECT id, subject FROM uni_mail
                WHERE is_sent = 0 AND folder_id IS NULL
            """).fetchall()

        classified_count = 0

        for email in emails:
            email_id = email['id']
            subject = email['subject'] or ''

            # 按优先级顺序匹配规则
            for rule in rules:
                keyword_str = rule['keyword'] or ''
                # 支持多关键词，用逗号分隔
                keywords = [k.strip().lower() for k in keyword_str.split(',') if k.strip()]
                if any(kw in subject.lower() for kw in keywords):
                    # 匹配成功，更新邮件的文件夹
                    conn.execute(
                        "UPDATE uni_mail SET folder_id = ? WHERE id = ?",
                        (rule['folder_id'], email_id)
                    )
                    classified_count += 1
                    break  # 只匹配第一个符合条件的规则

        conn.commit()

    return {"classified_count": classified_count, "rule_count": len(rules)}


def get_mails_by_folder(folder_id: int, page: int = 1, limit: int = 20,
                        search: str = None, account_id: int = None) -> Dict[str, Any]:
    """获取指定文件夹的邮件列表"""
    offset = (page - 1) * limit
    params = [folder_id]
    count_params = [folder_id]

    # 列表视图只查询必要字段，避免加载大字段
    select_fields = "id, subject, from_addr, from_name, to_addr, received_at, sent_at, is_sent, is_read, message_id, account_id, folder_id, created_at"

    query = f"SELECT {select_fields} FROM uni_mail WHERE folder_id = ? AND is_sent = 0 AND is_deleted = 0"
    count_query = "SELECT COUNT(*) FROM uni_mail WHERE folder_id = ? AND is_sent = 0 AND is_deleted = 0"

    if account_id is not None:
        query += " AND account_id = ?"
        count_query += " AND account_id = ?"
        params.append(account_id)
        count_params.append(account_id)

    if search:
        # 2026-06-11: 新增 to_addr 和 content 搜索，对齐其他列表行为
        query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])
        count_params.extend([search_param, search_param, search_param, search_param])

    query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        total_count = conn.execute(count_query, count_params).fetchone()[0]
        rows = conn.execute(query, params).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        item['content_preview'] = ''
        item['body_truncated'] = False
        items.append(item)

    return {
        "items": items,
        "total_count": total_count,
        "page": page,
        "page_size": limit,
        "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 0
    }


# ============ 垃圾邮件文件夹功能 ============

def get_spam_list(page: int = 1, limit: int = 20, search: str = None, account_id: int = None) -> Dict[str, Any]:
    """
    获取垃圾邮件列表（分页）
    """
    spam_folder_id = get_or_create_spam_folder(account_id)
    return get_mails_by_folder(spam_folder_id, page, limit, search, account_id)


def get_spam_count(account_id: int = None) -> int:
    """获取垃圾邮件数量"""
    spam_folder_id = get_or_create_spam_folder(account_id)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM uni_mail WHERE folder_id = ? AND is_deleted = 0",
            (spam_folder_id,)
        ).fetchone()
        return row[0] if row else 0


def move_email_to_folder(mail_id: int, folder_id: int = None) -> bool:
    """
    移动邮件到指定文件夹

    Args:
        mail_id: 邮件ID
        folder_id: 目标文件夹ID，None表示移回收件箱

    Returns:
        是否成功
    """
    with get_db_connection() as conn:
        result = conn.execute(
            "UPDATE uni_mail SET folder_id = ? WHERE id = ?",
            (folder_id, mail_id)
        )
        conn.commit()
        return result.rowcount > 0


def move_emails_to_folder(mail_ids: list, folder_id: int = None) -> int:
    """
    批量移动邮件到指定文件夹

    Args:
        mail_ids: 邮件ID列表
        folder_id: 目标文件夹ID，None表示移回收件箱

    Returns:
        成功移动的数量
    """
    if not mail_ids:
        return 0
    with get_db_connection() as conn:
        placeholders = ','.join('?' * len(mail_ids))
        result = conn.execute(
            f"UPDATE uni_mail SET folder_id = ? WHERE id IN ({placeholders})",
            [folder_id] + mail_ids
        )
        conn.commit()
        return result.rowcount