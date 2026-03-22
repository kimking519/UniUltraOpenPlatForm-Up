"""
邮件服务层
SmartMail Integration - Mail Service Layer

IMAP/SMTP 客户端实现，支持后台同步
"""
import imaplib
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
            'Sent', 'Sent Items', 'Sent Messages', '已发送', '发件箱',
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
            if 'sent' in decoded_lower or '发件' in decoded_name:
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

    def find_system_folder(self) -> Optional[str]:
        """
        自动查找系统邮件文件夹（退信、系统通知等）

        Returns:
            系统邮件文件夹原始名称，未找到返回None
        """
        folders = self.list_folders()

        # 常见的系统邮件文件夹名称
        system_names = [
            'System', 'System Messages', '系统邮件', '系统通知',
            'Notifications', 'Notices', 'Alerts',
            '&fPt+35AAT+E-'  # IMAP UTF-7 编码的"系统邮件"
        ]

        # 先精确匹配解码后的名称
        for raw_name, decoded_name in folders:
            if decoded_name in system_names or raw_name in system_names:
                print(f"[Mail] 找到系统邮件文件夹: {raw_name} ({decoded_name})")
                return raw_name

        # 再模糊匹配
        for raw_name, decoded_name in folders:
            decoded_lower = decoded_name.lower()
            if 'system' in decoded_lower or '系统' in decoded_name or 'notification' in decoded_lower:
                print(f"[Mail] 模糊匹配找到系统邮件文件夹: {raw_name} ({decoded_name})")
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

        # 获取分批处理配置（默认：每批100封，暂停1秒）
        batch_size = config.get('sync_batch_size') or 100
        pause_seconds = config.get('sync_pause_seconds') or 1.0
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
        sent_folder = imap_client.find_sent_folder()
        print(f"[Mail] 检测到发件箱: {sent_folder}")

        spam_folder = imap_client.find_spam_folder()
        print(f"[Mail] 检测到垃圾邮件文件夹: {spam_folder}")

        # 获取或创建本地垃圾邮件文件夹
        from Sills.db_mail import get_or_create_spam_folder
        spam_folder_id = get_or_create_spam_folder(current_account_id) if spam_folder else None

        # 自动检测系统邮件文件夹（退信、系统通知等）
        system_folder = imap_client.find_system_folder()
        print(f"[Mail] 检测到系统邮件文件夹: {system_folder}")

        # 同步收件箱、发件箱、垃圾邮件、系统邮件
        # (文件夹名, is_sent, 显示标签, 本地folder_id)
        folders_to_sync = [('INBOX', 0, '收件箱', None)]
        if sent_folder:
            folders_to_sync.append((sent_folder, 1, '发件箱', None))
        if spam_folder:
            folders_to_sync.append((spam_folder, 0, '垃圾邮件', spam_folder_id))
        if system_folder:
            folders_to_sync.append((system_folder, 0, '系统邮件', None))

        total_saved = 0
        total_updated = 0
        total_processed = 0

        # === UID预过滤优化：只获取本地没有的邮件 ===
        from Sills.db_mail import get_local_uids, get_local_message_ids

        # 先获取本地已有的Message-ID作为备用（处理UID为空的情况）
        local_message_ids = get_local_message_ids(current_account_id)
        print(f"[Mail] 本地已有 {len(local_message_ids)} 封邮件")

        # 按文件夹获取新邮件
        all_emails_data = []
        for folder_name, is_sent, folder_label, local_folder_id in folders_to_sync:
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

                # Step 3: 计算需要获取的UID（服务器有但本地没有的）
                new_uids = list(set(server_uids) - local_uids)
                print(f"[Mail] {folder_label}: 服务器 {len(server_uids)} 封, 本地 {len(local_uids)} 封, 新增 {len(new_uids)} 封")

                if not new_uids:
                    print(f"[Mail] {folder_label}: 无新邮件需要同步")
                    continue

                # Step 4: 只获取新邮件
                update_sync_progress(10, 100, f"获取{folder_label}新邮件...")
                emails = imap_client.fetch_emails_by_uid(folder_name, new_uids)

                if emails:
                    for email_data in emails:
                        email_data['is_sent'] = is_sent
                        email_data['folder_label'] = folder_label
                        email_data['imap_folder'] = folder_name
                        # 设置本地文件夹ID（垃圾邮件文件夹）
                        if local_folder_id:
                            email_data['folder_id'] = local_folder_id
                    all_emails_data.extend(emails)

            except Exception as e:
                print(f"[Mail] 扫描 {folder_name} 失败: {e}")
                import traceback
                traceback.print_exc()

        grand_total_emails = len(all_emails_data)
        print(f"[Mail] 总计 {grand_total_emails} 封邮件待同步")

        # 更新总邮件数
        update_sync_progress(10, 100, f"共发现 {grand_total_emails} 封邮件", total_emails=grand_total_emails)

        # 同步邮件（分批处理）
        import time
        batch_count = 0
        for idx, email_data in enumerate(all_emails_data):
            # 检查是否已存在
            is_new_email = True
            if email_data.get('message_id'):
                from Sills.db_mail import get_db_connection
                with get_db_connection() as conn:
                    existing = conn.execute(
                        "SELECT id, account_id FROM uni_mail WHERE message_id = ?",
                        (email_data['message_id'],)
                    ).fetchone()
                    if existing:
                        existing_id, existing_account_id = existing
                        # 如果邮件存在但 account_id 不是当前账户，更新为当前账户
                        if existing_account_id != current_account_id:
                            conn.execute(
                                "UPDATE uni_mail SET account_id = ? WHERE id = ?",
                                (current_account_id, existing_id)
                            )
                            conn.commit()
                            total_updated += 1
                        is_new_email = False

            # 保存新邮件
            if is_new_email:
                email_data['account_id'] = current_account_id
                save_email(email_data)
                total_saved += 1

            # 更新已处理数量
            total_processed += 1

            # 计算进度百分比并更新
            if grand_total_emails > 0:
                percent = int((total_processed / grand_total_emails) * 100)
            else:
                percent = 0

            folder_label = email_data.get('folder_label', '')
            current_batch = (idx // batch_size) + 1
            total_batches = (grand_total_emails + batch_size - 1) // batch_size
            update_sync_progress(
                percent, 100,
                f"批次 {current_batch}/{total_batches} - {folder_label} {idx + 1}/{grand_total_emails}",
                synced_emails=total_processed
            )

            # 分批暂停：每处理完一批后暂停，让系统喘息
            if (idx + 1) % batch_size == 0 and idx + 1 < grand_total_emails:
                batch_count += 1
                print(f"[Mail] 批次 {batch_count} 完成，暂停 {pause_seconds} 秒...")
                time.sleep(pause_seconds)

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
    增量同步：只获取上次同步后的新邮件

    Returns:
        {"status": "completed", "new_count": int}
    """
    from Sills.db_mail import get_latest_mail_time
    from datetime import datetime

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
        update_sync_progress(0, 100, "检查最新邮件时间...")

        # 获取最新邮件时间
        latest_time_str = get_latest_mail_time(current_account_id, 0)
        since_date = None
        if latest_time_str:
            try:
                since_date = datetime.fromisoformat(latest_time_str.replace('Z', '+00:00'))
                print(f"[Mail] 增量同步，起始时间: {since_date}")
            except Exception as e:
                print(f"[Mail] 解析时间失败: {e}")

        imap_client = IMAPClient(config)
        imap_client.connect()

        # 自动检测发件箱
        update_sync_progress(10, 100, "检测邮箱文件夹...")
        sent_folder = imap_client.find_sent_folder()
        spam_folder = imap_client.find_spam_folder()
        system_folder = imap_client.find_system_folder()

        # 同步收件箱、发件箱、垃圾邮件、系统邮件
        folders_to_sync = [('INBOX', 0, '收件箱')]
        if sent_folder:
            folders_to_sync.append((sent_folder, 1, '发件箱'))
        if spam_folder:
            folders_to_sync.append((spam_folder, 0, '垃圾邮件'))
        if system_folder:
            folders_to_sync.append((system_folder, 0, '系统邮件'))

        total_saved = 0
        total_processed = 0

        # 先获取所有新邮件并统计总数
        all_emails_data = []
        for folder_name, is_sent, folder_label in folders_to_sync:
            try:
                update_sync_progress(10, 100, f"扫描{folder_label}新邮件...")
                print(f"[Mail] 增量同步文件夹: {folder_name}")
                # 使用since_date进行增量同步
                emails = imap_client.fetch_emails(folder=folder_name, days=7, since_date=since_date)
                if emails:
                    for email_data in emails:
                        email_data['is_sent'] = is_sent
                        email_data['folder_label'] = folder_label
                        email_data['imap_folder'] = folder_name
                    all_emails_data.extend(emails)
                    print(f"[Mail] {folder_label}: {len(emails)} 封新邮件")
            except Exception as e:
                print(f"[Mail] 扫描 {folder_name} 失败: {e}")

        grand_total_emails = len(all_emails_data)
        print(f"[Mail] 总计 {grand_total_emails} 封新邮件待同步")

        # 设置同步日期范围（增量同步使用最近7天）
        from datetime import datetime, timedelta
        sync_start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        sync_end = datetime.now().strftime('%Y-%m-%d')

        # 更新总邮件数
        update_sync_progress(20, 100, f"共发现 {grand_total_emails} 封新邮件",
                           sync_start_date=sync_start, sync_end_date=sync_end,
                           total_emails=grand_total_emails, synced_emails=0)

        # 获取分批处理配置
        batch_size = config.get('sync_batch_size') or 100
        pause_seconds = config.get('sync_pause_seconds') or 1.0

        # 同步邮件（分批处理）
        import time
        for idx, email_data in enumerate(all_emails_data):
            # 检查是否已存在
            is_new_email = True
            if email_data.get('message_id'):
                from Sills.db_mail import get_db_connection
                with get_db_connection() as conn:
                    existing = conn.execute(
                        "SELECT id FROM uni_mail WHERE message_id = ?",
                        (email_data['message_id'],)
                    ).fetchone()
                    if existing:
                        is_new_email = False

            # 保存新邮件
            if is_new_email:
                email_data['account_id'] = current_account_id
                save_email(email_data)
                total_saved += 1

            # 更新已处理数量
            total_processed += 1

            # 计算进度百分比并更新
            if grand_total_emails > 0:
                percent = int((total_processed / grand_total_emails) * 100)
            else:
                percent = 0

            folder_label = email_data.get('folder_label', '')
            current_batch = (idx // batch_size) + 1
            total_batches = (grand_total_emails + batch_size - 1) // batch_size if grand_total_emails > 0 else 0
            update_sync_progress(
                percent, 100,
                f"批次 {current_batch}/{total_batches} - {folder_label} {idx + 1}/{grand_total_emails}",
                synced_emails=total_processed
            )

            # 分批暂停
            if (idx + 1) % batch_size == 0 and idx + 1 < grand_total_emails:
                print(f"[Mail] 增量同步批次完成，暂停 {pause_seconds} 秒...")
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