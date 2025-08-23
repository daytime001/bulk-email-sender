#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量发送邮件主程序
"""

from config import *
from email_sender import EmailSender
from data_loader import DataLoader


def analyze_sending_status(email_sender, teacher_data):
    """
    分析发送状态

    Args:
        email_sender: 邮件发送器实例
        teacher_data: 导师数据字典

    Returns:
        tuple: (已发送数量, 本次将发送数量, 不匹配的邮箱集合)
    """
    current_teacher_emails = set(teacher_data.keys())
    sent_emails_in_current = email_sender.sent_emails.intersection(current_teacher_emails)
    sent_emails_not_in_current = email_sender.sent_emails - current_teacher_emails

    already_sent_count = len(sent_emails_in_current)
    to_send_count = len(teacher_data) - already_sent_count

    return already_sent_count, to_send_count, sent_emails_not_in_current


def main():
    """主函数"""
    print("🚀 批量邮件发送工具")
    print("="*50)

    # 检查配置
    if SENDER_EMAIL == 'your_email@126.com' or SENDER_PASSWORD == 'your_authorization_code':
        print("❌ 请先在 config.py 中配置您的邮箱信息！")
        return

    # 创建数据加载器和邮件发送器
    data_loader = DataLoader()
    email_sender = EmailSender()

    # 加载导师数据
    teacher_data = data_loader.load_teacher_data(TEACHER_DATA_FILE)
    if not teacher_data:
        print("❌ 无法加载导师数据，程序退出")
        return

    # 分析发送状态
    already_sent_count, to_send_count, sent_emails_not_in_current = analyze_sending_status(email_sender, teacher_data)

    # 显示配置信息
    print(f"📧 发件邮箱: {SENDER_EMAIL}")
    print(f"👤 发件人: {SENDER_NAME}")
    print(f"📊 导师数量: {len(teacher_data)}")
    print(f"✅ 已发送数量: {already_sent_count}")
    print(f"📮 本次将发送: {to_send_count}")
    print(f"📎 附件数量: {len(ATTACHMENTS)}")
    print(f"⏱️  发送间隔: {MIN_DELAY}-{MAX_DELAY}秒")
    print(f"📄 邮件主题: {EMAIL_SUBJECT}")

    # 如果有已发送但不在当前数据中的邮箱，给出提示
    if sent_emails_not_in_current:
        print(f"⚠️  注意: 发现 {len(sent_emails_not_in_current)} 个已发送邮箱不在当前导师数据中")
        if len(sent_emails_not_in_current) <= 5:
            print("   不匹配的邮箱:")
            for email in sorted(sent_emails_not_in_current):
                print(f"     - {email}")
        else:
            print("   (数量较多，不显示详情)")

    # 确认发送
    print("\n" + "="*50)
    confirm = input("确认开始发送？(输入 yes 确认): ").strip()
    if confirm.lower() != 'yes':
        print("❌ 用户取消发送")
        return

    # 开始批量发送
    email_sender.batch_send(teacher_data)

if __name__ == "__main__":
    main()
