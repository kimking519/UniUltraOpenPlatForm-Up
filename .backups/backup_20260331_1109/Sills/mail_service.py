"""
邮件服务层
SmartMail Integration - Mail Service Layer

IMAP/SMTP 客户端实现，支持后台同步
"""
import imaplib

# 增加 IMAP 行长度限制，避免大量UID时 "got more than 1000000 bytes" 错误
imaplib._MAXLINE = 10 * 1024 * 1024  # 10MB

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from email.utils import parseaddr
import email
from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid
import threading

from Sills.db_mail import (
    save_email, get_mail_config, acquire_sync_lock,
    release_sync_lock, update_mail_sync_status, recover_orphaned_syncs,
    update_sync_progress, get_sync_days, get_sync_date_range
)

# 全局取消同步标志（使用线程锁保证线程安全）
_cancel_sync_flag = threading.Event()


def request_cancel_sync():
    """请求取消同步"""
    _cancel_sync_flag.set()


def is_sync_cancelled() -> bool:
    """检查是否请求了取消同步"""
    return _cancel_sync_flag.is_set()


def reset_cancel_flag():
    """重置取消标志"""
    _cancel_sync_flag.clear()


class IMAPClient:
    """IMAP 邮件接收客户端"""

    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化 IMAP 客户端

        Args:
            config: 邮件配置（可选，未提供则从数据库读取）
        """
        self.config = config or get_mail_config()
        self.client = None

    def connect(self) -> bool:
        """建立 IMAP 连接"""
        if not self.config:
            raise ValueError("Mail config not found")

        try:
            server = self.config.get('imap_server')
            port = self.config.get('imap_port', 993)
            use_ssl = self.config.get('use_tls', 1)

            # 添加ID命令支持（163/126邮箱需要）
            imaplib.Commands['ID'] = ('NONAUTH', 'AUTH', 'SELECTED')

            if use_ssl:
                self.client = imaplib.IMAP4_SSL(server, port)
            else:
                self.client = imaplib.IMAP4(server, port)

            # 处理非ASCII字符密码 - IMAP LOGIN命令默认使用ASCII编码
            password = self.config['password']
            try:
                # 尝试ASCII编码登录
                self.client.login(self.config['username'], password)
            except UnicodeEncodeError:
                # 如果密码包含非ASCII字符，使用UTF-8编码
                # 通过AUTHENTICATE PLAIN命令实现
                import base64
                auth_string = f"\x00{self.config['username']}\x00{password}"
                auth_bytes = auth_string.encode('utf-8')
                encoded = base64.b64encode(auth_bytes).decode('ascii')
                self.client.authenticate('PLAIN', lambda x: encoded.encode('ascii'))

            # 发送ID命令（163/126等网易邮箱需要，否则会出现Unsafe Login错误）
            try:
                self.client._simple_command('ID', '("name" "Thunderbird" "version" "115.0")')
            except Exception as e:
                print(f"[Mail] ID命令发送失败（部分邮箱不需要）: {e}")

            return True
        except Exception as e:
            raise ConnectionError(f"IMAP connection failed: {str(e)}")

    def disconnect(self):
        """断开 IMAP 连接"""
        if self.client:
            try:
                self.client.close()
                self.client.logout()
            except:
                pass
            self.client = None

    def _decode_imap_utf7(self, s: str) -> str:
        """
        解码 IMAP UTF-7 编码的文件夹名称

        Args:
            s: 编码的字符串，如 '&XfJT0ZAB-'

        Returns:
            解码后的字符串，如 '已发送'
        """
        result = []
        i = 0
        while i < len(s):
            if s[i] == '&' and i + 1 < len(s) and s[i+1] != '-':
                # 找到结束符 '-'
                end = s.find('-', i)
                if end != -1:
                    # 提取编码部分
                    encoded = s[i+1:end]
                    # 将 ',' 替换回 '/' (IMAP UTF-7 特殊规则)
                    encoded = encoded.replace(',', '/')
                    # Base64 解码为 UTF-16-BE
                    import base64
                    try:
                        # 补齐 Base64 padding
                        padding = 4 - len(encoded) % 4
                        if padding != 4:
                            encoded += '=' * padding
                        decoded = base64.b64decode(encoded).decode('utf-16-be')
                        result.append(decoded)
                    except Exception as e:
                        print(f"[Mail] UTF-7 解码失败 '{s[i:end+1]}': {e}")
                        result.append(s[i:end+1])
                    i = end + 1
                    continue
            result.append(s[i])
            i += 1
        return ''.join(result)

    def list_folders(self) -> List[tuple]:
        """
        获取所有邮箱文件夹列表

        Returns:
            文件夹列表，每项为 (原始名称, 解码后名称)
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server")

        folders = []
        try:
            status, data = self.client.list()
            if status == 'OK':
                for item in data:
                    if item:
                        # 解析文件夹名称，格式如: (\HasNoChildren) "." "INBOX"
                        parts = item.decode().split('"')
                        if len(parts) >= 3:
                            folder_name = parts[-2] if parts[-2] else parts[-1].strip('"')
                        else:
                            folder_name = item.decode().split()[-1].strip('"')

                        # 解码 UTF-7 编码的名称
                        decoded_name = self._decode_imap_utf7(folder_name)
                        folders.append((folder_name, decoded_name))
                        print(f"[Mail] 发现文件夹: {folder_name} -> {decoded_name}")
        except Exception as e:
            print(f"[Mail] 获取文件夹列表失败: {e}")

        return folders

    def find_sent_folder(self) -> Optional[str]:
        """
        自动查找发件箱文件夹

        Returns:
            发件箱文件夹原始名称，未找到返回None
        """
        folders = self.list_folders()

        # 常见的发件箱名称（按优先级）
        sent_names = [
            'Sent', 'Sent Items', 'Sent Messages', '已发送', '发件箱', '发送',
            'INBOX.Sent', 'INBOX/Sent', 'Sent Mail'
        ]

        # 先精确匹配解码后的名称
        for raw_name, decoded_name in folders:
            if decoded_name in sent_names:
                print(f"[Mail] 找到发件箱: {raw_name} ({decoded_name})")
                return raw_name

        # 再模糊匹配
        for raw_name, decoded_name in folders:
            decoded_lower = decoded_name.lower()
            if 'sent' in decoded_lower or '发件' in decoded_name or '发送' in decoded_name:
                print(f"[Mail] 模糊匹配找到发件箱: {raw_name} ({decoded_name})")
                return raw_name

        print("[Mail] 未找到发件箱文件夹")
        return None

    def find_spam_folder(self) -> Optional[str]:
        """
        自动查找垃圾邮件文件夹

        Returns:
            垃圾邮件文件夹原始名称，未找到返回None
        """
        folders = self.list_folders()

        # 常见的垃圾邮件文件夹名称
        spam_names = [
            'Spam', 'Junk', 'Junk E-mail', '垃圾邮件', '垃圾箱',
            'Bulk Mail', '垃圾信', '&V4NXPpCuTvY-'  # IMAP UTF-7 编码的"垃圾邮件"
        ]

        # 先精确匹配解码后的名称
        for raw_name, decoded_name in folders:
            if decoded_name in spam_names or raw_name in spam_names:
                print(f"[Mail] 找到垃圾邮件文件夹: {raw_name} ({decoded_name})")
                return raw_name

        # 再模糊匹配
        for raw_name, decoded_name in folders:
            decoded_lower = decoded_name.lower()
            if 'spam' in decoded_lower or 'junk' in decoded_lower or '垃圾' in decoded_name:
                print(f"[Mail] 模糊匹配找到垃圾邮件文件夹: {raw_name} ({decoded_name})")
                return raw_name

        print("[Mail] 未找到垃圾邮件文件夹")
        return None

    def find_draft_folder(self) -> Optional[str]:
        """
        自动查找草稿箱文件夹

        Returns:
            草稿箱文件夹原始名称，未找到返回None
        """
        folders = self.list_folders()

        # 常见的草稿箱文件夹名称
        draft_names = [
            'Drafts', 'Draft', '草稿', '草稿箱',
            'INBOX.Drafts', 'INBOX/Drafts',
            '&g0l6P3ux-'  # IMAP UTF-7 编码
        ]

        # 先精确匹配解码后的名称
        for raw_name, decoded_name in folders:
            if decoded_name in draft_names or raw_name in draft_names:
                print(f"[Mail] 找到草稿箱: {raw_name} ({decoded_name})")
                return raw_name

        # 再模糊匹配
        for raw_name, decoded_name in folders:
            decoded_lower = decoded_name.lower()
            if 'draft' in decoded_lower or '草稿' in decoded_name:
                print(f"[Mail] 模糊匹配找到草稿箱: {raw_name} ({decoded_name})")
                return raw_name

        print("[Mail] 未找到草稿箱文件夹")
        return None

    def find_system_folder(self) -> Optional[str]:
        """
        自动查找系统邮件文件夹（退信、系统通知等）

        Returns:
            系统邮件文件夹原始名称，未找到返回None
        """
        folders = self.list_folders()

        # 常见的系统邮件/退信文件夹名称
        system_names = [
            'System', 'System Messages', '系统邮件', '系统通知',
            'Notifications', 'Notices', 'Alerts',
            'Undelivered', 'Bounced', 'Returned',
            '&fPt+35AAT+E-'  # IMAP UTF-7 编码的"系统邮件"
        ]

        # 先精确匹配解码后的名称
        for raw_name, decoded_name in folders:
            if decoded_name in system_names or raw_name in system_names:
                print(f"[Mail] 找到系统邮件文件夹: {raw_name} ({decoded_name})")
                return raw_name

        # 再模糊匹配（系统邮件、退信等）
        for raw_name, decoded_name in folders:
            decoded_lower = decoded_name.lower()
            if 'system' in decoded_lower or '系统' in decoded_name or 'notification' in decoded_lower:
                print(f"[Mail] 模糊匹配找到系统邮件文件夹: {raw_name} ({decoded_name})")
                return raw_name

        # 查找退信文件夹（退回、bounced等）
        for raw_name, decoded_name in folders:
            decoded_lower = decoded_name.lower()
            if '退回' in decoded_name or '退信' in decoded_name or 'bounced' in decoded_lower or 'undelivered' in decoded_lower:
                # 优先选择包含"退回"的文件夹
                if '退回' in decoded_name and '/' not in decoded_name:
                    print(f"[Mail] 找到退信文件夹: {raw_name} ({decoded_name})")
                    return raw_name

        # 如果有"自定义垃圾邮件/退回"这样的文件夹，返回父文件夹
        for raw_name, decoded_name in folders:
            if '退回' in decoded_name:
                print(f"[Mail] 找到退信文件夹（含子目录）: {raw_name} ({decoded_name})")
                return raw_name

        print("[Mail] 未找到系统邮件文件夹")
        return None

    def fetch_emails(self, folder: str = 'INBOX', days: int = 90, since_date: datetime = None, date_range: tuple = None) -> List[Dict[str, Any]]:
        """
        获取邮件列表

        Args:
            folder: 邮箱文件夹
            days: 同步时间范围（天）
            since_date: 增量同步起始时间（优先于days参数）
            date_range: 自定义日期范围 (start_date, end_date)，格式 'YYYY-MM-DD'

        Returns:
            邮件数据列表
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server")

        emails = []

        try:
            # 尝试选择文件夹（不使用readonly，因为163邮箱不支持）
            status, data = self.client.select(folder)
            if status != 'OK':
                print(f"[Mail] 无法选择文件夹 '{folder}': {status}, {data}")
                return emails

            print(f"[Mail] 成功选择文件夹: {folder}")

            # 构建搜索条件
            from datetime import datetime, timedelta

            search_criteria = None

            if date_range:
                # 自定义日期范围
                start_date, end_date = date_range
                # IMAP日期格式: 01-Jan-2024
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                # SINCE: 包含当天及之后，BEFORE: 不包含当天
                # 所以end_date要加1天才能包含当天
                end_dt_search = end_dt + timedelta(days=1)
                start_str = start_dt.strftime('%d-%b-%Y')
                end_str = end_dt_search.strftime('%d-%b-%Y')
                search_criteria = f'SINCE {start_str} BEFORE {end_str}'
                print(f"[Mail] 自定义日期范围同步: {start_date} 至 {end_date}")
            elif since_date:
                # 增量同步：从指定时间开始
                # 稍微往前推1小时，避免遗漏
                search_date = since_date - timedelta(hours=1)
                date_str = search_date.strftime('%d-%b-%Y')
                search_criteria = f'SINCE {date_str}'
                print(f"[Mail] 增量同步，起始时间: {search_date}")
            else:
                # 全量同步
                search_date = datetime.now() - timedelta(days=days)
                date_str = search_date.strftime('%d-%b-%Y')  # IMAP日期格式: 01-Jan-2024
                search_criteria = f'SINCE {date_str}'

            # 使用搜索条件获取邮件
            status, messages = self.client.search(None, search_criteria)

            if status != 'OK':
                print(f"[Mail] 搜索失败 '{folder}': {status}")
                return emails

            message_ids = messages[0].split()
            print(f"[Mail] 文件夹 '{folder}' 找到 {len(message_ids)} 封邮件")

            for msg_id in message_ids:
                status, msg_data = self.client.fetch(msg_id, '(RFC822)')
                if status != 'OK':
                    continue

                raw_email = msg_data[0][1]
                email_data = self._parse_email(raw_email)
                if email_data:
                    # 标记邮件来源文件夹
                    email_data['folder'] = folder
                    emails.append(email_data)

        except Exception as e:
            print(f"[Mail] Fetch emails error for '{folder}': {e}")
            import traceback
            traceback.print_exc()

        return emails

    def get_uid_list(self, folder: str = 'INBOX', days: int = 90, date_range: tuple = None) -> List[int]:
        """
        获取邮件UID列表（轻量操作，不下载邮件内容）

        Args:
            folder: 邮箱文件夹
            days: 同步时间范围（天）
            date_range: 自定义日期范围 (start_date, end_date)

        Returns:
            UID列表
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server")

        try:
            status, data = self.client.select(folder)
            if status != 'OK':
                print(f"[Mail] 无法选择文件夹 '{folder}': {status}")
                return []

            from datetime import datetime, timedelta

            # 构建搜索条件
            if date_range:
                start_date, end_date = date_range
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                end_dt_search = end_dt + timedelta(days=1)
                start_str = start_dt.strftime('%d-%b-%Y')
                end_str = end_dt_search.strftime('%d-%b-%Y')
                search_criteria = f'SINCE {start_str} BEFORE {end_str}'
            else:
                search_date = datetime.now() - timedelta(days=days)
                date_str = search_date.strftime('%d-%b-%Y')
                search_criteria = f'SINCE {date_str}'

            # 搜索获取序号列表
            status, messages = self.client.search(None, search_criteria)
            if status != 'OK':
                return []

            sequence_nums = messages[0].split()
            if not sequence_nums:
                return []

            # 批量获取UID（使用FETCH命令获取UID）
            # 将序号列表转换为范围以减少请求次数
            uid_list = []
            batch_size = 500  # 每批处理的邮件数

            for i in range(0, len(sequence_nums), batch_size):
                batch = sequence_nums[i:i + batch_size]
                # 构建序号范围，如 "1:100" 或 "1,2,3,4,5"
                seq_range = ','.join([s.decode() if isinstance(s, bytes) else str(s) for s in batch])
                status, uid_data = self.client.fetch(seq_range, '(UID)')
                if status == 'OK':
                    for item in uid_data:
                        # 处理返回数据，可能是 tuple 或 bytes
                        if isinstance(item, tuple):
                            response = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                        elif isinstance(item, bytes):
                            response = item.decode()
                        else:
                            response = str(item)

                        import re
                        uid_match = re.search(r'UID (\d+)', response)
                        if uid_match:
                            uid_list.append(int(uid_match.group(1)))

            print(f"[Mail] 文件夹 '{folder}' 获取到 {len(uid_list)} 个UID")
            return uid_list

        except Exception as e:
            print(f"[Mail] 获取UID列表失败: {e}")
            return []

    def get_uids_after(self, folder: str, last_uid: int) -> List[int]:
        """
        获取指定UID之后的所有新邮件UID（用于增量同步）

        Args:
            folder: 邮箱文件夹
            last_uid: 上次同步的最后UID，获取大于此UID的所有邮件

        Returns:
            UID列表（大于last_uid的）
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server")

        try:
            status, data = self.client.select(folder)
            if status != 'OK':
                print(f"[Mail] 无法选择文件夹 '{folder}': {status}")
                return []

            # 使用UID SEARCH获取大于last_uid的邮件
            # IMAP的UID搜索命令: UID SEARCH UID <min>:
            if last_uid > 0:
                search_criteria = f'UID {last_uid + 1}:*'
                status, messages = self.client.uid('search', None, search_criteria)
            else:
                # 如果last_uid为0，获取所有邮件
                status, messages = self.client.uid('search', None, 'ALL')

            if status != 'OK':
                return []

            uid_list = []
            if messages[0]:
                uid_list = [int(uid) for uid in messages[0].split()]

            print(f"[Mail] 文件夹 '{folder}' 获取到 {len(uid_list)} 个新UID (last_uid={last_uid})")
            return uid_list

        except Exception as e:
            print(f"[Mail] 获取新UID失败: {e}")
            return []

    def fetch_emails_by_uid(self, folder: str, uids: List[int]) -> List[Dict[str, Any]]:
        """
        根据UID列表获取邮件

        Args:
            folder: 邮箱文件夹
            uids: UID列表

        Returns:
            邮件数据列表
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server")

        if not uids:
            return []

        emails = []

        try:
            status, data = self.client.select(folder)
            if status != 'OK':
                print(f"[Mail] 无法选择文件夹 '{folder}'")
                return emails

            # 批量获取邮件（每批50封）
            batch_size = 50
            for i in range(0, len(uids), batch_size):
                batch_uids = uids[i:i + batch_size]
                # 构建UID范围
                uid_range = ','.join(str(uid) for uid in batch_uids)

                # 使用UID FETCH命令
                status, msg_data = self.client.uid('fetch', uid_range, '(RFC822)')
                if status != 'OK':
                    continue

                # 解析返回的邮件数据
                j = 0
                while j < len(msg_data):
                    item = msg_data[j]
                    if isinstance(item, tuple) and len(item) >= 2:
                        raw_email = item[1]
                        # 解析UID
                        response = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                        import re
                        uid_match = re.search(r'UID (\d+)', response)
                        uid = int(uid_match.group(1)) if uid_match else None

                        email_data = self._parse_email(raw_email)
                        if email_data:
                            email_data['folder'] = folder
                            email_data['imap_uid'] = uid
                            emails.append(email_data)
                    j += 1

            print(f"[Mail] 根据UID获取到 {len(emails)} 封邮件")
            return emails

        except Exception as e:
            print(f"[Mail] 根据UID获取邮件失败: {e}")
            import traceback
            traceback.print_exc()
            return emails

    def _parse_email(self, raw_email: bytes) -> Optional[Dict[str, Any]]:
        """解析原始邮件"""
        try:
            msg = email.message_from_bytes(raw_email)

            # 解码主题
            subject = self._decode_header(msg.get('Subject', ''))

            # 解析发件人
            from_header = self._decode_header(msg.get('From', ''))
            from_name, from_email = parseaddr(from_header)

            # 解析收件人
            to_addr = self._decode_header(msg.get('To', ''))

            # 解析抄送
            cc_addr = self._decode_header(msg.get('Cc', '') or msg.get('CC', ''))

            # 解析日期
            date_str = msg.get('Date', '')
            try:
                from email.utils import parsedate_to_datetime
                received_at = parsedate_to_datetime(date_str).isoformat()
            except:
                received_at = datetime.now().isoformat()

            # 提取正文
            content = ''
            html_content = ''

            def decode_payload(payload, part):
                """智能解码邮件正文"""
                if not payload:
                    return ''
                charset = part.get_content_charset()
                # 韩文邮件常用编码列表
                encodings = ['euc-kr', 'ks_c_5601-1987', 'iso-2022-kr', 'utf-8', 'gbk', 'gb2312', 'iso-8859-1']

                # 如果检测到charset，优先尝试
                if charset:
                    try:
                        return payload.decode(charset, errors='replace')
                    except (LookupError, UnicodeDecodeError):
                        pass

                # 尝试各种编码
                for enc in encodings:
                    try:
                        decoded = payload.decode(enc, errors='strict')
                        # 检查是否有乱码特征（太多替换字符）
                        if decoded.count('\ufffd') / len(decoded) < 0.1:
                            return decoded
                    except (LookupError, UnicodeDecodeError):
                        continue

                # 最后用utf-8强制解码
                return payload.decode('utf-8', errors='replace')

            if msg.is_multipart():
                # 先收集所有内嵌图片
                embedded_images = {}  # cid -> base64 data
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_id = part.get('Content-ID', '')
                    if content_id and content_type.startswith('image/'):
                        payload = part.get_payload(decode=True)
                        if payload:
                            import base64
                            b64_data = base64.b64encode(payload).decode('ascii')
                            # 移除cid两端的尖括号
                            cid = content_id.strip('<>')
                            embedded_images[cid] = f"data:{content_type};base64,{b64_data}"

                # 再解析正文
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == 'text/plain':
                        payload = part.get_payload(decode=True)
                        if payload:
                            content += decode_payload(payload, part)
                    elif content_type == 'text/html':
                        payload = part.get_payload(decode=True)
                        if payload:
                            html_content += decode_payload(payload, part)

                # 替换HTML中的cid引用为base64数据
                import re
                for cid, data_url in embedded_images.items():
                    html_content = re.sub(
                        rf'src=["\']cid:{re.escape(cid)}["\']',
                        f'src="{data_url}"',
                        html_content,
                        flags=re.IGNORECASE
                    )
                    # 也处理不带cid:前缀的情况
                    html_content = re.sub(
                        rf'src=["\']cid:{re.escape(cid)}@[^"\']+["\']',
                        f'src="{data_url}"',
                        html_content,
                        flags=re.IGNORECASE
                    )
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    content = decode_payload(payload, msg)

            return {
                'subject': subject,
                'from_addr': from_email or from_header,
                'from_name': from_name or '',
                'to_addr': to_addr,
                'cc_addr': cc_addr,
                'content': content,
                'html_content': html_content,
                'received_at': received_at,
                'sent_at': received_at,  # 收件箱邮件也用sent_at存储发件时间
                'message_id': msg.get('Message-ID', ''),
                'is_sent': 0
            }
        except Exception as e:
            print(f"Parse email error: {e}")
            return None

    def _decode_header(self, header: str) -> str:
        """解码邮件头"""
        if not header:
            return ''
        decoded_parts = decode_header(header)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                # 尝试多种编码方式
                decoded = None
                # 优先使用检测到的charset
                if charset:
                    try:
                        decoded = part.decode(charset, errors='replace')
                    except (LookupError, UnicodeDecodeError):
                        pass
                # 如果charset无效或未指定，尝试常见编码
                if decoded is None:
                    for enc in ['utf-8', 'euc-kr', 'iso-8859-1', 'gbk', 'gb2312']:
                        try:
                            decoded = part.decode(enc, errors='replace')
                            break
                        except (LookupError, UnicodeDecodeError):
                            continue
                # 最后使用utf-8强制解码
                if decoded is None:
                    decoded = part.decode('utf-8', errors='replace')
                result.append(decoded)
            else:
                result.append(part)
        return ''.join(result)


class SMTPClient:
    """SMTP 邮件发送客户端"""

    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化 SMTP 客户端

        Args:
            config: 邮件配置（可选，未提供则从数据库读取）
        """
        self.config = config or get_mail_config()
        self.client = None

    def connect(self) -> bool:
        """建立 SMTP 连接"""
        if not self.config:
            raise ValueError("Mail config not found")

        try:
            server = self.config.get('smtp_server')
            port = self.config.get('smtp_port', 587)

            # 端口465使用SSL直连，其他端口使用STARTTLS
            if port == 465:
                self.client = smtplib.SMTP_SSL(server, port)
            else:
                self.client = smtplib.SMTP(server, port)
                self.client.ehlo()

                if self.config.get('use_tls', 1):
                    self.client.starttls()

            self.client.login(self.config['username'], self.config['password'])
            return True
        except Exception as e:
            raise ConnectionError(f"SMTP connection failed: {str(e)}")

    def disconnect(self):
        """断开 SMTP 连接"""
        if self.client:
            try:
                self.client.quit()
            except:
                pass
            self.client = None

    def send_email(self, to: str, subject: str, body: str,
                   html_body: str = None, cc: str = None) -> Dict[str, Any]:
        """
        发送邮件

        Args:
            to: 收件人
            subject: 主题
            body: 正文（纯文本）
            html_body: HTML 正文（可选）
            cc: 抄送（可选）

        Returns:
            {"success": bool, "message_id": str, "error": str}
        """
        if not self.client:
            raise ConnectionError("Not connected to SMTP server")

        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.config['username']
            msg['To'] = to
            msg['Subject'] = subject

            if cc:
                msg['Cc'] = cc

            # 添加纯文本正文
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # 添加 HTML 正文
            if html_body:
                msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            # 发送
            recipients = [to]
            if cc:
                recipients.append(cc)
            self.client.sendmail(self.config['username'], recipients, msg.as_string())

            return {
                "success": True,
                "message_id": msg.get('Message-ID', ''),
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "message_id": None,
                "error": str(e)
            }


def sync_inbox(background_tasks=None) -> Dict[str, Any]:
    """
    同步邮件（收件箱和发件箱）

    Args:
        background_tasks: FastAPI BackgroundTasks（暂未使用，保留扩展性）

    Returns:
        {"status": "started"|"error", "message": str}
    """
    lock_id = str(uuid.uuid4())

    # 恢复孤立的同步记录
    recover_orphaned_syncs()

    # 尝试获取锁
    if not acquire_sync_lock(lock_id):
        return {"status": "already_running", "message": "Sync already in progress"}

    try:
        config = get_mail_config()
        if not config or not config.get('imap_server'):
            update_sync_progress(0, 1, "邮件配置未找到")
            return {"status": "error", "message": "Mail config not found"}

        # 获取当前账户ID用于用户隔离
        current_account_id = config.get('id')
        sync_days = get_sync_days()
        date_range = get_sync_date_range()

        # 获取分批处理配置（默认：每批100封，暂停0.1秒）
        batch_size = config.get('sync_batch_size') or 100
        pause_seconds = config.get('sync_pause_seconds') or 0.1
        print(f"[Mail] 分批配置: 每批 {batch_size} 封, 暂停 {pause_seconds} 秒")

        # 确定同步范围描述和日期
        if date_range[0] and date_range[1]:
            sync_desc = f"{date_range[0]} 至 {date_range[1]}"
            sync_start = date_range[0]
            sync_end = date_range[1]
        else:
            from datetime import datetime, timedelta
            sync_start = (datetime.now() - timedelta(days=sync_days)).strftime('%Y-%m-%d')
            sync_end = datetime.now().strftime('%Y-%m-%d')
            sync_desc = f"最近{sync_days}天"

        # 初始化进度（包含日期范围）
        update_sync_progress(
            0, 100, f"连接邮件服务器...",
            sync_start_date=sync_start,
            sync_end_date=sync_end,
            total_emails=0,
            synced_emails=0
        )

        imap_client = IMAPClient(config)
        imap_client.connect()

        # 自动检测发件箱和垃圾邮件文件夹
        update_sync_progress(5, 100, "检测邮箱文件夹...")

        # 一次性获取所有文件夹，避免多次调用
        all_folders = imap_client.list_folders()
        print(f"[Mail] 服务器共有 {len(all_folders)} 个文件夹:")
        for raw_name, decoded_name in all_folders:
            print(f"  - {raw_name} ({decoded_name})")

        # 在获取的文件夹中查找发件箱、垃圾邮件、草稿箱
        sent_folder = None
        spam_folder = None
        draft_folder = None

        # 常见的发件箱名称
        sent_names = ['Sent', 'Sent Items', 'Sent Messages', '已发送', '发件箱',
                      'INBOX.Sent', 'INBOX/Sent', 'Sent Mail', '&XfJT0ZAB-', '&g0l6P3ux-']  # UTF-7 编码
        # 常见的垃圾邮件名称
        spam_names = ['Spam', 'Junk', 'Junk E-mail', '垃圾邮件', '垃圾箱',
                      'Bulk Mail', '垃圾信', '&V4NXPpCuTvY-', '&g0l6P3ux-']
        # 常见的草稿箱名称
        draft_names = ['Drafts', 'Draft', '草稿', '草稿箱', '&g0l6P3ux-']

        for raw_name, decoded_name in all_folders:
            decoded_lower = decoded_name.lower()
            # 检测发件箱
            if not sent_folder:
                if decoded_name in sent_names or raw_name in sent_names:
                    sent_folder = raw_name
                    print(f"[Mail] 找到发件箱: {raw_name} ({decoded_name})")
                elif 'sent' in decoded_lower or '发件' in decoded_name or '发送' in decoded_name:
                    sent_folder = raw_name
                    print(f"[Mail] 模糊匹配找到发件箱: {raw_name} ({decoded_name})")

            # 检测垃圾邮件
            if not spam_folder:
                if decoded_name in spam_names or raw_name in spam_names:
                    spam_folder = raw_name
                    print(f"[Mail] 找到垃圾邮件文件夹: {raw_name} ({decoded_name})")
                elif 'spam' in decoded_lower or 'junk' in decoded_lower or '垃圾' in decoded_name:
                    spam_folder = raw_name
                    print(f"[Mail] 模糊匹配找到垃圾邮件: {raw_name} ({decoded_name})")

            # 检测草稿箱
            if not draft_folder:
                if decoded_name in draft_names or raw_name in draft_names:
                    draft_folder = raw_name
                    print(f"[Mail] 找到草稿箱: {raw_name} ({decoded_name})")
                elif 'draft' in decoded_lower or '草稿' in decoded_name:
                    draft_folder = raw_name
                    print(f"[Mail] 模糊匹配找到草稿箱: {raw_name} ({decoded_name})")

        if not sent_folder:
            print("[Mail] ⚠️ 警告：未检测到发件箱，请检查邮箱文件夹命名")
        if not spam_folder:
            print("[Mail] ⚠️ 警告：未检测到垃圾邮件文件夹，请检查邮箱文件夹命名")
        if not draft_folder:
            print("[Mail] ⚠️ 警告：未检测到草稿箱，请检查邮箱文件夹命名")

        # 只获取垃圾邮件文件夹ID（已发送和草稿箱通过is_sent和is_draft字段区分，不需要folder_id）
        from Sills.db_mail import get_or_create_spam_folder
        spam_folder_id = get_or_create_spam_folder(current_account_id) if spam_folder else None

        # 处理其他文件夹（已在上面的 all_folders 中获取）
        other_folders = []
        for raw_name, decoded_name in all_folders:
            # 跳过已处理的文件夹
            if raw_name == 'INBOX' or raw_name == sent_folder or raw_name == spam_folder or raw_name == draft_folder:
                continue
            # 其他文件夹都同步到收件箱
            other_folders.append(raw_name)
            print(f"[Mail] 其他文件夹同步到收件箱: {decoded_name}")

        # 同步收件箱、发件箱、垃圾邮件、草稿箱、其他文件夹
        # (文件夹名, is_sent, is_draft, 显示标签, 本地folder_id)
        # 已发送通过is_sent=1区分，草稿箱通过is_draft=1区分，都不需要folder_id
        folders_to_sync = [('INBOX', 0, 0, '收件箱', None)]
        if sent_folder:
            folders_to_sync.append((sent_folder, 1, 0, '发件箱', None))
        if draft_folder:
            folders_to_sync.append((draft_folder, 0, 1, '草稿箱', None))
        if spam_folder:
            folders_to_sync.append((spam_folder, 0, 0, '垃圾邮件', spam_folder_id))
        # 其他文件夹都归入收件箱
        for folder_name in other_folders:
            folders_to_sync.append((folder_name, 0, 0, '收件箱', None))

        print(f"[Mail] 共需同步 {len(folders_to_sync)} 个文件夹: {[f[2] for f in folders_to_sync]}")

        total_saved = 0
        total_updated = 0
        total_processed = 0

        # === 流式处理：分批获取并立即写入数据库，避免内存溢出 ===
        from Sills.db_mail import get_local_uids, get_db_connection
        import gc
        import time

        # 第一遍：统计所有文件夹的新邮件总数（不下载内容，不存储UID列表）
        grand_total_new = 0

        for folder_name, is_sent, is_draft, folder_label, local_folder_id in folders_to_sync:
            try:
                update_sync_progress(5, 100, f"扫描{folder_label}UID...")

                # Step 1: 获取服务器UID列表（轻量操作）
                server_uids = imap_client.get_uid_list(
                    folder=folder_name,
                    days=sync_days,
                    date_range=date_range if date_range[0] and date_range[1] else None
                )

                if not server_uids:
                    print(f"[Mail] {folder_label}: 无邮件")
                    continue

                # Step 2: 获取本地已有UID（仅此文件夹）
                local_uids = get_local_uids(folder_name, current_account_id)

                # Step 3: 计算需要获取的UID数量（不存储列表）
                new_count = len(set(server_uids) - local_uids)
                print(f"[Mail] {folder_label}: 服务器 {len(server_uids)} 封, 本地 {len(local_uids)} 封, 新增 {new_count} 封")

                if new_count > 0:
                    grand_total_new += new_count

                # 释放内存
                del server_uids
                del local_uids
                gc.collect()

            except Exception as e:
                print(f"[Mail] 扫描 {folder_name} 失败: {e}")
                import traceback
                traceback.print_exc()

        print(f"[Mail] 总计 {grand_total_new} 封新邮件待同步")
        update_sync_progress(10, 100, f"共发现 {grand_total_new} 封新邮件", total_emails=grand_total_new)

        # 第二遍：流式处理 - 逐文件夹处理，避免内存累积
        fetch_batch_size = 50  # IMAP 每批获取数量

        for folder_name, is_sent, is_draft, folder_label, local_folder_id in folders_to_sync:
            try:
                # 重新获取此文件夹的UID（流式处理，不保留）
                server_uids = imap_client.get_uid_list(
                    folder=folder_name,
                    days=sync_days,
                    date_range=date_range if date_range[0] and date_range[1] else None
                )
                if not server_uids:
                    continue

                local_uids = get_local_uids(folder_name, current_account_id)
                new_uids = [uid for uid in server_uids if uid not in local_uids]

                # 释放内存
                del server_uids
                del local_uids
                gc.collect()

                if not new_uids:
                    continue

                # 分批获取邮件
                for batch_start in range(0, len(new_uids), fetch_batch_size):
                    batch_uids = new_uids[batch_start:batch_start + fetch_batch_size]

                    # 检查取消
                    if is_sync_cancelled():
                        update_sync_progress(0, 100, "同步已取消")
                        return {"status": "cancelled", "message": "同步已取消"}

                    update_sync_progress(
                        int(10 + (total_processed / grand_total_new) * 85) if grand_total_new > 0 else 50,
                        100,
                        f"获取{folder_label}邮件 {total_processed + 1}-{min(total_processed + fetch_batch_size, grand_total_new)}/{grand_total_new}",
                        synced_emails=total_processed
                    )

                    # 获取一批邮件
                    emails = imap_client.fetch_emails_by_uid(folder_name, batch_uids)

                    # 为每封邮件添加元数据
                    for email_data in emails:
                        email_data['is_sent'] = is_sent
                        email_data['is_draft'] = is_draft
                        email_data['folder_label'] = folder_label
                        email_data['imap_folder'] = folder_name
                        email_data['account_id'] = current_account_id
                        if local_folder_id:
                            email_data['folder_id'] = local_folder_id

                    # 批量保存邮件（一次事务，更高效）
                    from Sills.db_mail import batch_save_emails
                    saved_in_batch = batch_save_emails(emails)
                    total_saved += saved_in_batch
                    total_processed += len(emails)

                    # 更新进度
                    percent = int(10 + (total_processed / grand_total_new) * 85) if grand_total_new > 0 else 50
                    update_sync_progress(
                        percent, 100,
                        f"同步{folder_label} {total_processed}/{grand_total_new}",
                        synced_emails=total_processed
                    )

                    # 释放内存
                    emails.clear()
                    del emails
                    del batch_uids
                    gc.collect()

                    # 批次间暂停，让系统喘息
                    time.sleep(pause_seconds)

                # 文件夹处理完毕，释放UID列表
                del new_uids
                gc.collect()

            except Exception as e:
                print(f"[Mail] 处理文件夹 {folder_name} 失败: {e}")
                import traceback
                traceback.print_exc()

        update_sync_progress(95, 100, "断开连接...")
        imap_client.disconnect()

        update_sync_progress(100, 100, f"完成！新增 {total_saved} 封，更新 {total_updated} 封")

        return {
            "status": "completed",
            "message": f"Synced {total_saved} new emails, updated {total_updated} existing"
        }

    except Exception as e:
        update_sync_progress(0, 100, f"错误: {str(e)}")
        return {"status": "error", "message": str(e)}

    finally:
        release_sync_lock()


def sync_inbox_async() -> Dict[str, Any]:
    """
    异步同步收件箱（启动后台线程）

    Returns:
        {"status": "started"}
    """
    thread = threading.Thread(target=sync_inbox)
    thread.daemon = True
    thread.start()
    return {"status": "started"}


def sync_new_emails(background_tasks=None) -> Dict[str, Any]:
    """
    增量同步：对比服务器UID和本地UID，只获取本地没有的邮件

    Returns:
        {"status": "completed", "new_count": int}
    """
    from Sills.db_mail import get_local_uids, get_sync_deleted_setting, get_synced_uids, batch_record_synced_uids
    from datetime import datetime

    # 重置取消标志
    reset_cancel_flag()

    lock_id = str(uuid.uuid4())

    # 恢复孤立的同步记录
    recover_orphaned_syncs()

    # 尝试获取锁
    if not acquire_sync_lock(lock_id):
        return {"status": "already_running", "message": "Sync already in progress"}

    try:
        config = get_mail_config()
        if not config or not config.get('imap_server'):
            update_sync_progress(0, 1, "邮件配置未找到")
            return {"status": "error", "message": "Mail config not found"}

        current_account_id = config.get('id')
        update_sync_progress(0, 100, "连接邮件服务器...")

        # 检查取消
        if is_sync_cancelled():
            update_sync_progress(0, 100, "同步已取消")
            return {"status": "cancelled", "message": "同步已取消"}

        imap_client = IMAPClient(config)
        imap_client.connect()

        # 自动检测发件箱、垃圾邮件、草稿箱
        update_sync_progress(10, 100, "检测邮箱文件夹...")
        sent_folder = imap_client.find_sent_folder()
        spam_folder = imap_client.find_spam_folder()
        draft_folder = imap_client.find_draft_folder()

        # 只获取垃圾邮件文件夹ID（已发送和草稿箱通过is_sent和is_draft字段区分，不需要folder_id）
        from Sills.db_mail import get_or_create_spam_folder
        spam_folder_id = get_or_create_spam_folder(current_account_id) if spam_folder else None

        # 获取所有文件夹，同步除垃圾邮件外的其他文件夹到收件箱
        all_folders = imap_client.list_folders()
        other_folders = []
        for raw_name, decoded_name in all_folders:
            # 跳过已处理的文件夹
            if raw_name == 'INBOX' or raw_name == sent_folder or raw_name == spam_folder or raw_name == draft_folder:
                continue
            # 其他文件夹都同步到收件箱
            other_folders.append(raw_name)

        # 同步收件箱、发件箱、垃圾邮件、草稿箱、其他文件夹
        # (文件夹名, is_sent, is_draft, 显示标签, 本地folder_id)
        # 已发送通过is_sent=1区分，草稿箱通过is_draft=1区分，都不需要folder_id
        folders_to_sync = [('INBOX', 0, 0, '收件箱', None)]
        if sent_folder:
            folders_to_sync.append((sent_folder, 1, 0, '发件箱', None))
        if draft_folder:
            folders_to_sync.append((draft_folder, 0, 1, '草稿箱', None))
        if spam_folder:
            folders_to_sync.append((spam_folder, 0, 0, '垃圾邮件', spam_folder_id))
        # 其他文件夹都归入收件箱
        for folder_name in other_folders:
            folders_to_sync.append((folder_name, 0, 0, '收件箱', None))

        total_saved = 0

        # 获取分批处理配置
        batch_size = config.get('sync_batch_size') or 100
        pause_seconds = config.get('sync_pause_seconds') or 0.1

        # 收集所有需要同步的UID
        update_sync_progress(20, 100, "扫描服务器UID...")
        all_uids_to_fetch = []  # [(folder_name, is_sent, is_draft, folder_label, local_folder_id, uid), ...]

        for folder_name, is_sent, is_draft, folder_label, local_folder_id in folders_to_sync:
            # 检查取消
            if is_sync_cancelled():
                update_sync_progress(0, 100, "同步已取消")
                imap_client.disconnect()
                return {"status": "cancelled", "message": "同步已取消", "new_count": total_saved}

            try:
                print(f"[Mail] 检查文件夹: {folder_name}")
                # 获取服务器上的UID列表（轻量操作）
                server_uids = imap_client.get_uid_list(folder=folder_name, days=365)
                if not server_uids:
                    print(f"[Mail] {folder_label}: 无邮件")
                    continue

                # 获取本地已存储的UID
                local_uids = get_local_uids(folder_name, current_account_id)

                # 计算差集：需要同步的新UID
                new_uids = set(server_uids) - local_uids

                # 如果"同步已删除邮件"开关关闭，排除已同步过但已删除的邮件
                sync_deleted_enabled = get_sync_deleted_setting()
                if not sync_deleted_enabled:
                    # 获取已同步过的UID记录
                    synced_uids = get_synced_uids(current_account_id, folder_name)
                    # 只保留从未同步过的UID
                    new_uids = new_uids - synced_uids
                    print(f"[Mail] {folder_label}: 已同步过{len(synced_uids)}封, 开关关闭，跳过已删除邮件")

                print(f"[Mail] {folder_label}: 服务器{len(server_uids)}封, 本地{len(local_uids)}封, 新增{len(new_uids)}封")

                for uid in new_uids:
                    all_uids_to_fetch.append((folder_name, is_sent, is_draft, folder_label, local_folder_id, uid))

            except Exception as e:
                print(f"[Mail] 扫描 {folder_name} 失败: {e}")

        grand_total_emails = len(all_uids_to_fetch)
        print(f"[Mail] 总计 {grand_total_emails} 封新邮件待同步")

        if grand_total_emails == 0:
            update_sync_progress(100, 100, "完成！无新邮件")
            imap_client.disconnect()
            return {"status": "completed", "new_count": 0, "message": "无新邮件"}

        # 设置同步日期范围
        from datetime import timedelta
        sync_start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        sync_end = datetime.now().strftime('%Y-%m-%d')

        # 更新总邮件数
        update_sync_progress(30, 100, f"共发现 {grand_total_emails} 封新邮件",
                           sync_start_date=sync_start, sync_end_date=sync_end,
                           total_emails=grand_total_emails, synced_emails=0)

        # 按文件夹分组，批量获取邮件
        import time
        from collections import defaultdict
        uids_by_folder = defaultdict(list)
        for folder_name, is_sent, is_draft, folder_label, local_folder_id, uid in all_uids_to_fetch:
            uids_by_folder[(folder_name, is_sent, is_draft, folder_label, local_folder_id)].append(uid)

        processed_count = 0
        for (folder_name, is_sent, is_draft, folder_label, local_folder_id), uids in uids_by_folder.items():
            # 检查取消
            if is_sync_cancelled():
                update_sync_progress(0, 100, "同步已取消")
                imap_client.disconnect()
                return {"status": "cancelled", "message": "同步已取消", "new_count": total_saved}

            print(f"[Mail] 同步 {folder_label} 的 {len(uids)} 封邮件...")

            # 批量获取邮件
            batch_uids = []
            for uid in uids:
                batch_uids.append(uid)

            # 使用 fetch_emails_by_uid 批量获取
            emails = imap_client.fetch_emails_by_uid(folder_name, batch_uids)

            # 收集已同步的UID用于记录
            synced_uid_pairs = []

            for email_data in emails:
                # 检查取消
                if is_sync_cancelled():
                    update_sync_progress(0, 100, "同步已取消")
                    imap_client.disconnect()
                    return {"status": "cancelled", "message": "同步已取消", "new_count": total_saved}

                email_data['is_sent'] = is_sent
                email_data['is_draft'] = is_draft
                email_data['folder_label'] = folder_label
                email_data['imap_folder'] = folder_name
                email_data['account_id'] = current_account_id
                if local_folder_id:
                    email_data['folder_id'] = local_folder_id

                # 保存邮件
                save_email(email_data)
                total_saved += 1
                processed_count += 1

                # 收集UID用于记录
                if email_data.get('imap_uid'):
                    synced_uid_pairs.append((email_data['imap_uid'], folder_name))

                # 更新进度
                percent = int(30 + (processed_count / grand_total_emails) * 65)
                update_sync_progress(
                    percent, 100,
                    f"{folder_label} {processed_count}/{grand_total_emails}",
                    synced_emails=processed_count
                )

            # 批量记录已同步的UID
            if synced_uid_pairs:
                batch_record_synced_uids(current_account_id, synced_uid_pairs)

            # 分批暂停
            if len(uids) >= batch_size:
                print(f"[Mail] 批次完成，暂停 {pause_seconds} 秒...")
                time.sleep(pause_seconds)

        update_sync_progress(95, 100, "断开连接...")
        imap_client.disconnect()

        update_sync_progress(100, 100, f"完成！新增 {total_saved} 封邮件")

        return {
            "status": "completed",
            "new_count": total_saved,
            "message": f"获取了 {total_saved} 封新邮件"
        }

    except Exception as e:
        update_sync_progress(0, 100, f"错误: {str(e)}")
        return {"status": "error", "message": str(e)}

    finally:
        release_sync_lock()


def sync_new_emails_async() -> Dict[str, Any]:
    """
    异步增量同步（启动后台线程）
    """
    thread = threading.Thread(target=sync_new_emails)
    thread.daemon = True
    thread.start()
    return {"status": "started"}


def refresh_emails(background_tasks=None) -> Dict[str, Any]:
    """
    刷新邮件：只同步上次同步之后的新邮件

    Returns:
        {"status": "completed", "new_count": int, "message": "..."}
    """
    from Sills.db_mail import get_folder_last_uid, update_folder_last_uid, get_local_uids, batch_record_synced_uids
    from datetime import datetime

    # 重置取消标志
    reset_cancel_flag()

    lock_id = str(uuid.uuid4())

    # 尝试获取锁
    if not acquire_sync_lock(lock_id):
        return {"status": "already_running", "message": "同步任务正在进行中"}

    try:
        config = get_mail_config()
        if not config or not config.get('imap_server'):
            update_sync_progress(0, 1, "邮件配置未找到")
            return {"status": "error", "message": "邮件配置未找到"}

        current_account_id = config.get('id')
        update_sync_progress(0, 100, "连接邮件服务器...")

        imap_client = IMAPClient(config)
        imap_client.connect()

        # 检测文件夹
        update_sync_progress(10, 100, "检测邮箱文件夹...")
        sent_folder = imap_client.find_sent_folder()
        spam_folder = imap_client.find_spam_folder()
        draft_folder = imap_client.find_draft_folder()

        # 只获取垃圾邮件文件夹ID（已发送和草稿箱不需要folder_id，通过is_sent和is_draft字段区分）
        from Sills.db_mail import get_or_create_spam_folder
        spam_folder_id = get_or_create_spam_folder(current_account_id) if spam_folder else None

        # 构建要同步的文件夹列表
        # (文件夹名, is_sent, is_draft, 显示标签, 本地folder_id)
        # 已发送通过is_sent=1区分，草稿箱通过is_draft=1区分，都不需要folder_id
        folders_to_sync = [('INBOX', 0, 0, '收件箱', None)]
        if sent_folder:
            folders_to_sync.append((sent_folder, 1, 0, '发件箱', None))
        if draft_folder:
            folders_to_sync.append((draft_folder, 0, 1, '草稿箱', None))
        if spam_folder:
            folders_to_sync.append((spam_folder, 0, 0, '垃圾邮件', spam_folder_id))

        total_saved = 0

        # 获取每个文件夹的最后同步UID
        last_uids = {}
        for folder_name, is_sent, is_draft, folder_label, local_folder_id in folders_to_sync:
            last_uid = get_folder_last_uid(current_account_id, folder_name)
            last_uids[folder_name] = last_uid
            print(f"[Mail] {folder_label} last_uid = {last_uid}")

        # 获取新邮件UID
        update_sync_progress(20, 100, "扫描新邮件...")
        all_uids_to_fetch = []  # [(folder_name, is_sent, is_draft, folder_label, local_folder_id, uid), ...]

        for folder_name, is_sent, is_draft, folder_label, local_folder_id in folders_to_sync:
            if is_sync_cancelled():
                update_sync_progress(0, 100, "同步已取消")
                imap_client.disconnect()
                return {"status": "cancelled", "message": "同步已取消"}

            try:
                last_uid = last_uids.get(folder_name, 0)
                new_uids = imap_client.get_uids_after(folder_name, last_uid)

                # 过滤掉本地已存在的UID（防止重复）
                local_uids = get_local_uids(folder_name, current_account_id)
                new_uids = [uid for uid in new_uids if uid not in local_uids]

                print(f"[Mail] {folder_label}: 发现 {len(new_uids)} 封新邮件")

                for uid in new_uids:
                    all_uids_to_fetch.append((folder_name, is_sent, is_draft, folder_label, local_folder_id, uid))

            except Exception as e:
                print(f"[Mail] 扫描 {folder_name} 失败: {e}")

        grand_total = len(all_uids_to_fetch)

        if grand_total == 0:
            update_sync_progress(100, 100, "完成！没有新邮件")
            imap_client.disconnect()
            release_sync_lock()
            return {"status": "completed", "new_count": 0, "message": "没有新邮件"}

        update_sync_progress(30, 100, f"发现 {grand_total} 封新邮件", total_emails=grand_total)

        # 按文件夹分组获取邮件
        import time
        from collections import defaultdict
        uids_by_folder = defaultdict(list)
        for folder_name, is_sent, is_draft, folder_label, local_folder_id, uid in all_uids_to_fetch:
            uids_by_folder[(folder_name, is_sent, is_draft, folder_label, local_folder_id)].append(uid)

        processed_count = 0
        folder_max_uids = {}  # 记录每个文件夹的最大UID

        for (folder_name, is_sent, is_draft, folder_label, local_folder_id), uids in uids_by_folder.items():
            if is_sync_cancelled():
                update_sync_progress(0, 100, "同步已取消")
                imap_client.disconnect()
                return {"status": "cancelled", "message": "同步已取消"}

            print(f"[Mail] 同步 {folder_label} 的 {len(uids)} 封邮件, is_sent={is_sent}, is_draft={is_draft}")

            # 批量获取邮件
            batch_size = 50
            for i in range(0, len(uids), batch_size):
                # 检查取消标志
                if is_sync_cancelled():
                    update_sync_progress(0, 100, "同步已取消")
                    imap_client.disconnect()
                    return {"status": "cancelled", "message": "同步已取消"}

                batch_uids = uids[i:i + batch_size]
                emails = imap_client.fetch_emails_by_uid(folder_name, batch_uids)

                for email_data in emails:
                    email_data['is_sent'] = is_sent
                    email_data['is_draft'] = is_draft
                    email_data['folder_label'] = folder_label
                    email_data['imap_folder'] = folder_name
                    email_data['account_id'] = current_account_id
                    if local_folder_id:
                        email_data['folder_id'] = local_folder_id

                    # 调试日志
                    if total_saved < 3:
                        print(f"[DEBUG] Saving email: folder={folder_name}, is_sent={is_sent}, is_draft={is_draft}, label={folder_label}, subject={email_data.get('subject', 'N/A')[:30]}")

                    save_email(email_data)
                    total_saved += 1
                    processed_count += 1

                    # 记录最大UID
                    uid = email_data.get('imap_uid')
                    if uid:
                        if folder_name not in folder_max_uids or uid > folder_max_uids[folder_name]:
                            folder_max_uids[folder_name] = uid

                # 更新进度
                percent = int(30 + (processed_count / grand_total) * 65)
                update_sync_progress(percent, 100, f"同步中 {processed_count}/{grand_total}", synced_emails=processed_count)

                time.sleep(0.1)  # 短暂暂停

            # 更新文件夹的最后同步UID
            if folder_name in folder_max_uids:
                update_folder_last_uid(current_account_id, folder_name, folder_max_uids[folder_name])
                print(f"[Mail] 更新 {folder_label} last_uid = {folder_max_uids[folder_name]}")

        imap_client.disconnect()
        update_sync_progress(100, 100, f"完成！新增 {total_saved} 封邮件")

        return {
            "status": "completed",
            "new_count": total_saved,
            "message": f"新增 {total_saved} 封邮件" if total_saved > 0 else "没有新邮件"
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        update_sync_progress(0, 100, f"错误: {str(e)}")
        return {"status": "error", "message": str(e)}

    finally:
        release_sync_lock()


def refresh_emails_async() -> Dict[str, Any]:
    """
    异步刷新邮件（启动后台线程）
    """
    thread = threading.Thread(target=refresh_emails)
    thread.daemon = True
    thread.start()
    return {"status": "started"}


def send_email_now(to: str, subject: str, body: str,
                   html_body: str = None, cc: str = None) -> Dict[str, Any]:
    """
    立即发送邮件

    Args:
        to: 收件人
        subject: 主题
        body: 正文
        html_body: HTML 正文（可选）
        cc: 抄送（可选）

    Returns:
        发送结果
    """
    smtp_client = SMTPClient()

    try:
        smtp_client.connect()
        result = smtp_client.send_email(to, subject, body, html_body, cc)
        smtp_client.disconnect()

        if result['success']:
            # 保存到数据库（检查是否已存在）
            message_id = result.get('message_id')
            from Sills.db_mail import get_db_connection

            # 检查邮件是否已存在
            existing = None
            if message_id:
                with get_db_connection() as conn:
                    existing = conn.execute(
                        "SELECT id FROM uni_mail WHERE message_id = ?",
                        (message_id,)
                    ).fetchone()

            if not existing:
                save_email({
                    'subject': subject,
                    'from_addr': smtp_client.config.get('username', ''),
                    'to_addr': to,
                    'cc_addr': cc,
                    'content': body,
                    'html_content': html_body,
                    'sent_at': datetime.now().isoformat(),
                    'is_sent': 1,
                    'message_id': message_id,
                    'sync_status': 'completed',
                    'account_id': smtp_client.config.get('id')  # 关联当前账户ID
                })

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        smtp_client.disconnect()


def send_email_with_attachments(to: str, subject: str, body: str,
                                  html_body: str = None, cc: str = None,
                                  attachments: list = None) -> Dict[str, Any]:
    """
    发送带附件的邮件

    Args:
        to: 收件人
        subject: 主题
        body: 正文
        html_body: HTML 正文（可选）
        cc: 抄送（可选）
        attachments: 附件列表 [{'path': '文件路径', 'filename': '文件名', 'content_type': 'MIME类型'}]

    Returns:
        发送结果
    """
    from email.mime.base import MIMEBase
    from email import encoders

    config = get_mail_config()
    if not config:
        return {"success": False, "error": "邮件配置未找到"}

    smtp_client = SMTPClient(config)

    try:
        smtp_client.connect()

        # 创建带附件的邮件
        if attachments:
            msg = MIMEMultipart('mixed')
        else:
            msg = MIMEMultipart('alternative')

        msg['From'] = config['username']
        msg['To'] = to
        msg['Subject'] = subject

        if cc:
            msg['Cc'] = cc

        # 添加正文部分
        if attachments:
            # 有附件时，正文需要放在multipart/alternative中
            text_part = MIMEMultipart('alternative')
            text_part.attach(MIMEText(body, 'plain', 'utf-8'))
            if html_body:
                text_part.attach(MIMEText(html_body, 'html', 'utf-8'))
            msg.attach(text_part)
        else:
            # 无附件直接添加正文
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            if html_body:
                msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # 添加附件
        if attachments:
            for att in attachments:
                with open(att['path'], 'rb') as f:
                    part = MIMEBase(*att.get('content_type', 'application/octet-stream').split('/'))
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=att['filename']
                    )
                    msg.attach(part)

        # 发送
        recipients = [to]
        if cc:
            recipients.append(cc)
        smtp_client.client.sendmail(config['username'], recipients, msg.as_string())

        result = {"success": True, "message_id": msg.get('Message-ID', '')}

        if result['success']:
            # 保存到数据库（检查是否已存在）
            message_id = result.get('message_id')
            from Sills.db_mail import get_db_connection

            # 检查邮件是否已存在
            existing = None
            if message_id:
                with get_db_connection() as conn:
                    existing = conn.execute(
                        "SELECT id FROM uni_mail WHERE message_id = ?",
                        (message_id,)
                    ).fetchone()

            if not existing:
                save_email({
                    'subject': subject,
                    'from_addr': config.get('username', ''),
                    'to_addr': to,
                    'cc_addr': cc,
                    'content': body,
                    'html_content': html_body,
                    'sent_at': datetime.now().isoformat(),
                    'is_sent': 1,
                    'message_id': message_id,
                    'sync_status': 'completed',
                    'account_id': config.get('id')
                })

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        smtp_client.disconnect()