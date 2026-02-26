import { memo, useMemo } from 'react';
import { Table } from 'antd';
import { FileSpreadsheet, FolderOpen, ListChecks, Users } from 'lucide-react';

import type { Recipient, RecipientStats } from '@/types';
import { Badge as UiBadge } from '@/components/ui/badge';
import { Button as UiButton } from '@/components/ui/button';
import {
  Card as UiCard,
  CardContent as UiCardContent,
  CardDescription as UiCardDescription,
  CardHeader as UiCardHeader,
  CardTitle as UiCardTitle,
} from '@/components/ui/card';
import { Input as UiInput } from '@/components/ui/input';

interface RecipientsWorkspaceProps {
  recipientsPath: string;
  recipients: Recipient[];
  recipientsStats: RecipientStats | null;
  onRecipientsPathChange: (value: string) => void;
  onPickRecipientsFile: () => void;
  onLoadRecipients: () => void;
}

const recipientsColumns = [
  { title: '邮箱', dataIndex: 'email', key: 'email' },
  { title: '姓名', dataIndex: 'name', key: 'name' },
];

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function isValidEmail(email: string): boolean {
  return EMAIL_PATTERN.test(email.trim());
}

function RecipientsWorkspaceInner({
  recipientsPath,
  recipients,
  recipientsStats,
  onRecipientsPathChange,
  onPickRecipientsFile,
  onLoadRecipients,
}: RecipientsWorkspaceProps) {
  const stats = useMemo(() => {
    if (recipientsStats) {
      return {
        total: recipientsStats.total_rows,
        sendable: recipientsStats.sendable_rows,
        invalidEmail: recipientsStats.invalid_email_rows,
        missingName: recipientsStats.missing_name_rows,
      };
    }

    const total = recipients.length;
    const sendable = recipients.filter(
      (item) => isValidEmail(item.email) && item.name.trim().length > 0,
    ).length;
    const invalidEmail = recipients.filter((item) => !isValidEmail(item.email)).length;
    const missingName = recipients.filter(
      (item) => isValidEmail(item.email) && item.name.trim().length === 0,
    ).length;
    return { total, sendable, invalidEmail, missingName };
  }, [recipients, recipientsStats]);

  return (
    <div className="recipients-workbench">
      <UiCard className="recipients-path-card py-0">
        <UiCardHeader className="px-6 pt-6 pb-4">
          <div className="flex flex-wrap items-center gap-2">
            <UiBadge variant="secondary" className="bg-slate-100 text-slate-700">
              <FileSpreadsheet className="size-3.5" />
              收件人数据源
            </UiBadge>
            <UiBadge variant="outline" className="border-slate-200 bg-white text-slate-700">
              支持 JSON / XLSX
            </UiBadge>
          </div>
          <UiCardTitle className="text-xl text-slate-900">收件人导入</UiCardTitle>
          <UiCardDescription>先选择数据文件，再点击解析。</UiCardDescription>
        </UiCardHeader>
        <UiCardContent className="space-y-4 px-6 pb-6">
          <div className="flex flex-col gap-3 md:flex-row">
            <UiInput
              name="recipients_path"
              value={recipientsPath}
              onChange={(event) => onRecipientsPathChange(event.target.value)}
              placeholder="收件人文件路径（json / xlsx）"
              autoComplete="off"
              spellCheck={false}
              className="h-11 flex-1 border-slate-200 bg-white"
            />
            <div className="flex gap-2">
              <UiButton
                type="button"
                variant="outline"
                className="h-11"
                onClick={onPickRecipientsFile}
              >
                <FolderOpen className="size-4" />
                选择文件
              </UiButton>
              <UiButton
                type="button"
                className="h-11"
                onClick={onLoadRecipients}
              >
                <ListChecks className="size-4" />
                解析文件
              </UiButton>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
            <UiBadge variant="secondary" className="h-8 justify-center bg-slate-100 text-slate-700">
              <Users className="size-3.5" />
              总数 {stats.total}
            </UiBadge>
            <UiBadge variant="secondary" className="h-8 justify-center bg-slate-100 text-slate-700">
              可发送数 {stats.sendable}
            </UiBadge>
            <UiBadge variant="secondary" className="h-8 justify-center bg-slate-100 text-slate-700">
              无效邮箱数 {stats.invalidEmail}
            </UiBadge>
            <UiBadge variant="secondary" className="h-8 justify-center bg-slate-100 text-slate-700">
              缺姓名数 {stats.missingName}
            </UiBadge>
          </div>
        </UiCardContent>
      </UiCard>

      <UiCard className="recipients-table-card mt-4 py-0">
        <UiCardHeader className="px-6 pt-5 pb-2">
          <UiCardTitle className="text-base text-slate-900">收件人明细</UiCardTitle>
          <UiCardDescription>解析结果仅在本地使用，不会上传到任何外部服务。</UiCardDescription>
        </UiCardHeader>
        <UiCardContent className="px-6 pb-6">
          <Table<Recipient>
            size="small"
            rowKey={(row, index) => `${row.email}-${index ?? 0}`}
            columns={recipientsColumns}
            dataSource={recipients}
            pagination={{ pageSize: 8 }}
          />
        </UiCardContent>
      </UiCard>
    </div>
  );
}

export const RecipientsWorkspace = memo(RecipientsWorkspaceInner);
