"""
邮件发送核心模块
实现SMTP邮件发送、后台Worker、进度追踪等功能
"""
import smtplib
import threading
import time
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os

from Sills.db_email_task import (
    get_task_by_id, get_task_contacts, get_task_failed_contacts, update_task_progress,
    is_cancel_requested, complete_task, error_task
)
from Sills.db_email_log import add_log
from Sills.db_email_account import (
    get_account_by_id, can_send_today, increment_sent_count
)
from Sills.db_contact import update_contact_marketing_status
from Sills.crypto_utils import decrypt_password as aes_decrypt


def save_sent_email_to_mail(send_result, account_id=None):
    """将发送成功的邮件保存到uni_mail表

    Args:
        send_result: send_single_email返回的结果字典
        account_id: 发件账号ID

    Returns:
        bool: 是否保存成功
    """
    from Sills.db_mail_core import save_email

    try:
        mail_data = {
            'subject': send_result.get('subject', ''),
            'from_addr': PRIMARY_EMAIL,  # 显示的发件人（主账号）
            'from_name': '',
            'to_addr': send_result.get('to_email', ''),
            'cc_addr': FIXED_CC_EMAIL,
            'content': '',
            'html_content': send_result.get('body', ''),
            'sent_at': datetime.now().isoformat(),
            'is_sent': 1,
            'is_read': 1,  # 已发送邮件标记为已读
            'message_id': send_result.get('message_id', ''),
            'sync_status': 'completed',
            'account_id': account_id
        }
        save_email(mail_data)
        return True
    except Exception as e:
        print(f"[Worker] 保存到uni_mail失败: {e}")
        return False


# 固定CC收件人
FIXED_CC_EMAIL = "jinzheng519@163.com"
# 报告接收邮箱
REPORT_EMAIL = "joy@unicornsemi.com"
# 主账号邮箱（用于代理发送）
PRIMARY_EMAIL = "joy@unicornsemi.com"


class EmailSenderWorker:
    """邮件发送Worker类"""

    def __init__(self, task_id, retry_mode=False):
        self.task_id = task_id
        self.retry_mode = retry_mode  # 是否重试模式（只发失败邮件）
        self.task = None
        self.accounts = []  # 账号列表（支持多账号轮换）
        self.current_account_index = 0  # 当前账号索引
        self.contacts = []
        self.stop_flag = False
        self.thread = None
        self.server = None  # SMTP连接

    def load_task_data(self):
        """加载任务数据"""
        self.task = get_task_by_id(self.task_id)
        if not self.task:
            raise ValueError(f"任务 {self.task_id} 不存在")

        # 获取账号列表
        accounts_info = self.task.get('accounts_info', [])
        if not accounts_info:
            raise ValueError("任务没有关联的发件人账号")

        # 解密所有账号密码
        for acc in accounts_info:
            if acc.get('password'):
                try:
                    acc['password'] = aes_decrypt(acc['password'])
                except:
                    pass

        self.accounts = accounts_info
        # 重试模式从第0个账号重新开始，不沿用上次的失败账号索引
        if self.retry_mode:
            self.current_account_index = 0
        else:
            self.current_account_index = self.task.get('current_account_index', 0) or 0

        # 获取联系人列表：重试模式只获取失败联系人
        if self.retry_mode:
            self.contacts = get_task_failed_contacts(self.task_id)
            if not self.contacts:
                raise ValueError("没有发送失败的联系人，无需重试")
        else:
            self.contacts = get_task_contacts(self.task_id)

    def get_current_account(self):
        """获取当前使用的账号"""
        if self.current_account_index >= len(self.accounts):
            return None
        return self.accounts[self.current_account_index]

    def switch_to_next_account(self):
        """切换到下一个账号"""
        if self.current_account_index < len(self.accounts) - 1:
            self.current_account_index += 1
            from Sills.db_email_task import update_current_account_index
            update_current_account_index(self.task_id, self.current_account_index)
            print(f"[Worker] 切换到账号 {self.current_account_index + 1}: {self.accounts[self.current_account_index].get('email')}")
            return True
        return False

    def connect_smtp(self, account=None):
        """连接SMTP服务器"""
        if account is None:
            account = self.get_current_account()
        if not account:
            raise ValueError("没有可用的发件人账号")

        email = account['email']
        password = account['password']
        smtp_server = account.get('smtp_server', 'smtp.163.com')

        # 清除代理环境变量(避免代理拦截SMTP SSL连接)
        proxy_keys = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']
        proxy_backup = {k: os.environ.pop(k) for k in proxy_keys if k in os.environ}

        try:
            server = smtplib.SMTP_SSL(smtp_server, 465, timeout=20)
            server.login(email.strip(), password.strip())
            return server
        finally:
            os.environ.update(proxy_backup)

    def _is_connection_error(self, error):
        """判断是否为SMTP连接类错误

        Returns:
            bool 是否为连接类错误（需要重连）
        """
        error_str = str(error).lower()
        connection_keywords = [
            'please run connect() first',
            'connection',
            'timed out',
            'timeout',
            '421',
            'broken pipe',
            'server disconnected',
            'connection reset',
            'eof occurred',
        ]
        if isinstance(error, (smtplib.SMTPServerDisconnected, ConnectionError, OSError)):
            return True
        for kw in connection_keywords:
            if kw in error_str:
                return True
        return False

    def _reconnect_smtp(self, old_server, max_retries=2):
        """尝试重连当前账号的SMTP（指数退避）

        Args:
            old_server: 旧的SMTP连接（将被关闭）
            max_retries: 最大重试次数，默认2次

        Returns:
            新的SMTP连接，或None（重连失败）
        """
        account = self.get_current_account()
        if not account:
            return None

        for attempt in range(max_retries):
            wait_time = 5 * (3 ** attempt)  # 5s, 15s 指数退避
            print(f"[Worker] SMTP重连第{attempt + 1}次，等待{wait_time}秒后重试...")
            time.sleep(wait_time)

            try:
                # 关闭旧连接（忽略错误）
                if old_server:
                    try:
                        old_server.quit()
                    except:
                        pass

                new_server = self.connect_smtp(account)
                print(f"[Worker] SMTP重连成功: {account.get('email')}")
                return new_server
            except Exception as e:
                print(f"[Worker] SMTP重连第{attempt + 1}次失败: {e}")

        return None

    def _try_reconnect_or_switch(self, old_server):
        """尝试重连当前账号，失败则逐个切换到其他账号

        Args:
            old_server: 旧的SMTP连接

        Returns:
            (success, new_server, error_detail) - success=True时new_server为有效连接
        """
        all_errors = []

        # 1. 尝试重连当前账号
        new_server = self._reconnect_smtp(old_server, max_retries=2)
        if new_server:
            return True, new_server, ""

        # 2. 当前账号重连失败，逐个尝试剩余账号
        print(f"[Worker] 当前账号重连失败，尝试切换到其他账号")
        for _ in range(len(self.accounts)):
            if self.switch_to_next_account():
                acc = self.get_current_account()
                try:
                    new_server = self.connect_smtp(acc)
                    print(f"[Worker] 切换到账号 {acc.get('email')} 成功")
                    return True, new_server, ""
                except Exception as e:
                    err_msg = f"{acc.get('email')}: {e}"
                    all_errors.append(err_msg)
                    print(f"[Worker] 切换到账号 {acc.get('email')} 失败: {e}")

        # 3. 所有账号都连不上
        error_detail = " | ".join(all_errors)
        print(f"[Worker] 所有账号均无法连接: {error_detail}")
        return False, None, error_detail

    def send_single_email(self, server, to_email, company_name=""):
        """发送单封邮件（支持代理发送）

        Returns:
            dict: {'success': bool, 'message_id': str, 'subject': str, 'body': str}
        """
        account = self.get_current_account()
        if not account:
            raise ValueError("没有可用的发件人账号")

        email = account['email']
        subject = self.task['subject']
        body = self.task['body']

        # 替换占位符（支持 {公司名} 和 @# 两种格式）
        subject = subject.replace('{公司名}', company_name).replace('@#', company_name)
        body = body.replace('{公司名}', company_name).replace('@#', company_name)

        message = MIMEMultipart()
        html_part = MIMEText(body, 'html', 'utf-8')
        message.attach(html_part)

        message['Subject'] = subject
        message['To'] = to_email
        message['Cc'] = FIXED_CC_EMAIL

        # 代理发送逻辑：客户看到的发件人始终是 PRIMARY_EMAIL
        if email.lower() == PRIMARY_EMAIL.lower():
            # 发件人就是主账号，直接发送
            message['From'] = email
        else:
            # 发件人不是主账号，代理发送
            # From: 主账号（客户看到的）
            # Sender: 实际发送账号（邮件客户端显示"代理发送")
            message['From'] = PRIMARY_EMAIL
            message['Sender'] = email

        # 发送邮件（实际SMTP认证用的是当前账号的邮箱）
        server.sendmail(email, [to_email, FIXED_CC_EMAIL], message.as_string())

        # 返回发送结果，用于保存到uni_mail
        return {
            'success': True,
            'message_id': message.get('Message-ID', ''),
            'subject': subject,
            'body': body,
            'from_email': email,
            'to_email': to_email
        }

    def is_in_schedule_time(self):
        """已移除发送时间段限制，任意时间均允许发送"""
        return True

    def run(self):
        """Worker主循环（支持多账号轮换）"""
        sent_count = 0
        failed_count = 0
        skipped_count = 0
        account_sent_counts = {}  # 每个账号的发送计数

        # 去重集合：记录已跳过/已失败的邮箱（避免同一邮箱多次计数）
        skipped_email_set = set()  # 已跳过的邮箱
        failed_email_set = set()   # 已失败的邮箱
        consecutive_550_count = 0  # 当前账号连续550 DT:SPM计数

        try:
            self.load_task_data()

            # 获取账号数量限制
            daily_limit_per_account = self.task.get('daily_limit_per_account', 1800) or 1800

            # 连接SMTP：从当前账号开始，失败则从头逐个尝试
            current_account = self.get_current_account()
            if not current_account:
                raise ValueError("没有可用的发件人账号")

            server = None
            init_errors = []
            # 先尝试当前账号
            try:
                server = self.connect_smtp(current_account)
                print(f"[Worker] 使用账号 {self.current_account_index + 1}: {current_account.get('email')}")
            except Exception as e:
                init_errors.append(f"{current_account.get('email')}: {e}")
                print(f"[Worker] 当前账号({current_account.get('email')})连接失败: {e}，从第1个账号重新尝试...")
                # 从第0个账号逐个尝试
                for idx, acc in enumerate(self.accounts):
                    try:
                        server = self.connect_smtp(acc)
                        self.current_account_index = idx
                        from Sills.db_email_task import update_current_account_index
                        update_current_account_index(self.task_id, idx)
                        print(f"[Worker] 切换到账号 {idx + 1}: {acc.get('email')} 成功")
                        break
                    except Exception as e2:
                        init_errors.append(f"{acc.get('email')}: {e2}")
                        print(f"[Worker] 账号 {acc.get('email')} 连接失败: {e2}")

            if server is None:
                raise ValueError(f"所有账号均无法连接: {' | '.join(init_errors)}")

            # 初始化账号发送计数
            for i, acc in enumerate(self.accounts):
                account_sent_counts[i] = 0

            total = len(self.contacts)
            mode_str = "[重试模式]" if self.retry_mode else ""

            # 获取已发送成功的联系人列表（用于跳过当前任务重复）
            from Sills.db_email_log import get_sent_emails_for_task
            sent_emails = get_sent_emails_for_task(self.task_id)
            sent_email_set = set(e.lower() for e in sent_emails)

            # 获取跳过规则配置
            skip_enabled = self.task.get('skip_enabled', 1)  # 0=不跳过, 1=跳过
            skip_days = self.task.get('skip_days', 7)

            # 如果启用跳过规则，获取最近N天内成功发送的邮箱列表（不限任务）
            recently_sent_set = set()
            if skip_enabled == 1 and not self.retry_mode:
                from Sills.db_email_log import get_recently_sent_emails
                recently_sent_set = get_recently_sent_emails(skip_days)
                print(f"[Worker] 启用跳过规则：{skip_days}天内已发送的邮箱将被跳过，共{len(recently_sent_set)}个")

            # 获取任务当前的进度计数
            task = get_task_by_id(self.task_id)
            base_sent = task.get('sent_count', 0) or 0
            base_failed = task.get('failed_count', 0) or 0
            base_skipped = task.get('skipped_count', 0) or 0

            for idx, contact in enumerate(self.contacts):
                # 检查取消请求
                if is_cancel_requested(self.task_id):
                    self.stop_flag = True
                    break

                # 检查时间段
                while not self.is_in_schedule_time():
                    if is_cancel_requested(self.task_id):
                        self.stop_flag = True
                        break
                    time.sleep(60)  # 每分钟检查一次

                if self.stop_flag:
                    break

                # 检查当前账号是否达到日限
                current_account = self.get_current_account()
                if not current_account:
                    # 所有账号都达到限制
                    print(f"[Worker] 所有账号均已达到日限,等待到第二天继续")
                    update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                    error_task(self.task_id, "所有账号均已达到日发送限制,等待第二天继续")
                    server.quit()
                    return

                # 检查账号日发送限制（使用任务的daily_limit_per_account）
                can_send, remaining = can_send_today(current_account['account_id'], daily_limit_per_account)
                if not can_send:
                    # 当前账号达到限制，尝试切换下一个账号
                    print(f"[Worker] 账号 {current_account.get('email')} 达到日限({daily_limit_per_account}),尝试切换下一个账号")
                    server.quit()

                    if self.switch_to_next_account():
                        next_account = self.get_current_account()
                        server = self.connect_smtp(next_account)
                        print(f"[Worker] 已切换到账号 {next_account.get('email')}")
                        continue
                    else:
                        # 所有账号都达到限制
                        print(f"[Worker] 所有账号均已达到日限,等待到第二天继续")
                        update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                        error_task(self.task_id, "所有账号均已达到日发送限制,等待第二天继续")
                        server.quit()
                        return

                # 每50封NOOP探活，提前发现死连接
                if sent_count > 0 and sent_count % 50 == 0:
                    try:
                        server.noop()
                    except Exception as e:
                        print(f"[Worker] NOOP探活失败: {e}，尝试重连...")
                        success, server, err_detail = self._try_reconnect_or_switch(server)
                        if not success:
                            update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                            error_task(self.task_id, f"SMTP连接断开且所有账号均无法重连: {err_detail}")
                            return

                # 每200封主动重连，避免长连接被中途断开
                if sent_count > 0 and sent_count % 200 == 0:
                    try:
                        server.quit()
                    except:
                        pass
                    current_account = self.get_current_account()
                    try:
                        server = self.connect_smtp(current_account)
                        print(f"[Worker] 主动重连: {current_account.get('email')}")
                    except Exception as e:
                        print(f"[Worker] 主动重连失败: {e}，尝试切换账号...")
                        success, server, err_detail = self._try_reconnect_or_switch(server)
                        if not success:
                            update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                            error_task(self.task_id, f"SMTP主动重连失败且所有账号均无法连接: {err_detail}")
                            return

                email_addr = contact.get('email', '')
                contact_id = contact.get('contact_id', '')
                # 优先用 prospect_name（真实公司名），fallback 到 company
                company_name = contact.get('prospect_name') or contact.get('company', '')

                if not email_addr:
                    continue

                # 跳过已发送成功的联系人（当前任务内重复）
                if email_addr.lower() in sent_email_set:
                    print(f"[Worker] {mode_str} 跳过已发送(当前任务): {email_addr}")
                    # 去重计数：同一个邮箱只计一次跳过
                    if email_addr.lower() not in skipped_email_set:
                        skipped_email_set.add(email_addr.lower())
                        skipped_count += 1
                    update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                    continue

                # 跳过规则：N天内已成功发送的邮箱（不限任务）
                if skip_enabled == 1 and email_addr.lower() in recently_sent_set:
                    print(f"[Worker] {mode_str} 跳过(最近{skip_days}天已发送): {email_addr}")
                    # 去重计数：同一个邮箱只计一次
                    if email_addr.lower() not in skipped_email_set:
                        skipped_email_set.add(email_addr.lower())
                        skipped_count += 1
                    update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                    continue

                try:
                    send_result = self.send_single_email(server, email_addr, company_name)
                    # 获取当前账号信息用于记录
                    current_account_id = current_account.get('account_id')
                    current_account_email = current_account.get('email')

                    # 重试模式：更新之前失败的日志状态为成功
                    if self.retry_mode:
                        from Sills.db_email_log import update_log_status
                        update_log_status(self.task_id, email_addr, 'sent', None, current_account_id, current_account_email)
                    else:
                        add_log(self.task_id, contact_id, email_addr, company_name, 'sent', None, current_account_id, current_account_email)

                    # 保存到uni_mail表（确保邮件系统数据一致性）
                    if send_result.get('success'):
                        save_sent_email_to_mail(send_result, current_account_id)
                    sent_count += 1
                    account_sent_counts[self.current_account_index] += 1
                    increment_sent_count(current_account['account_id'])
                    consecutive_550_count = 0  # 发送成功，重置550计数

                    # 更新联系人营销状态（send_count++, last_sent_at）
                    if contact_id:
                        update_contact_marketing_status(contact_id, 'sent')
                    else:
                        # 如果没有contact_id，尝试通过email查找并更新
                        from Sills.db_contact import get_contact_by_email
                        existing_contact = get_contact_by_email(email_addr)
                        if existing_contact and existing_contact.get('contact_id'):
                            update_contact_marketing_status(existing_contact['contact_id'], 'sent')

                    # 更新进度（累加原有进度）
                    update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)

                    print(f"[Worker] {mode_str} [{current_account_email}] 已发送 {base_sent + sent_count}/{total} 到 {email_addr} (账号{self.current_account_index + 1})")

                    # 发送间隔(使用任务配置的间隔，避免过快)
                    send_interval = self.task.get('send_interval', 2) or 2
                    time.sleep(send_interval)

                except Exception as e:
                    error_msg = str(e)

                    # 判断是否为连接类错误 → 自动重连并重试当前邮件
                    if self._is_connection_error(e):
                        print(f"[Worker] {mode_str} 检测到连接错误: {error_msg}，尝试重连...")
                        success, server, err_detail = self._try_reconnect_or_switch(server)

                        if success:
                            # 重连成功，重试发送当前邮件
                            try:
                                send_result = self.send_single_email(server, email_addr, company_name)
                                current_account = self.get_current_account()
                                current_account_id = current_account.get('account_id')
                                current_account_email = current_account.get('email')

                                if self.retry_mode:
                                    from Sills.db_email_log import update_log_status
                                    update_log_status(self.task_id, email_addr, 'sent', None, current_account_id, current_account_email)
                                else:
                                    add_log(self.task_id, contact_id, email_addr, company_name, 'sent', None, current_account_id, current_account_email)

                                if send_result.get('success'):
                                    save_sent_email_to_mail(send_result, current_account_id)
                                sent_count += 1
                                account_sent_counts[self.current_account_index] += 1
                                increment_sent_count(current_account['account_id'])
                                consecutive_550_count = 0  # 重连后发送成功，重置550计数

                                if contact_id:
                                    update_contact_marketing_status(contact_id, 'sent')
                                else:
                                    from Sills.db_contact import get_contact_by_email
                                    existing_contact = get_contact_by_email(email_addr)
                                    if existing_contact and existing_contact.get('contact_id'):
                                        update_contact_marketing_status(existing_contact['contact_id'], 'sent')

                                update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                                print(f"[Worker] {mode_str} [{current_account_email}] 重连后发送成功 {base_sent + sent_count}/{total} 到 {email_addr} (账号{self.current_account_index + 1})")

                                send_interval = self.task.get('send_interval', 2) or 2
                                time.sleep(send_interval)
                                continue  # 重试成功，继续下一个联系人

                            except Exception as retry_e:
                                # 重连后重试仍然失败，按普通失败处理
                                error_msg = str(retry_e)
                                current_account = self.get_current_account()
                                current_account_id = current_account.get('account_id')
                                current_account_email = current_account.get('email')
                                print(f"[Worker] {mode_str} 重连后重试仍然失败 {email_addr}: {error_msg}")
                        else:
                            # 所有账号都无法重连，任务终止
                            update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                            error_task(self.task_id, f"SMTP连接断开且所有账号均无法重连: {err_detail}")
                            return

                    # 非连接错误，或重连后重试仍失败 → 检查550 DT:SPM
                    current_account = self.get_current_account()
                    current_account_id = current_account.get('account_id')
                    current_account_email = current_account.get('email')

                    # 检测550 DT:SPM反垃圾拦截，连续5次切换到下一个账号
                    if '550' in error_msg and 'DT:SPM' in error_msg:
                        consecutive_550_count += 1
                        print(f"[Worker] {mode_str} [{current_account_email}] 550 DT:SPM拦截 ({consecutive_550_count}/5) {email_addr}")
                        if consecutive_550_count >= 5:
                            print(f"[Worker] {mode_str} 账号 {current_account_email} 连续{consecutive_550_count}次550拦截，切换到下一个账号")
                            consecutive_550_count = 0  # 重置计数
                            try:
                                server.quit()
                            except:
                                pass
                            if self.switch_to_next_account():
                                next_account = self.get_current_account()
                                try:
                                    server = self.connect_smtp(next_account)
                                    print(f"[Worker] 已切换到账号 {next_account.get('email')}，重试当前邮件")
                                    # 用新账号重试当前邮件
                                    try:
                                        send_result = self.send_single_email(server, email_addr, company_name)
                                        next_account_id = next_account.get('account_id')
                                        next_account_email = next_account.get('email')
                                        if self.retry_mode:
                                            from Sills.db_email_log import update_log_status
                                            update_log_status(self.task_id, email_addr, 'sent', None, next_account_id, next_account_email)
                                        else:
                                            add_log(self.task_id, contact_id, email_addr, company_name, 'sent', None, next_account_id, next_account_email)
                                        if send_result.get('success'):
                                            save_sent_email_to_mail(send_result, next_account_id)
                                        sent_count += 1
                                        account_sent_counts[self.current_account_index] += 1
                                        increment_sent_count(next_account['account_id'])
                                        consecutive_550_count = 0
                                        if contact_id:
                                            update_contact_marketing_status(contact_id, 'sent')
                                        else:
                                            from Sills.db_contact import get_contact_by_email
                                            existing_contact = get_contact_by_email(email_addr)
                                            if existing_contact and existing_contact.get('contact_id'):
                                                update_contact_marketing_status(existing_contact['contact_id'], 'sent')
                                        update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                                        print(f"[Worker] {mode_str} [{next_account_email}] 切换账号后发送成功 {base_sent + sent_count}/{total} 到 {email_addr}")
                                        send_interval = self.task.get('send_interval', 2) or 2
                                        time.sleep(send_interval)
                                        continue  # 成功，继续下一个
                                    except Exception as retry_e:
                                        retry_error_msg = str(retry_e)
                                        print(f"[Worker] {mode_str} 切换账号后重试仍失败 {email_addr}: {retry_error_msg}")
                                        error_msg = retry_error_msg
                                        current_account = self.get_current_account()
                                        current_account_id = current_account.get('account_id')
                                        current_account_email = current_account.get('email')
                                except Exception as conn_e:
                                    print(f"[Worker] 切换账号 {next_account.get('email')} 连接失败: {conn_e}")
                            else:
                                # 所有账号都已轮完，说明邮件内容被拦截
                                update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                                error_task(self.task_id, "所有账号均连续触发550 DT:SPM反垃圾拦截，请检查邮件内容")
                                return
                    else:
                        # 非550错误，重置550计数器
                        consecutive_550_count = 0

                    # 记录失败日志
                    if self.retry_mode:
                        from Sills.db_email_log import update_log_status
                        update_log_status(self.task_id, email_addr, 'failed', error_msg, current_account_id, current_account_email)
                    else:
                        add_log(self.task_id, contact_id, email_addr, company_name, 'failed', error_msg, current_account_id, current_account_email)
                    # 去重计数：同一个邮箱只计一次失败
                    if email_addr.lower() not in failed_email_set:
                        failed_email_set.add(email_addr.lower())
                        failed_count += 1
                    update_task_progress(self.task_id, base_sent + sent_count, base_failed + failed_count, base_skipped + skipped_count)
                    print(f"[Worker] {mode_str} 发送失败 {email_addr}: {error_msg}")
                    # 继续发送下一个

            # 断开连接
            server.quit()

            # 任务完成判断：所有联系人已处理完毕（不再依赖累加计数）
            # 判断方式：本次循环遍历完所有联系人，且未被中断
            if not self.stop_flag:
                complete_task(self.task_id, base_failed + failed_count)

            # 发送报告邮件
            accounts_summary = ", ".join([f"{acc.get('email')}: {account_sent_counts[i]}封" for i, acc in enumerate(self.accounts) if account_sent_counts[i] > 0])
            self.send_report_email(sent_count, failed_count, skipped_count, accounts_summary)

        except Exception as e:
            import traceback
            error_detail = f"{str(e)} | {traceback.format_exc()}"
            print(f"[Worker] 任务异常终止: {error_detail}")
            error_task(self.task_id, str(e))
            print(f"[Worker] 任务出错: {e}")

    def send_report_email(self, sent_count, failed_count, skipped_count=0, accounts_summary=""):
        """发送任务完成报告（使用主账号发送）"""
        try:
            # 使用主账号发送报告
            primary_account = self.accounts[0] if self.accounts else None
            if not primary_account:
                print("[Worker] 无可用账号，跳过发送报告")
                return

            server = self.connect_smtp(primary_account)

            mode_str = "(重试)" if self.retry_mode else ""
            subject = f"[开发信管理] 任务完成报告{mode_str} - {self.task['task_name']}"
            skip_info = f"<p><strong style=\"color: orange;\">跳过(已发送):</strong> {skipped_count}</p>" if skipped_count > 0 else ""
            accounts_info = f"<p><strong>各账号发送:</strong> {accounts_summary}</p>" if accounts_summary else ""

            primary_email = primary_account.get('email', 'unknown')

            body = f"""
            <html>
            <body>
            <h2>邮件任务完成报告</h2>
            <p><strong>任务名称:</strong> {self.task['task_name']}</p>
            <p><strong>发件人:</strong> {primary_email}</p>
            <p><strong>发送模式:</strong> {mode_str if self.retry_mode else "正常发送"}</p>
            <p><strong>发送时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <hr>
            <p><strong>本次处理:</strong> {len(self.contacts)}</p>
            <p><strong style="color: green;">成功发送:</strong> {sent_count}</p>
            <p><strong style="color: red;">发送失败:</strong> {failed_count}</p>
            {skip_info}
            {accounts_info}
            <hr>
            <p><em>此报告由系统自动发送</em></p>
            </body>
            </html>
            """

            message = MIMEMultipart()
            html_part = MIMEText(body, 'html', 'utf-8')
            message.attach(html_part)
            message['Subject'] = subject
            message['To'] = REPORT_EMAIL
            message['Cc'] = FIXED_CC_EMAIL

            # 报告邮件使用主账号发送
            email = primary_email
            if email.lower() == PRIMARY_EMAIL.lower():
                message['From'] = email
            else:
                message['From'] = PRIMARY_EMAIL
                message['Sender'] = email

            server.sendmail(email, [REPORT_EMAIL, FIXED_CC_EMAIL], message.as_string())
            server.quit()

            print(f"[Worker] 报告已发送到 {REPORT_EMAIL}")

        except Exception as e:
            print(f"[Worker] 发送报告失败: {e}")

    def start(self):
        """启动Worker线程"""
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        """停止Worker"""
        self.stop_flag = True


def start_email_worker(task_id, retry_mode=False):
    """启动邮件发送Worker

    Args:
        task_id: 任务ID
        retry_mode: 是否重试模式（只发送失败邮件）

    Returns:
        EmailSenderWorker instance
    """
    worker = EmailSenderWorker(task_id, retry_mode)
    worker.start()
    return worker


def send_test_email(account_id, to_email, subject="测试邮件", body="<p>这是一封测试邮件</p>"):
    """发送测试邮件（支持代理发送）

    Args:
        account_id: 发件人账号ID
        to_email: 收件人邮箱
        subject: 邮件主题
        body: 邮件内容

    Returns:
        (success, message) tuple
    """
    try:
        account = get_account_by_id(account_id)
        if not account:
            return False, "发件人账号不存在"

        email = account['email']
        password = account['password']
        smtp_server = account.get('smtp_server', 'smtp.163.com')

        # 清除代理
        proxy_keys = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']
        proxy_backup = {k: os.environ.pop(k) for k in proxy_keys if k in os.environ}

        try:
            server = smtplib.SMTP_SSL(smtp_server, 465, timeout=20)
            server.login(email.strip(), password.strip())
        finally:
            os.environ.update(proxy_backup)

        message = MIMEMultipart()
        html_part = MIMEText(body, 'html', 'utf-8')
        message.attach(html_part)
        message['Subject'] = subject
        message['To'] = to_email
        message['Cc'] = FIXED_CC_EMAIL

        # 代理发送逻辑
        if email.lower() == PRIMARY_EMAIL.lower():
            message['From'] = email
        else:
            message['From'] = PRIMARY_EMAIL
            message['Sender'] = email

        server.sendmail(email, [to_email, FIXED_CC_EMAIL], message.as_string())
        server.quit()

        return True, f"测试邮件已发送到 {to_email}"
    except Exception as e:
        return False, str(e)