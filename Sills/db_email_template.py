"""
邮件模板管理数据库操作模块
用于邮件模板的创建、查询、删除等功能
"""
import sqlite3
import json
from datetime import datetime
from Sills.base import get_db_connection
from Sills.db_config import get_datetime_now


def get_next_template_id():
    """获取下一个模板ID (TPL+时间戳+随机数格式)"""
    import random
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    rand_suffix = random.randint(1000, 9999)
    return f"TPL{timestamp}{rand_suffix}"


def get_template_list(emp_id=None):
    """获取邮件模板列表

    Args:
        emp_id: 员工ID，用于筛选当前用户创建的模板

    Returns:
        list 模板列表
    """
    with get_db_connection() as conn:
        if emp_id:
            rows = conn.execute("""
                SELECT template_id, template_name, subject, body, created_by, created_at
                FROM uni_email_template
                WHERE created_by = ?
                ORDER BY created_at DESC
            """, (emp_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT template_id, template_name, subject, body, created_by, created_at
                FROM uni_email_template
                ORDER BY created_at DESC
            """).fetchall()

        results = []
        for row in rows:
            template = {k: ("" if v is None else v) for k, v in dict(row).items()}
            results.append(template)
        return results


def get_template_by_id(template_id):
    """根据ID获取模板详情

    Args:
        template_id: 模板ID

    Returns:
        dict 模板详情或None
    """
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT template_id, template_name, subject, body, created_by, created_at
            FROM uni_email_template
            WHERE template_id = ?
        """, (template_id,)).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def create_template(template_name, subject, body, created_by):
    """创建邮件模板

    Args:
        template_name: 模板名称
        subject: 邮件主题模板
        body: 邮件内容模板(HTML)
        created_by: 创建人(员工ID)

    Returns:
        (success, message_or_template_id) tuple
    """
    try:
        if not template_name or not template_name.strip():
            return False, "模板名称不能为空"
        if not subject or not subject.strip():
            return False, "邮件主题不能为空"
        if not body or not body.strip():
            return False, "邮件内容不能为空"

        template_id = get_next_template_id()
        dt_now = get_datetime_now()

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_email_template (
                    template_id, template_name, subject, body, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, {})
            """.format(dt_now), (
                template_id, template_name.strip(), subject.strip(), body.strip(), created_by
            ))
            conn.commit()

        return True, template_id
    except Exception as e:
        return False, str(e)


def update_template(template_id, template_name=None, subject=None, body=None):
    """更新邮件模板

    Args:
        template_id: 模板ID
        template_name: 新模板名称(可选)
        subject: 新邮件主题(可选)
        body: 新邮件内容(可选)

    Returns:
        (success, message) tuple
    """
    try:
        with get_db_connection() as conn:
            # 检查模板是否存在
            row = conn.execute(
                "SELECT template_id FROM uni_email_template WHERE template_id = ?",
                (template_id,)
            ).fetchone()
            if not row:
                return False, "模板不存在"

            # 构建更新语句
            updates = []
            params = []

            if template_name and template_name.strip():
                updates.append("template_name = ?")
                params.append(template_name.strip())

            if subject and subject.strip():
                updates.append("subject = ?")
                params.append(subject.strip())

            if body and body.strip():
                updates.append("body = ?")
                params.append(body.strip())

            if not updates:
                return True, "无更新内容"

            params.append(template_id)
            sql = f"UPDATE uni_email_template SET {', '.join(updates)} WHERE template_id = ?"

            conn.execute(sql, params)
            conn.commit()

        return True, "模板更新成功"
    except Exception as e:
        return False, str(e)


def delete_template(template_id):
    """删除邮件模板

    Args:
        template_id: 模板ID

    Returns:
        (success, message) tuple
    """
    try:
        with get_db_connection() as conn:
            # 检查模板是否存在
            row = conn.execute(
                "SELECT template_id FROM uni_email_template WHERE template_id = ?",
                (template_id,)
            ).fetchone()
            if not row:
                return False, "模板不存在"

            conn.execute("DELETE FROM uni_email_template WHERE template_id = ?", (template_id,))
            conn.commit()

        return True, "模板删除成功"
    except Exception as e:
        return False, str(e)


def delete_templates_batch(template_ids):
    """批量删除模板

    Args:
        template_ids: list 模板ID列表

    Returns:
        (success_count, failed_list) tuple
    """
    success_count = 0
    failed_list = []

    for template_id in template_ids:
        success, message = delete_template(template_id)
        if success:
            success_count += 1
        else:
            failed_list.append({"template_id": template_id, "reason": message})

    return success_count, failed_list