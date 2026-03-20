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
    release_sync_lock, update_mail_sync_status, recover_orphaned_syncs
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

    def fetch_emails(self, limit: int = 50, folder: str = 'INBOX') -> List[Dict[str, Any]]:
        """
        获取邮件列表

        Args:
            limit: 最大获取数量
            folder: 邮箱文件夹

        Returns:
            邮件数据列表
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server")

        emails = []

        try:
            self.client.select(folder)
            status, messages = self.client.search(None, 'ALL')

            if status != 'OK':
                return emails

            message_ids = messages[0].split()[-limit:]  # 获取最新的 N 封

            for msg_id in message_ids:
                status, msg_data = self.client.fetch(msg_id, '(RFC822)')
                if status != 'OK':
                    continue

                raw_email = msg_data[0][1]
                email_data = self._parse_email(raw_email)
                if email_data:
                    emails.append(email_data)

        except Exception as e:
            print(f"Fetch emails error: {e}")

        return emails

    def _parse_email(self, raw_email: bytes) -> Optional[Dict[str, Any]]:
        """解析原始邮件"""
        try:
            msg = email.message_from_bytes(raw_email)

            # 解码主题
            subject = self._decode_header(msg.get('Subject', ''))

            # 解析发件人
            from_addr = self._decode_header(msg.get('From', ''))
            _, from_email = parseaddr(from_addr)

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
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    content = decode_payload(payload, msg)

            return {
                'subject': subject,
                'from_addr': from_email or from_addr,
                'to_addr': to_addr,
                'cc_addr': cc_addr,
                'content': content,
                'html_content': html_content,
                'received_at': received_at,
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
    同步收件箱（后台任务）

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
            return {"status": "error", "message": "Mail config not found"}

        # 获取当前账户ID用于用户隔离
        current_account_id = config.get('id')

        imap_client = IMAPClient(config)
        imap_client.connect()

        emails = imap_client.fetch_emails(limit=50)

        saved_count = 0
        updated_count = 0
        for email_data in emails:
            # 检查是否已存在
            if email_data.get('message_id'):
                from Sills.db_mail import get_db_connection
                with get_db_connection() as conn:
                    existing = conn.execute(
                        "SELECT id, account_id FROM uni_mail WHERE message_id = ?",
                        (email_data['message_id'],)
                    ).fetchone()
                    if existing:
                        existing_id, existing_account_id = existing
                        # 如果邮件存在但 account_id 为 NULL，更新为当前账户
                        if existing_account_id is None and current_account_id is not None:
                            conn.execute(
                                "UPDATE uni_mail SET account_id = ? WHERE id = ?",
                                (current_account_id, existing_id)
                            )
                            conn.commit()
                            updated_count += 1
                        continue

            # 关联当前账户ID
            email_data['account_id'] = current_account_id

            # 保存邮件
            save_email(email_data)
            saved_count += 1

        imap_client.disconnect()

        return {
            "status": "completed",
            "message": f"Synced {saved_count} new emails, updated {updated_count} existing"
        }

    except Exception as e:
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


def send_email_now(to: str, subject: str, body: str,
                   html_body: str = None) -> Dict[str, Any]:
    """
    立即发送邮件

    Args:
        to: 收件人
        subject: 主题
        body: 正文
        html_body: HTML 正文（可选）

    Returns:
        发送结果
    """
    smtp_client = SMTPClient()

    try:
        smtp_client.connect()
        result = smtp_client.send_email(to, subject, body, html_body)
        smtp_client.disconnect()

        if result['success']:
            # 保存到数据库
            save_email({
                'subject': subject,
                'from_addr': smtp_client.config.get('username', ''),
                'to_addr': to,
                'content': body,
                'html_content': html_body,
                'sent_at': datetime.now().isoformat(),
                'is_sent': 1,
                'message_id': result.get('message_id'),
                'sync_status': 'completed',
                'account_id': smtp_client.config.get('id')  # 关联当前账户ID
            })

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        smtp_client.disconnect()