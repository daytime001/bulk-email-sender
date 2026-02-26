import { memo, useMemo } from 'react';
import { Alert, Checkbox, InputNumber, Progress, Space, Table, Tag, Typography } from 'antd';
import { Loader2, Paperclip, Play, Send } from 'lucide-react';

import { Button as UiButton } from '@/components/ui/button';
import {
  Card as UiCard,
  CardContent as UiCardContent,
  CardDescription as UiCardDescription,
  CardHeader as UiCardHeader,
  CardTitle as UiCardTitle,
} from '@/components/ui/card';
import { Input as UiInput } from '@/components/ui/input';
import { Textarea as UiTextarea } from '@/components/ui/textarea';

const { Text } = Typography;

const TEACHER_TOKEN = '{teacher_name}';
const SENDER_TOKEN = '{sender_name}';
const DATE_TOKEN = '{send_date}';
const REQUIRED_TEMPLATE_TOKENS = [TEACHER_TOKEN, SENDER_TOKEN, DATE_TOKEN] as const;
const FULL_WIDTH_INDENT = '　　';

interface SendSummary {
  total: number;
  success: number;
  failed: number;
  skipped: number;
}

interface WaitInfo {
  remainingSec: number;
  delaySec: number;
  nextIndex: number;
}

interface FailureItem {
  email: string;
  name: string;
  error: string;
}

interface EmailContentWorkspaceProps {
  subject: string;
  bodyText: string;
  attachmentsText: string;
  isSending: boolean;
  skipSent: boolean;
  minDelaySec: number;
  maxDelaySec: number;
  progressPercent: number;
  currentStatus: string;
  doneCount: number;
  summary: SendSummary;
  waitInfo: WaitInfo | null;
  failures: FailureItem[];
  onSubjectChange: (value: string) => void;
  onBodyTextChange: (value: string) => void;
  onAttachmentsTextChange: (value: string) => void;
  onPickAttachments: () => void;
  onClearAttachments: () => void;
  onStartSend: () => void;
  onCancelSend: () => void;
  onSkipSentChange: (checked: boolean) => void;
  onClearSentRecords: () => void;
  onMinDelaySecChange: (value: number) => void;
  onMaxDelaySecChange: (value: number) => void;
}

const failureColumns = [
  { title: '邮箱', dataIndex: 'email', key: 'email' },
  { title: '姓名', dataIndex: 'name', key: 'name' },
  { title: '错误信息', dataIndex: 'error', key: 'error' },
];

function EmailContentWorkspaceInner({
  subject,
  bodyText,
  attachmentsText,
  isSending,
  skipSent,
  minDelaySec,
  maxDelaySec,
  progressPercent,
  currentStatus,
  doneCount,
  summary,
  waitInfo,
  failures,
  onSubjectChange,
  onBodyTextChange,
  onAttachmentsTextChange,
  onPickAttachments,
  onClearAttachments,
  onStartSend,
  onCancelSend,
  onSkipSentChange,
  onClearSentRecords,
  onMinDelaySecChange,
  onMaxDelaySecChange,
}: EmailContentWorkspaceProps) {
  const missingTokens = useMemo(
    () => REQUIRED_TEMPLATE_TOKENS.filter((token) => !bodyText.includes(token)),
    [bodyText],
  );
  const attachmentCount = useMemo(
    () => attachmentsText
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter((item) => item.length > 0).length,
    [attachmentsText],
  );

  const handleBodyTextChange = (value: string) => {
    onBodyTextChange(value.replace(/\r\n/g, '\n'));
  };

  const handleBodyTextEnterIndent: React.KeyboardEventHandler<HTMLTextAreaElement> = (event) => {
    if (event.key !== 'Enter' || event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }

    event.preventDefault();
    const target = event.currentTarget;
    const { selectionStart, selectionEnd, value } = target;
    const breakToken = event.shiftKey ? `\n${FULL_WIDTH_INDENT}` : `\n\n${FULL_WIDTH_INDENT}`;
    const nextValue = `${value.slice(0, selectionStart)}${breakToken}${value.slice(selectionEnd)}`;
    onBodyTextChange(nextValue);

    const nextCursor = selectionStart + breakToken.length;
    window.requestAnimationFrame(() => {
      target.setSelectionRange(nextCursor, nextCursor);
    });
  };

  return (
    <div className="email-workbench">
      <UiCard className="email-editor-card py-0">
        <UiCardHeader className="px-5 pt-5 pb-3">
          <UiCardTitle className="text-xl tracking-tight text-slate-900">邮件内容</UiCardTitle>
          <UiCardDescription>填写主题与正文模板，固定占位符请勿改动</UiCardDescription>
        </UiCardHeader>
        <UiCardContent className="space-y-3 px-5 pb-5">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">邮件主题</label>
            <UiInput
              name="email_subject"
              value={subject}
              onChange={(event) => onSubjectChange(event.target.value)}
              placeholder="请输入邮件主题"
              autoComplete="off"
              className="h-11 border-slate-200 bg-white"
            />
          </div>

          <div className="overflow-x-auto whitespace-nowrap rounded-md border border-sky-100 bg-sky-50 px-3 py-2 text-xs text-slate-700">
            占位符完整性检查：<span className="font-mono">{TEACHER_TOKEN}</span>=收件人姓名；
            <span className="font-mono">{SENDER_TOKEN}</span>、<span className="font-mono">{DATE_TOKEN}</span>
            在发送时会自动渲染到正文右下方（缺少任一占位符将禁止发送）
          </div>

          <div className="space-y-3">
            <label className="text-sm font-medium text-slate-700">正文模板</label>
            <UiTextarea
              name="email_body_template"
              rows={14}
              value={bodyText}
              onChange={(event) => handleBodyTextChange(event.target.value)}
              onKeyDown={handleBodyTextEnterIndent}
              spellCheck={false}
              className="email-body-textarea min-h-[360px] border-slate-200 bg-white text-[15px]"
            />
            {missingTokens.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message="模板缺少固定占位符"
                description={`请补充：${missingTokens.join('、')}`}
              />
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-sm font-medium text-slate-700">附件</label>
              <div className="flex gap-2">
                <UiButton type="button" variant="outline" size="sm" className="h-7" onClick={onPickAttachments}>
                  选择
                </UiButton>
                <UiButton type="button" variant="outline" size="sm" className="h-7" onClick={onClearAttachments}>
                  清空
                </UiButton>
              </div>
            </div>
            <UiTextarea
              name="email_attachments"
              rows={3}
              value={attachmentsText}
              onChange={(event) => onAttachmentsTextChange(event.target.value)}
              placeholder={'attachments/resume.pdf\nattachments/transcript.pdf'}
              spellCheck={false}
              className="border-slate-200 bg-white leading-7"
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              <Paperclip className="mr-1 inline size-3.5" />
              当前附件 {attachmentCount} 个
            </Text>
          </div>
        </UiCardContent>
      </UiCard>

      <UiCard className="email-send-card mt-4 py-0">
        <UiCardHeader className="px-5 pt-4 pb-2">
          <UiCardTitle className="text-base text-slate-900">发送控制</UiCardTitle>
        </UiCardHeader>
        <UiCardContent className="space-y-3 px-5 pb-5">
          <div className="flex flex-wrap items-center gap-2">
            <UiButton
              type="button"
              size="lg"
              className="h-10 min-w-32"
              disabled={isSending}
              onClick={onStartSend}
            >
              {isSending ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
              开始发送
            </UiButton>
            <UiButton type="button" variant="outline" size="lg" className="h-10" disabled={!isSending} onClick={onCancelSend}>
              取消任务
            </UiButton>
            <UiButton
              type="button"
              variant="outline"
              size="lg"
              className="h-10"
              disabled={isSending}
              onClick={onClearSentRecords}
            >
              清除发送记录
            </UiButton>
            <Checkbox checked={skipSent} onChange={(e) => onSkipSentChange(e.target.checked)} disabled={isSending}>
              跳过已发送
            </Checkbox>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Text type="secondary" style={{ fontSize: 12 }}><Send className="mr-1 inline size-3.5" />发送间隔（秒）</Text>
            <InputNumber
              size="small"
              min={0}
              max={maxDelaySec}
              value={minDelaySec}
              onChange={(value) => onMinDelaySecChange(value ?? 0)}
              disabled={isSending}
              style={{ width: 74 }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>~</Text>
            <InputNumber
              size="small"
              min={minDelaySec}
              max={600}
              value={maxDelaySec}
              onChange={(value) => onMaxDelaySecChange(value ?? 0)}
              disabled={isSending}
              style={{ width: 74 }}
            />
          </div>

          <Progress percent={progressPercent} status={isSending ? 'active' : 'normal'} style={{ marginBottom: 0 }} />

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>{currentStatus}</Text>
            <Space size={4}>
              <Tag color="purple">进度 {doneCount}/{summary.total}</Tag>
              <Tag color="green">成功 {summary.success}</Tag>
              <Tag color="red">失败 {summary.failed}</Tag>
              <Tag color="gold">跳过 {summary.skipped}</Tag>
              <Tag color="blue">总计 {summary.total}</Tag>
            </Space>
          </div>

          {waitInfo && isSending && (
            <Alert
              showIcon
              type="info"
              message={`节奏控制中：${waitInfo.remainingSec}s 后发送第 ${waitInfo.nextIndex} 封`}
              description={`当前轮次间隔 ${waitInfo.delaySec}s，用于降低连续发送触发风控的概率。`}
            />
          )}
        </UiCardContent>
      </UiCard>

      {failures.length > 0 && (
        <UiCard className="email-failures-card mt-4 py-0">
          <UiCardHeader className="px-6 pt-5 pb-2">
            <UiCardTitle className="text-base text-slate-900">失败明细</UiCardTitle>
            <UiCardDescription>请修复下列条目后重试。</UiCardDescription>
          </UiCardHeader>
          <UiCardContent className="px-6 pb-6">
            <Table
              size="small"
              rowKey={(row) => `${row.email}-${row.error}`}
              columns={failureColumns}
              dataSource={failures}
              pagination={{ pageSize: 5 }}
            />
          </UiCardContent>
        </UiCard>
      )}
    </div>
  );
}

export const EmailContentWorkspace = memo(EmailContentWorkspaceInner);
