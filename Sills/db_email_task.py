"""
邮件任务管理数据库操作模块
用于邮件任务创建、进度追踪、取消等功能
"""
import sqlite3
import json
from datetime import datetime
from Sills.base import get_db_connection
from Sills.db_contact_group import get_all_groups_contacts, get_all_groups_contacts_all_types
from Sills.db_config import get_datetime_now


def get_next_task_id():
    """获取下一个任务ID (ET + 微秒时间戳 + 3位计数器, 批量导入安全)"""
    from Sills.base import gen_unique_id
    return gen_unique_id('ET')


def get_task_list(page=1, page_size=20, status_filter="", search_kw=""):
    """获取邮件任务列表"""
    offset = (page - 1) * page_size
    where_clauses = []
    params = []

    if status_filter:
        where_clauses.append("status = ?")
        params.append(status_filter)

    if search_kw:
        where_clauses.append("task_name LIKE ?")
        params.append(f"%{search_kw}%")

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
    SELECT t.*, a.email as account_email, a.account_name as account_name
    FROM uni_email_task t
    LEFT JOIN uni_email_account a ON t.account_id = a.account_id
    {where_sql}
    ORDER BY t.created_at DESC
    LIMIT ? OFFSET ?
    """

    count_query = f"SELECT COUNT(*) FROM uni_email_task {where_sql}"

    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total


def get_task_by_id(task_id):
    """根据ID获取任务详情"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT t.*
            FROM uni_email_task t
            WHERE t.task_id = ?
        """, (task_id,)).fetchone()
        if row:
            task = {k: ("" if v is None else v) for k, v in dict(row).items()}
            # 解析account_ids获取账号信息列表
            account_ids_json = task.get('account_ids', '[]')
            try:
                account_ids = json.loads(account_ids_json) if account_ids_json else []
            except:
                account_ids = []

            # 获取所有账号信息
            from Sills.db_email_account import get_account_by_id
            accounts_info = []
            for acc_id in account_ids:
                acc = get_account_by_id(acc_id)
                if acc:
                    accounts_info.append(acc)
            task['accounts_info'] = accounts_info
            return task
        return None


def get_active_task():
    """获取当前活跃任务(单任务约束)"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT t.*
            FROM uni_email_task t
            WHERE t.status IN ('running', 'retrying')
        """).fetchone()
        if row:
            task = {k: ("" if v is None else v) for k, v in dict(row).items()}
            # 解析account_ids获取账号信息列表
            account_ids_json = task.get('account_ids', '[]')
            try:
                account_ids = json.loads(account_ids_json) if account_ids_json else []
            except:
                account_ids = []

            # 获取所有账号信息（包含密码用于发送）
            from Sills.db_email_account import get_account_by_id
            accounts_info = []
            for acc_id in account_ids:
                acc = get_account_by_id(acc_id)
                if acc:
                    accounts_info.append(acc)
            task['accounts_info'] = accounts_info
            return task
        return None


def get_interrupted_tasks():
    """获取所有状态为 running 的中断任务（服务器重启后需要恢复）

    Returns:
        list: 中断任务列表
    """
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT t.*
            FROM uni_email_task t
            WHERE t.status IN ('running', 'retrying')
            ORDER BY t.started_at DESC
        """).fetchall()
        tasks = []
        for row in rows:
            task = {k: ("" if v is None else v) for k, v in dict(row).items()}
            tasks.append(task)
        return tasks


def has_running_task():
    """检查是否有正在进行的任务"""
    with get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM uni_email_task WHERE status IN ('running', 'retrying')"
        ).fetchone()[0]
        return count > 0


def create_task(task_name, account_ids, group_ids, subject, body,
                placeholders=None, schedule_start=None, schedule_end=None,
                send_interval=2, skip_enabled=1, skip_days=7, daily_limit_per_account=1800):
    """创建邮件任务

    Args:
        task_name: 任务名称
        account_ids: list 发件人账号ID列表（支持多账号轮换）
        group_ids: list 组ID列表
        subject: 邮件主题
        body: HTML邮件内容
        placeholders: dict 占位符配置
        schedule_start: 发送开始时间 HH:MM
        schedule_end: 发送结束时间 HH:MM
        send_interval: 发送间隔（秒），默认2秒
        skip_enabled: 是否启用跳过规则（默认1开启）
        skip_days: 成功发送后跳过天数（默认7天）
        daily_limit_per_account: 单账号日发送上限（默认1800）

    Returns:
        (success, message_or_task_id) tuple
    """
    try:
        # 已移除"有任务在跑时禁止创建"的限制 (2026-06-19)
        # 现在任意时刻都允许创建新任务（启动时仍受其他规则约束）
        if not task_name or not task_name.strip():
            return False, "任务名称不能为空"
        if not account_ids or len(account_ids) == 0:
            return False, "请选择至少一个发件人账号"
        if not group_ids:
            return False, "请选择至少一个联系人组"
        if not subject or not subject.strip():
            return False, "邮件主题不能为空"
        if not body or not body.strip():
            return False, "邮件内容不能为空"

        # 合并组联系人并去重（支持动态组和静态组）
        contacts = get_all_groups_contacts_all_types(group_ids)
        if not contacts:
            return False, "所选组中没有联系人"

        task_id = get_next_task_id()
        group_ids_json = json.dumps(group_ids)
        account_ids_json = json.dumps(account_ids)
        placeholders_json = json.dumps(placeholders) if placeholders else ""

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_email_task (
                    task_id, task_name, account_ids, group_ids,
                    subject, body, placeholders,
                    schedule_start, schedule_end, send_interval,
                    skip_enabled, skip_days, daily_limit_per_account,
                    current_account_index,
                    status, total_count, sent_count, failed_count, skipped_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', ?, 0, 0, 0)
            """, (
                task_id, task_name.strip(), account_ids_json, group_ids_json,
                subject.strip(), body.strip(), placeholders_json,
                schedule_start, schedule_end, send_interval,
                skip_enabled, skip_days, daily_limit_per_account,
                len(contacts)
            ))
            conn.commit()

        return True, task_id
    except Exception as e:
        return False, str(e)


def start_task(task_id):
    """启动任务(状态改为running，支持pending/paused/error状态)"""
    try:
        dt_now = get_datetime_now()
        with get_db_connection() as conn:
            # 支持从待执行、已暂停、执行错误状态继续执行
            conn.execute(f"""
                UPDATE uni_email_task
                SET status = 'running', started_at = {dt_now}, cancel_requested = 0, error_message = ''
                WHERE task_id = ? AND status IN ('pending', 'paused', 'error', 'retrying')
            """, (task_id,))
            conn.commit()
            return True, "任务已启动"
    except Exception as e:
        return False, str(e)


def update_task_progress(task_id, sent_count=None, failed_count=None, skipped_count=None):
    """更新任务进度"""
    try:
        updates = []
        params = []

        if sent_count is not None:
            updates.append("sent_count = ?")
            params.append(sent_count)

        if failed_count is not None:
            updates.append("failed_count = ?")
            params.append(failed_count)

        if skipped_count is not None:
            updates.append("skipped_count = ?")
            params.append(skipped_count)

        if not updates:
            return True

        params.append(task_id)
        sql = f"UPDATE uni_email_task SET {', '.join(updates)} WHERE task_id = ?"

        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

        return True
    except Exception as e:
        return False, str(e)


def cancel_task(task_id):
    """请求取消任务并设置为暂停状态"""
    try:
        with get_db_connection() as conn:
            # 设置取消请求标志，同时将状态改为 paused
            conn.execute("""
                UPDATE uni_email_task
                SET cancel_requested = 1, status = 'paused'
                WHERE task_id = ? AND status IN ('running', 'retrying')
            """, (task_id,))
            conn.commit()
            return True, "任务已暂停"
    except Exception as e:
        return False, str(e)


def complete_task(task_id, failed_count=0):
    """完成任务"""
    try:
        dt_now = get_datetime_now()
        with get_db_connection() as conn:
            conn.execute(f"""
                UPDATE uni_email_task
                SET status = 'completed',
                    completed_at = {dt_now},
                    failed_count = ?
                WHERE task_id = ?
            """, (failed_count, task_id))
            conn.commit()
            return True, "任务已完成"
    except Exception as e:
        return False, str(e)


def update_current_account_index(task_id, account_index):
    """更新当前使用的账号索引"""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_email_task
                SET current_account_index = ?
                WHERE task_id = ?
            """, (account_index, task_id))
            conn.commit()
            return True
    except Exception as e:
        return False, str(e)


def error_task(task_id, error_message):
    """标记任务出错"""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_email_task
                SET status = 'error', error_message = ?
                WHERE task_id = ?
            """, (error_message, task_id))
            conn.commit()
            return True, "任务已标记为错误"
    except Exception as e:
        return False, str(e)


def update_task_account(task_id, new_account_id):
    """更新任务的发件人账号（仅非执行状态可用）

    Args:
        task_id: 任务ID
        new_account_id: 新的发件人账号ID

    Returns:
        (success, message) tuple
    """
    try:
        with get_db_connection() as conn:
            # 检查任务状态
            task = conn.execute(
                "SELECT status FROM uni_email_task WHERE task_id = ?",
                (task_id,)
            ).fetchone()

            if not task:
                return False, "任务不存在"

            status = task[0] if isinstance(task, tuple) else task.get('status')

            # 只有非执行状态可以修改
            if status == 'running':
                return False, "正在执行的任务不能修改发件人账号"

            # 验证新账号是否存在
            from Sills.db_email_account import get_account_by_id
            account = get_account_by_id(new_account_id)
            if not account:
                return False, "发件人账号不存在"

            # 更新账号
            conn.execute("""
                UPDATE uni_email_task
                SET account_id = ?
                WHERE task_id = ?
            """, (new_account_id, task_id))
            conn.commit()
            return True, "发件人账号已更新"
    except Exception as e:
        return False, str(e)


def get_task_progress(task_id):
    """获取任务进度信息"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT task_id, task_name, status, total_count, sent_count, failed_count,
                   started_at, schedule_start, schedule_end, cancel_requested
            FROM uni_email_task
            WHERE task_id = ?
        """, (task_id,)).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def is_cancel_requested(task_id):
    """检查是否请求取消"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT cancel_requested FROM uni_email_task WHERE task_id = ?",
            (task_id,)
        ).fetchone()
        return row and row[0] == 1


def get_task_contacts(task_id):
    """获取任务的联系人列表（排除已发送成功的邮箱 + 手动排除的邮箱）

    Returns:
        list 未发送联系人列表 [{"contact_id", "email", "company", ...}, ...]
    """
    task = get_task_by_id(task_id)
    if not task:
        return []

    group_ids = json.loads(task.get('group_ids', '[]') or '[]')
    all_contacts = get_all_groups_contacts_all_types(group_ids)

    # 获取本任务已发送成功的邮箱列表，排除已发送的
    from Sills.db_email_log import get_sent_emails_for_task
    sent_emails = get_sent_emails_for_task(task_id)
    sent_email_set = set(e.lower() for e in sent_emails)

    # 获取本任务手动排除的邮箱列表
    excluded_json = task.get('excluded_contacts', '') or ''
    excluded_emails = set()
    if excluded_json:
        try:
            excluded_emails = set(e.lower() for e in json.loads(excluded_json))
        except:
            pass

    # 过滤掉已发送成功 + 手动排除的联系人
    unsent_contacts = [
        c for c in all_contacts
        if c.get('email', '').lower() not in sent_email_set
        and c.get('email', '').lower() not in excluded_emails
    ]

    return unsent_contacts


def get_task_all_contacts(task_id):
    """获取任务全部联系人（仅排除手动排除的邮箱，不排除已发送成功）——用于重新执行

    Returns:
        list 全部联系人列表 [{"contact_id", "email", "company", ...}, ...]
    """
    task = get_task_by_id(task_id)
    if not task:
        return []

    group_ids = json.loads(task.get('group_ids', '[]') or '[]')
    all_contacts = get_all_groups_contacts_all_types(group_ids)

    # 获取本任务手动排除的邮箱列表
    excluded_json = task.get('excluded_contacts', '') or ''
    excluded_emails = set()
    if excluded_json:
        try:
            excluded_emails = set(e.lower() for e in json.loads(excluded_json))
        except:
            pass

    # 仅过滤手动排除的联系人，不排除已发送成功的（重新执行需重发全部）
    return [
        c for c in all_contacts
        if c.get('email', '').lower() not in excluded_emails
    ]


def get_task_contacts_with_excluded(task_id, search=""):
    """获取任务的全部联系人列表（带排除标记，用于编辑弹窗）

    Args:
        task_id: 任务ID
        search: 搜索关键词（匹配客户名或邮箱）

    Returns:
        (contacts_list, excluded_count, total) tuple
        contacts_list 中每个联系人包含 is_excluded 字段
    """
    task = get_task_by_id(task_id)
    if not task:
        return [], 0, 0

    group_ids = json.loads(task.get('group_ids', '[]') or '[]')
    all_contacts = get_all_groups_contacts_all_types(group_ids)

    # 获取手动排除的邮箱
    excluded_json = task.get('excluded_contacts', '') or ''
    excluded_set = set()
    if excluded_json:
        try:
            excluded_set = set(e.lower() for e in json.loads(excluded_json))
        except:
            pass

    # 构建联系人列表（带排除标记）
    results = []
    for c in all_contacts:
        email = c.get('email', '').lower()
        if not email:
            continue
        # 搜索过滤
        if search:
            kw = search.lower()
            name = (c.get('name', '') or c.get('contact_name', '') or '').lower()
            company = (c.get('company', '') or c.get('company_name', '') or '').lower()
            if kw not in email and kw not in name and kw not in company:
                continue
        results.append({
            'contact_id': c.get('contact_id', ''),
            'email': c.get('email', ''),
            'name': c.get('name', '') or c.get('contact_name', '') or '',
            'company': c.get('company', '') or c.get('company_name', '') or '',
            'is_excluded': email in excluded_set
        })

    # 去重（按email）
    seen = set()
    deduped = []
    for c in results:
        email_lower = c['email'].lower()
        if email_lower not in seen:
            seen.add(email_lower)
            deduped.append(c)

    excluded_count = sum(1 for c in deduped if c['is_excluded'])

    return deduped, excluded_count, len(deduped)


def exclude_task_contact(task_id, email):
    """从任务中排除某个联系人邮箱

    Args:
        task_id: 任务ID
        email: 要排除的邮箱地址

    Returns:
        (success, message) tuple
    """
    try:
        task = get_task_by_id(task_id)
        if not task:
            return False, "任务不存在"

        # 只允许在 pending/paused/error 状态编辑
        if task.get('status') not in ('pending', 'paused', 'error'):
            return False, "当前任务状态不允许编辑名单"

        email_lower = email.strip().lower()
        if not email_lower:
            return False, "邮箱地址不能为空"

        # 获取现有排除列表
        excluded_json = task.get('excluded_contacts', '') or ''
        excluded_list = []
        if excluded_json:
            try:
                excluded_list = json.loads(excluded_json)
            except:
                excluded_list = []

        if email_lower in [e.lower() for e in excluded_list]:
            return False, "该邮箱已在排除列表中"

        excluded_list.append(email.strip())
        new_excluded_json = json.dumps(excluded_list)

        # 同步更新 total_count（减少1，但不能低于已处理数）
        task_total = task.get('total_count', 0) or 0
        sent = task.get('sent_count', 0) or 0
        skipped = task.get('skipped_count', 0) or 0
        new_total = max(task_total - 1, sent + skipped)

        with get_db_connection() as conn:
            conn.execute(
                "UPDATE uni_email_task SET excluded_contacts = ?, total_count = ? WHERE task_id = ?",
                (new_excluded_json, new_total, task_id)
            )
            conn.commit()

        return True, "邮箱已从名单中移除"
    except Exception as e:
        return False, str(e)


def restore_task_contact(task_id, email):
    """恢复任务中被排除的联系人邮箱

    Args:
        task_id: 任务ID
        email: 要恢复的邮箱地址

    Returns:
        (success, message) tuple
    """
    try:
        task = get_task_by_id(task_id)
        if not task:
            return False, "任务不存在"

        # 只允许在 pending/paused/error 状态编辑
        if task.get('status') not in ('pending', 'paused', 'error'):
            return False, "当前任务状态不允许编辑名单"

        email_lower = email.strip().lower()
        if not email_lower:
            return False, "邮箱地址不能为空"

        # 获取现有排除列表
        excluded_json = task.get('excluded_contacts', '') or ''
        excluded_list = []
        if excluded_json:
            try:
                excluded_list = json.loads(excluded_json)
            except:
                excluded_list = []

        # 查找并移除
        found = False
        new_list = []
        for e in excluded_list:
            if e.lower() == email_lower:
                found = True
            else:
                new_list.append(e)

        if not found:
            return False, "该邮箱不在排除列表中"

        new_excluded_json = json.dumps(new_list) if new_list else ""

        # 同步更新 total_count（增加1）
        task_total = task.get('total_count', 0) or 0
        new_total = task_total + 1

        with get_db_connection() as conn:
            conn.execute(
                "UPDATE uni_email_task SET excluded_contacts = ?, total_count = ? WHERE task_id = ?",
                (new_excluded_json, new_total, task_id)
            )
            conn.commit()

        return True, "邮箱已恢复到名单中"
    except Exception as e:
        return False, str(e)


def get_task_failed_contacts(task_id):
    """获取任务发送失败的联系人列表（用于重试）

    Returns:
        list 失败联系人列表 [{"contact_id", "email", "company", ...}, ...]
    """
    from Sills.db_email_log import get_failed_logs

    failed_logs = get_failed_logs(task_id)
    if not failed_logs:
        return []

    results = []
    for log in failed_logs:
        contact_id = log.get('contact_id', '')
        email = log.get('email', '')
        company = log.get('company_name', '')

        # 尝试从contact表获取更多信息
        from Sills.db_contact import get_contact_by_id
        contact = get_contact_by_id(contact_id) if contact_id else None

        results.append({
            'contact_id': contact_id,
            'email': email,
            'company': company or (contact.get('company', '') if contact else ''),
            'contact_name': contact.get('contact_name', '') if contact else '',
            'country': contact.get('country', '') if contact else '',
            'domain': contact.get('domain', '') if contact else '',
            'position': contact.get('position', '') if contact else '',
            'phone': contact.get('phone', '') if contact else '',
            'is_bounced': contact.get('is_bounced', 0) if contact else 0,
            'send_count': contact.get('send_count', 0) if contact else 0,
            'error_message': log.get('error_message', '')
        })

    return results


def retry_failed_task(task_id):
    """重试任务中发送失败的联系人

    Args:
        task_id: 任务ID

    Returns:
        (success, message) tuple
    """
    try:
        task = get_task_by_id(task_id)
        if not task:
            return False, "任务不存在"

        status = task.get('status', '')
        if status not in ['completed', 'error']:
            return False, "只有已完成或出错的任务可以重试"

        failed_contacts = get_task_failed_contacts(task_id)
        if not failed_contacts:
            return False, "没有发送失败的联系人"

        # 更新任务状态为 retrying
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_email_task
                SET status = 'retrying', error_message = ''
                WHERE task_id = ?
            """, (task_id,))
            conn.commit()

        return True, f"任务已设置为重试模式，将重新发送 {len(failed_contacts)} 个失败邮件"
    except Exception as e:
        return False, str(e)


def reexecute_task(task_id):
    """重新执行任务：重置进度并对全部联系人重新发送（仅 completed/error 可用）

    Args:
        task_id: 任务ID

    Returns:
        (success, message) tuple
    """
    try:
        task = get_task_by_id(task_id)
        if not task:
            return False, "任务不存在"

        status = task.get('status', '')
        if status not in ['completed', 'error']:
            return False, "只有已完成或执行错误的任务可以重新执行"

        contacts = get_task_all_contacts(task_id)
        if not contacts:
            return False, "任务没有可发送的联系人"

        # 重置进度计数，状态置为 running，重新发送全部联系人
        dt_now = get_datetime_now()
        with get_db_connection() as conn:
            conn.execute(f"""
                UPDATE uni_email_task
                SET status = 'running', started_at = {dt_now},
                    cancel_requested = 0, error_message = '',
                    sent_count = 0, failed_count = 0, skipped_count = 0
                WHERE task_id = ?
            """, (task_id,))
            conn.commit()

        return True, f"任务已重新启动，将发送 {len(contacts)} 个联系人"
    except Exception as e:
        return False, str(e)


def get_task_full_stats(task_id):
    """获取任务完整统计信息

    Returns:
        dict {
            total_count: 总联系人数,
            sent_count: 已发送数,
            success_count: 成功数,
            failed_count: 失败数,
            pending_count: 待发送数,
            retry_count: 重试次数
        }
    """
    from Sills.db_email_log import get_sent_count, get_failed_count, get_task_stats

    task = get_task_by_id(task_id)
    if not task:
        return None

    total_count = task.get('total_count', 0) or 0
    sent_count = task.get('sent_count', 0) or 0
    failed_count = task.get('failed_count', 0) or 0

    # 从日志表获取准确的成功/失败数
    log_stats = get_task_stats(task_id)
    success_count = log_stats.get('sent', 0)
    actual_failed_count = log_stats.get('failed', 0)

    # 计算待发送数
    pending_count = total_count - sent_count - failed_count

    # 获取重试次数（任务状态变为retrying的次数）
    with get_db_connection() as conn:
        # 通过日志表查询重试记录
        retry_count = conn.execute("""
            SELECT COUNT(*) FROM uni_email_log
            WHERE task_id = ? AND status = 'failed'
        """, (task_id,)).fetchone()[0]

    return {
        'total_count': total_count,
        'sent_count': sent_count,
        'success_count': success_count,
        'failed_count': actual_failed_count,
        'pending_count': max(0, pending_count),
        'retry_count': retry_count
    }


def delete_task(task_id):
    """删除单个任务及其相关日志

    Args:
        task_id: 任务ID

    Returns:
        (success, message) tuple
    """
    with get_db_connection() as conn:
        # 检查任务是否存在
        task = conn.execute(
            "SELECT task_id, status FROM uni_email_task WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if not task:
            return False, "任务不存在"

        status = task.get('status') if isinstance(task, dict) else task[1]

        # 正在运行的任务不能删除
        if status == 'running':
            return False, "正在执行的任务不能删除，请先停止任务"

        # 删除相关日志
        conn.execute("DELETE FROM uni_email_log WHERE task_id = ?", (task_id,))

        # 删除任务
        conn.execute("DELETE FROM uni_email_task WHERE task_id = ?", (task_id,))

        conn.commit()
        return True, "删除成功"


def delete_tasks_batch(task_ids):
    """批量删除任务

    Args:
        task_ids: list 任务ID列表

    Returns:
        (success_count, failed_list) tuple
            success_count: 成功删除数量
            failed_list: [{"task_id": xxx, "reason": xxx}, ...] 失败列表
    """
    success_count = 0
    failed_list = []

    for task_id in task_ids:
        success, message = delete_task(task_id)
        if success:
            success_count += 1
        else:
            failed_list.append({"task_id": task_id, "reason": message})

    return success_count, failed_list