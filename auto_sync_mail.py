"""
邮件自动同步脚本
按月递减同步邮件，从当前月份同步到指定截止月份

使用方法:
    python auto_sync_mail.py --end 2024-10
    python auto_sync_mail.py --start 2025-12 --end 2025-06

参数:
    --end: 截止年月，格式 YYYY-MM，默认 2024-10
    --start: 起始年月，格式 YYYY-MM，可选（默认同步到当前月份）
    --account: 邮箱账户ID，默认使用当前配置的账户
"""

import sys
import time
import argparse
from datetime import datetime, timedelta
from calendar import monthrange

# 添加项目路径
sys.path.insert(0, '.')

from Sills.db_mail import (
    get_mail_config,
    set_sync_date_range,
    get_db_connection,
    get_sync_progress,
    is_sync_locked
)
from Sills.mail_service import sync_inbox


def get_current_sync_progress():
    """获取当前同步进度"""
    progress = get_sync_progress()
    return progress


def wait_for_sync_complete(timeout_minutes=30):
    """等待当前同步完成"""
    start_time = time.time()
    while time.time() - start_time < timeout_minutes * 60:
        if not is_sync_locked():
            return True
        time.sleep(5)
    return False


def count_emails_in_range(start_date, end_date):
    """估算指定日期范围内的邮件数量"""
    from Sills.mail_service import IMAPClient

    config = get_mail_config()
    if not config:
        return 0

    try:
        client = IMAPClient(config)
        client.connect()

        # 转换日期格式
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        end_dt_search = end_dt + timedelta(days=1)
        start_str = start_dt.strftime('%d-%b-%Y')
        end_str = end_dt_search.strftime('%d-%b-%Y')

        total_count = 0

        # 检查主要文件夹
        folders = ['INBOX', '&XfJT0ZAB-']  # 收件箱和发件箱

        for folder in folders:
            try:
                status, _ = client.client.select(folder)
                if status == 'OK':
                    status, messages = client.client.search(None, f'SINCE {start_str} BEFORE {end_str}')
                    if status == 'OK':
                        count = len(messages[0].split())
                        total_count += count
                        print(f"  {folder}: {count} 封")
            except Exception as e:
                print(f"  {folder}: 检查失败 - {e}")

        client.disconnect()
        return total_count

    except Exception as e:
        print(f"连接失败: {e}")
        return 0


def auto_sync(end_month='2024-10', start_month=None, dry_run=False):
    """
    自动按月同步邮件

    Args:
        end_month: 截止年月，格式 YYYY-MM
        start_month: 起始年月，格式 YYYY-MM（可选，默认为当前月份）
        dry_run: 仅模拟运行，不实际同步
    """
    print("=" * 60)
    print("邮件自动同步脚本")
    print("=" * 60)

    # 解析截止日期
    end_date = datetime.strptime(end_month, '%Y-%m')
    current_date = datetime.now()

    # 如果指定了起始月份，用它代替当前月份
    if start_month:
        start_date = datetime.strptime(start_month, '%Y-%m')
        # 确保 start_date 不超过当前月份
        if start_date > current_date:
            start_date = current_date
    else:
        start_date = current_date

    print(f"同步范围: {end_date.strftime('%Y-%m')} 至 {start_date.strftime('%Y-%m')}")
    print(f"模式: {'模拟运行' if dry_run else '实际同步'}")
    print()

    # 检查邮件配置
    config = get_mail_config()
    if not config:
        print("错误: 未找到邮件配置，请先在邮件中心配置邮箱")
        return

    print(f"邮箱账户: {config.get('username')}")
    print()

    # 生成月份列表（从起始月往前到截止月）
    months_to_sync = []
    current_month = start_date.replace(day=1)

    while current_month >= end_date:
        # 计算该月的起始和结束日期
        year = current_month.year
        month = current_month.month
        _, last_day = monthrange(year, month)
        month_start = current_month.replace(day=1)
        month_end = current_month.replace(day=last_day)

        # 如果是起始月，结束日期用该月最后一天或今天（如果起始月是当前月份）
        if start_month and current_month.month == start_date.month and current_month.year == start_date.year:
            # 起始月是当前月份，用今天作为结束日期
            if current_month.month == current_date.month and current_month.year == current_date.year:
                month_end = current_date
            else:
                # 起始月不是当前月份，用该月最后一天
                month_end = month_end.replace(day=last_day)
        elif current_month.month == current_date.month and current_month.year == current_date.year:
            # 没指定起始月且是当前月份，用今天
            month_end = current_date

        months_to_sync.append({
            'month': current_month.strftime('%Y-%m'),
            'start': month_start.strftime('%Y-%m-%d'),
            'end': month_end.strftime('%Y-%m-%d')
        })

        # 移动到上一个月
        prev_month = current_month.month - 1
        prev_year = current_month.year
        if prev_month < 1:
            prev_month = 12
            prev_year -= 1
        current_month = current_month.replace(year=prev_year, month=prev_month)

    # 反转，从最早的月份开始同步
    months_to_sync.reverse()

    print(f"共需同步 {len(months_to_sync)} 个月份:")
    for m in months_to_sync:
        print(f"  - {m['month']}: {m['start']} 至 {m['end']}")
    print()

    if dry_run:
        print("模拟运行，仅估算邮件数量...")
        for m in months_to_sync:
            print(f"\n检查 {m['month']}...")
            count = count_emails_in_range(m['start'], m['end'])
            print(f"  预计邮件数: {count}")
        return

    # 开始同步
    total_synced = 0

    for i, month_info in enumerate(months_to_sync, 1):
        print("\n" + "=" * 60)
        print(f"[{i}/{len(months_to_sync)}] 同步 {month_info['month']}")
        print(f"日期范围: {month_info['start']} 至 {month_info['end']}")
        print("=" * 60)

        # 设置同步日期范围
        set_sync_date_range(month_info['start'], month_info['end'])
        print(f"已设置同步日期范围")

        # 等待之前的同步完成
        if is_sync_locked():
            print("等待之前的同步完成...")
            if not wait_for_sync_complete():
                print("超时：之前的同步未完成，跳过本月")
                continue

        # 执行同步
        print("开始同步...")
        try:
            result = sync_inbox()
            print(f"同步结果: {result}")

            # 获取同步的邮件数
            progress = get_sync_progress()
            synced = progress.get('synced_emails', 0)
            total_synced += synced
            print(f"本月同步: {synced} 封，累计: {total_synced} 封")

        except Exception as e:
            print(f"同步出错: {e}")
            import traceback
            traceback.print_exc()

        # 等待同步完成
        print("等待同步完成...")
        wait_time = 0
        max_wait = 60  # 最多等待60分钟

        while wait_time < max_wait:
            if not is_sync_locked():
                print("同步完成！")
                break

            progress = get_sync_progress()
            current = progress.get('synced_emails', 0)
            total = progress.get('total_emails', 0)
            message = progress.get('progress_message', '')

            print(f"  进度: {current}/{total} - {message}")
            time.sleep(10)
            wait_time += 10/60

        # 每个月份同步完成后休息一下
        if i < len(months_to_sync):
            print("休息 5 秒后继续...")
            time.sleep(5)

    print("\n" + "=" * 60)
    print("全部同步完成！")
    print(f"总计同步: {total_synced} 封邮件")
    print("=" * 60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='邮件自动同步脚本')
    parser.add_argument('--end', default='2024-10', help='截止年月，格式 YYYY-MM')
    parser.add_argument('--start', default=None, help='起始年月，格式 YYYY-MM（可选，默认为当前月份）')
    parser.add_argument('--dry-run', action='store_true', help='仅模拟运行，不实际同步')

    args = parser.parse_args()

    auto_sync(end_month=args.end, start_month=args.start, dry_run=args.dry_run)