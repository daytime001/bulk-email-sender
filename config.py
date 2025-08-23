#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮件发送配置文件
请在此处修改所有配置参数
"""

# ==================== 邮箱配置 ====================
# 126邮箱配置
SENDER_EMAIL = 'your_email@126.com'  # 您的126邮箱地址
SENDER_PASSWORD = 'your_authorization_code'  # 您的126邮箱授权码（不是登录密码！）
SENDER_NAME = '您的姓名'  # 发件人姓名

# SMTP服务器配置
SMTP_SERVER = 'smtp.126.com'
SMTP_PORT = 465

# ==================== 邮件内容配置 ====================
# 邮件主题
EMAIL_SUBJECT = '推免自荐+学校名称+您的姓名'

# 邮件正文模板（{teacher_name}会被替换为导师姓名）
EMAIL_CONTENT = """尊敬的{teacher_name}：

　　您好！我是来自XXX大学XXX专业的XXX，预计能够以专业第X的成绩获得推免资格。冒昧致信，请问您是否还有空余的招生名额？下面是我的一些基本情况介绍，随信附上个人简历与成绩单。

　　【请在此处填写您的个人介绍内容】

　　感谢拨冗垂阅，如有不妥望您海涵，诚盼老师的回复！

                                                                                                                                  学生XXX
                                                                                                                                XXXX年XX月XX日
"""

# ==================== 文件路径配置 ====================
# 导师数据文件路径
TEACHER_DATA_FILE = 'data/teachers.json'

# 附件文件路径列表（可为空）
ATTACHMENTS = []  # 例如: ['attachments/resume.pdf', 'attachments/transcript.pdf']

# 日志文件路径
LOG_FILE = 'email_log.txt'

# ==================== 发送控制配置 ====================
# 发送间隔时间（秒）
MIN_DELAY = 30  # 最小间隔
MAX_DELAY = 60  # 最大间隔

# 是否随机打乱发送顺序
RANDOMIZE_ORDER = True

# 是否在导师姓名后添加"老师"后缀
ADD_TEACHER_SUFFIX = True
