#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮件发送器模块
负责邮件的创建和发送
"""

import os
import time
import random
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate
from config import *

class EmailSender:
    """邮件发送器类"""
    
    def __init__(self):
        self.success_count = 0
        self.fail_count = 0
        self.failed_emails = []
        self.sent_emails = set()  # 记录已发送的邮箱
        self.logger = logging.getLogger(__name__)


        # 配置日志
        self._setup_logging()

        # 加载已发送记录
        self._load_sent_records()

    def _setup_logging(self):
        """设置日志配置"""
        # 创建文件处理器，强制刷新缓冲区
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.INFO)

        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 设置格式
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # 配置根日志记录器
        logging.basicConfig(
            level=logging.INFO,
            handlers=[file_handler, console_handler],
            force=True  # 强制重新配置
        )

        # 确保日志立即刷新
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'flush'):
                handler.flush()

    def flush_logs(self):
        """强制刷新所有日志处理器"""
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'flush'):
                handler.flush()

    def _load_sent_records(self):
        """从日志文件中加载已发送的邮箱记录"""
        if not os.path.exists(LOG_FILE):
            return

        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    # 查找包含发送成功和邮箱地址的日志行
                    if '✅ 发送成功给' in line and '@' in line:
                        # 提取邮箱地址
                        parts = line.split('✅ 发送成功给 ')
                        if len(parts) > 1:
                            email_part = parts[1].split('(')[1].split(')')[0]
                            if '@' in email_part:
                                self.sent_emails.add(email_part)

            if self.sent_emails:
                self.logger.info(f"加载已发送记录: {len(self.sent_emails)} 条")
        except Exception as e:
            self.logger.warning(f"加载已发送记录失败: {e}")

    def is_already_sent(self, email):
        """检查邮箱是否已经发送过"""
        return email in self.sent_emails

    def mark_as_sent(self, email):
        """标记邮箱为已发送"""
        self.sent_emails.add(email)

    def get_sent_summary(self):
        """获取已发送邮箱的摘要信息"""
        if not self.sent_emails:
            return "📭 暂无已发送记录"

        summary = f"📋 已发送邮箱列表 (共 {len(self.sent_emails)} 个):\n"
        summary += "=" * 50 + "\n"

        for i, email in enumerate(sorted(self.sent_emails), 1):
            summary += f"{i:3d}. {email}\n"

        return summary
    
    def create_email_content(self, teacher_name):
        """
        创建邮件正文内容

        Args:
            teacher_name (str): 导师姓名

        Returns:
            str: 邮件正文（HTML格式）
        """
        # 获取原始文本内容
        text_content = EMAIL_CONTENT.format(teacher_name=teacher_name)

        # 转换为HTML格式
        html_content = self.convert_text_to_html(text_content)

        return html_content

    def convert_text_to_html(self, text_content):
        """
        将纯文本转换为HTML格式，优化段落间距

        Args:
            text_content (str): 纯文本内容

        Returns:
            str: HTML格式内容
        """
        # 分割段落
        paragraphs = text_content.split('\n')
        html_paragraphs = []

        signature_started = False

        for paragraph in paragraphs:
            # 先检查是否以全角空格开头（首行缩进标识），再进行strip
            has_indent = paragraph.startswith('　　')
            paragraph_stripped = paragraph.strip()

            if not paragraph_stripped:
                # 空行跳过，不添加额外间距
                continue
            elif paragraph_stripped.startswith('尊敬的') and paragraph_stripped.endswith('：'):
                # 称呼部分
                html_paragraphs.append(f'<p style="margin: 0 0 16px 0; line-height: 1.5;">{paragraph_stripped}</p>')
            elif has_indent:
                # 正文段落，使用正常的段落间距和首行缩进
                # 移除开头的两个全角空格，用CSS text-indent实现缩进
                content = paragraph.lstrip('　').strip()
                html_paragraphs.append(f'<p style="margin: 0 0 16px 0; line-height: 1.8; text-indent: 2em;">{content}</p>')
            elif '学生魏中信' in paragraph_stripped or '2025年' in paragraph_stripped or signature_started:
                # 签名部分开始
                if not signature_started:
                    signature_started = True
                    html_paragraphs.append('<div style="text-align: right; margin-top: 30px; line-height: 1.5;">')

                # 处理签名内容
                if paragraph_stripped:
                    html_paragraphs.append(f'<div style="margin-bottom: 5px;">{paragraph_stripped}</div>')
            else:
                # 其他内容
                html_paragraphs.append(f'<p style="margin: 0 0 16px 0; line-height: 1.5;">{paragraph_stripped}</p>')

        # 如果有签名部分，关闭div
        if signature_started:
            html_paragraphs.append('</div>')

        # 组合HTML内容
        html_body = f'''
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: "Microsoft YaHei", "SimSun", Arial, sans-serif;
                    font-size: 14px;
                    color: #333;
                    line-height: 1.6;
                    margin: 0;
                    padding: 20px;
                    max-width: 1225px;
                }}
            </style>
        </head>
        <body>
            {''.join(html_paragraphs)}
        </body>
        </html>
        '''

        return html_body

    def setup_email_headers(self, msg, teacher_email):
        """
        设置邮件头，确保格式正确避免被拒收

        Args:
            msg: 邮件对象
            teacher_email (str): 收件人邮箱
        """
        # 使用最简单的格式设置邮件头
        msg['From'] = SENDER_EMAIL
        msg['To'] = teacher_email
        msg['Subject'] = EMAIL_SUBJECT

        # 添加一些标准邮件头，提高送达率
        msg['Message-ID'] = f"<{int(time.time() * 1000000)}@{SENDER_EMAIL.split('@')[1]}>"
        msg['Date'] = formatdate(localtime=True)
        msg['MIME-Version'] = '1.0'
    
    def add_attachments(self, msg):
        """
        添加附件到邮件

        Args:
            msg: 邮件对象
        """
        import mimetypes

        for attachment_path in ATTACHMENTS:
            if os.path.exists(attachment_path):
                try:
                    # 获取文件的MIME类型
                    mime_type, _ = mimetypes.guess_type(attachment_path)
                    if mime_type is None:
                        mime_type = 'application/octet-stream'

                    main_type, sub_type = mime_type.split('/', 1)

                    with open(attachment_path, 'rb') as attachment:
                        part = MIMEBase(main_type, sub_type)
                        part.set_payload(attachment.read())
                        encoders.encode_base64(part)

                        # 正确设置文件名，避免中文乱码
                        filename = os.path.basename(attachment_path)
                        # 使用RFC2231编码处理中文文件名
                        from email.header import Header
                        from urllib.parse import quote

                        # 对文件名进行URL编码
                        encoded_filename = quote(filename.encode('utf-8'))

                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename*=UTF-8\'\'{encoded_filename}'
                        )
                        msg.attach(part)
                    # 静默记录附件添加信息到日志
                    self.logger.debug(f"已添加附件: {attachment_path} (类型: {mime_type})")
                except Exception as e:
                    self.logger.warning(f"添加附件失败 {attachment_path}: {e}")
            else:
                self.logger.warning(f"附件文件不存在: {attachment_path}")
                print(f"⚠️  警告: 附件文件不存在: {attachment_path}")
    
    def send_single_email(self, teacher_email, teacher_name, retry_count=3):
        """
        发送单封邮件，支持重试机制

        Args:
            teacher_email (str): 导师邮箱
            teacher_name (str): 导师姓名
            retry_count (int): 重试次数

        Returns:
            bool: 发送是否成功
        """
        for attempt in range(retry_count):
            try:
                # 重试时显示提示
                if attempt > 0:
                    print(f"🔄 第 {attempt + 1} 次尝试发送...")
                    time.sleep(2)  # 重试前等待2秒
                # 创建邮件对象
                msg = MIMEMultipart()

                # 设置邮件头
                self.setup_email_headers(msg, teacher_email)

                # 添加邮件正文（HTML格式）
                html_body = self.create_email_content(teacher_name)
                msg.attach(MIMEText(html_body, 'html', 'utf-8'))

                # 添加附件
                self.add_attachments(msg)

                # 连接SMTP服务器并发送邮件，设置超时和强制关闭
                server = None
                try:
                    server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    # 使用send_message方法，让服务器自动处理邮件头
                    result = server.send_message(msg)
                    # send_message返回的是被拒绝的收件人字典，空字典表示全部成功
                    if result:
                        # 如果有被拒绝的收件人，记录但不抛出异常
                        self.logger.warning(f"部分收件人被拒绝: {result}")
                        print(f"⚠️  部分收件人被拒绝")
                    else:
                        # 全部成功
                        pass
                finally:
                    # 确保连接被关闭
                    if server:
                        try:
                            server.quit()
                        except:
                            try:
                                server.close()
                            except:
                                pass

                # 记录发送成功，包含具体老师信息
                self.logger.info(f"✅ 发送成功给 {teacher_name}({teacher_email})")
                self.flush_logs()  # 强制刷新日志
                self.mark_as_sent(teacher_email)  # 标记为已发送
                self.success_count += 1
                return True

            except smtplib.SMTPAuthenticationError as e:
                error_msg = f"SMTP认证失败: {e}"
                self.logger.error(f"❌ 发送失败: 请检查邮箱和授权码")
                self.flush_logs()  # 强制刷新日志
                # 认证失败不重试
                self.fail_count += 1
                self.failed_emails.append((teacher_email, teacher_name, error_msg))
                return False

            except smtplib.SMTPRecipientsRefused as e:
                error_msg = f"收件人被拒绝: {e}"
                self.logger.error(f"❌ 发送失败: 收件人邮箱无效")
                # 收件人问题不重试
                self.fail_count += 1
                self.failed_emails.append((teacher_email, teacher_name, error_msg))
                return False

            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError) as e:
                # 网络连接相关错误，可以重试
                error_msg = f"网络连接错误: {e}"
                if attempt < retry_count - 1:
                    self.logger.warning(f"⚠️  网络连接问题，将重试 (尝试 {attempt + 1}/{retry_count})")
                    time.sleep(5)  # 等待5秒后重试
                    continue
                else:
                    self.logger.error(f"❌ 发送失败: 网络连接问题，已重试 {retry_count} 次")
                    self.fail_count += 1
                    self.failed_emails.append((teacher_email, teacher_name, error_msg))
                    return False

            except smtplib.SMTPDataError as e:
                error_msg = f"邮件数据错误: {e}"
                self.logger.error(f"❌ 发送失败: 邮件格式问题")
                # 数据格式问题不重试
                self.fail_count += 1
                self.failed_emails.append((teacher_email, teacher_name, error_msg))
                return False

            except Exception as e:
                error_msg = str(e)
                # 检查是否是成功的SMTP响应被误判为异常
                if "250" in error_msg and ("Mail OK" in error_msg or "queued" in error_msg):
                    # 这实际上是成功的响应
                    self.logger.info(f"✅ 发送成功给 {teacher_name}({teacher_email})")
                    self.mark_as_sent(teacher_email)  # 标记为已发送
                    self.success_count += 1
                    return True
                else:
                    # 其他未知错误，可以重试
                    if attempt < retry_count - 1:
                        self.logger.warning(f"⚠️  未知错误，将重试: {error_msg} (尝试 {attempt + 1}/{retry_count})")
                        time.sleep(3)  # 等待3秒后重试
                        continue
                    else:
                        self.logger.error(f"❌ 发送失败: {error_msg}")
                        self.fail_count += 1
                        self.failed_emails.append((teacher_email, teacher_name, error_msg))
                        return False

        # 如果所有重试都失败了
        self.logger.error(f"❌ 发送失败: 已重试 {retry_count} 次，仍然失败")
        self.fail_count += 1
        self.failed_emails.append((teacher_email, teacher_name, "重试次数已用完"))
        return False
    
    def batch_send(self, teacher_data):
        """
        批量发送邮件

        Args:
            teacher_data (dict): 导师数据 {email: name}
        """
        print("\n🚀 开始发送邮件...")
        print("="*50)
        
        # 转换为列表格式
        teacher_list = list(teacher_data.items())
        
        # 随机打乱发送顺序
        if RANDOMIZE_ORDER:
            random.shuffle(teacher_list)
            # 静默记录到日志，不在控制台显示
            self.logger.debug("已随机打乱发送顺序")
        
        total_count = len(teacher_list)
        
        # 统计跳过的邮件数量
        skipped_count = 0

        for i, (email, name) in enumerate(teacher_list, 1):
            # 处理导师姓名
            teacher_name = name + "老师" if ADD_TEACHER_SUFFIX else name

            # 检查是否已经发送过
            if self.is_already_sent(email):
                print(f"[{i}/{total_count}] ⏭️  跳过 {teacher_name}({email}) - 已发送过")
                skipped_count += 1
                continue

            print(f"[{i}/{total_count}] 正在发送给 {teacher_name}({email}) ... ")

            # 发送邮件，添加超时保护
            try:
                success = self.send_single_email(email, teacher_name)
                if not success:
                    print(f"❌ 发送失败，继续下一封邮件")
            except Exception as e:
                print(f"❌ 发送过程中出现异常: {e}")
                self.logger.error(f"发送异常: {e}")

            # 如果不是最后一封邮件，则等待随机时间（分段等待，避免长时间挂起）
            if i < total_count:
                delay = random.randint(MIN_DELAY, MAX_DELAY)
                print(f"⏳ 等待 {delay} 秒后发送下一封...")

                # 分段等待，每5秒检查一次，避免长时间挂起
                remaining_time = delay
                while remaining_time > 0:
                    sleep_time = min(5, remaining_time)
                    time.sleep(sleep_time)
                    remaining_time -= sleep_time
                    if remaining_time > 0:
                        print(f"⏳ 还需等待 {remaining_time} 秒...")
        
        # 输出发送统计
        self.print_summary(skipped_count)
    
    def print_summary(self, skipped_count=0):
        """打印发送统计信息"""
        total_count = self.success_count + self.fail_count

        print("\n" + "="*50)
        print("📊 发送完成统计")
        print("="*50)
        print(f"✅ 成功发送: {self.success_count} 封")
        print(f"❌ 发送失败: {self.fail_count} 封")
        if skipped_count > 0:
            print(f"⏭️  跳过已发送: {skipped_count} 封")
        print(f"📧 本次处理: {total_count} 封")
        print(f"📋 总已发送: {len(self.sent_emails)} 封")

        if total_count > 0:
            success_rate = self.success_count / total_count * 100
            print(f"📈 本次成功率: {success_rate:.1f}%")
        
        if self.failed_emails:
            print(f"\n❌ 发送失败的邮件:")
            for email, name, error in self.failed_emails:
                print(f"  - {name} ({email}): {error}")
        
        print("="*50)
        print(f"📝 详细日志已保存到 {LOG_FILE}")
        
        # 记录统计信息到日志
        self.logger.info(f"发送统计 - 成功: {self.success_count}, 失败: {self.fail_count}, 跳过: {skipped_count}, 本次处理: {total_count}, 总已发送: {len(self.sent_emails)}")
    
    def test_connection(self):
        """
        测试SMTP连接
        
        Returns:
            bool: 连接是否成功
        """
        try:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
            print("✅ SMTP连接测试成功")
            return True
        except Exception as e:
            print(f"❌ SMTP连接测试失败: {e}")
            return False
