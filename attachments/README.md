# 附件文件夹

请将您的附件文件放在此文件夹中，例如：

- `resume.pdf` - 个人简历
- `transcript.pdf` - 成绩单
- `personal_statement.pdf` - 个人陈述

然后在 `config.py` 中的 `ATTACHMENTS` 列表中添加文件路径：

```python
ATTACHMENTS = [
    'attachments/resume.pdf',
    'attachments/transcript.pdf',
    'attachments/personal_statement.pdf'
]
```

## 注意事项

1. 附件文件大小建议不超过10MB
2. 支持常见格式：PDF、DOC、DOCX、JPG、PNG等
3. 文件名建议使用英文，避免特殊字符（中文也可）
