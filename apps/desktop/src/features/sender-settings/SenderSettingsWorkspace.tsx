import { memo } from 'react';
import { Alert, App, InputNumber, Select, Tag } from 'antd';
import { LoadingOutlined } from '@ant-design/icons';
import { KeyRound, MailCheck, Shield, UserRound } from 'lucide-react';

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

type SmtpTestState = 'idle' | 'testing' | 'success' | 'error';

interface SmtpOption {
  value: string;
  label: string;
}

interface SenderSettingsWorkspaceProps {
  smtpProvider: string;
  smtpProviderOptions: SmtpOption[];
  senderEmail: string;
  senderName: string;
  smtpPassword: string;
  smtpHost: string;
  smtpPort: number;
  effectiveSmtpSecurity: 'ssl' | 'starttls' | 'plain';
  selectedSmtpPreset: {
    label: string;
    authHint: string;
  } | null;
  isTestingSmtp: boolean;
  smtpTestState: SmtpTestState;
  smtpTestElapsedSec: number;
  smtpTestMessage: string;
  onSmtpProviderChange: (value: string) => void;
  onSenderEmailChange: (value: string) => void;
  onSenderNameChange: (value: string) => void;
  onSmtpPasswordChange: (value: string) => void;
  onSmtpHostChange: (value: string) => void;
  onSmtpPortChange: (value: number) => void;
  onTestSmtp: () => void;
}

function toSmtpTestAlertType(state: SmtpTestState): 'info' | 'success' | 'error' {
  if (state === 'success') return 'success';
  if (state === 'error') return 'error';
  return 'info';
}

function SenderSettingsWorkspaceInner({
  smtpProvider,
  smtpProviderOptions,
  senderEmail,
  senderName,
  smtpPassword,
  smtpHost,
  smtpPort,
  effectiveSmtpSecurity,
  selectedSmtpPreset,
  isTestingSmtp,
  smtpTestState,
  smtpTestElapsedSec,
  smtpTestMessage,
  onSmtpProviderChange,
  onSenderEmailChange,
  onSenderNameChange,
  onSmtpPasswordChange,
  onSmtpHostChange,
  onSmtpPortChange,
  onTestSmtp,
}: SenderSettingsWorkspaceProps) {
  const { message } = App.useApp();

  const handlePortChange = (value: number | null) => {
    if (value === null) {
      onSmtpPortChange(0);
      return;
    }
    if (value < 1 || value > 65535) {
      message.warning('端口范围应为 1-65535');
      return;
    }
    onSmtpPortChange(Math.trunc(value));
  };

  return (
    <div className="sender-workbench">
      <div className="sender-grid">
        <UiCard className="sender-identity-card py-0">
          <UiCardHeader className="px-6 pt-6 pb-4">
            <div className="flex flex-wrap items-center gap-2">
              <UiBadge variant="secondary" className="bg-slate-100 text-slate-700">
                <UserRound className="size-3.5" />
                发件身份
              </UiBadge>
            </div>
            <UiCardTitle className="text-xl text-slate-900">发件人信息</UiCardTitle>
            <UiCardDescription>用于 SMTP 登录和收件方显示。</UiCardDescription>
          </UiCardHeader>
          <UiCardContent className="space-y-4 px-6 pb-6">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">邮箱类型</label>
              <Select
                value={smtpProvider}
                options={smtpProviderOptions}
                onChange={(value) => onSmtpProviderChange(String(value))}
                style={{ width: '100%' }}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">发件邮箱</label>
              <UiInput
                type="email"
                name="sender_email"
                value={senderEmail}
                onChange={(event) => onSenderEmailChange(event.target.value)}
                placeholder="example@163.com"
                autoComplete="email"
                spellCheck={false}
                className="h-11 border-slate-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">授权码</label>
              <UiInput
                type="password"
                name="smtp_password"
                value={smtpPassword}
                onChange={(event) => onSmtpPasswordChange(event.target.value)}
                placeholder={selectedSmtpPreset ? `${selectedSmtpPreset.label}需要授权码登录 SMTP` : '授权码（无密码可留空）'}
                autoComplete="current-password"
                className="h-11 border-slate-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">发件人姓名</label>
              <UiInput
                name="sender_name"
                value={senderName}
                onChange={(event) => onSenderNameChange(event.target.value)}
                placeholder="收件方显示的发送人名称"
                autoComplete="name"
                className="h-11 border-slate-200 bg-white"
              />
            </div>
          </UiCardContent>
        </UiCard>

        <UiCard className="sender-smtp-card py-0">
          <UiCardHeader className="px-6 pt-6 pb-4">
            <div className="flex flex-wrap items-center gap-2">
              <UiBadge variant="secondary" className="bg-slate-100 text-slate-700">
                <Shield className="size-3.5" />
                SMTP 设置
              </UiBadge>
              <Tag color="blue">{effectiveSmtpSecurity.toUpperCase()} · 端口 {smtpPort}</Tag>
            </div>
            <UiCardTitle className="text-xl text-slate-900">连接与测试</UiCardTitle>
            <UiCardDescription>建议先测试连接再发送。</UiCardDescription>
          </UiCardHeader>
          <UiCardContent className="space-y-4 px-6 pb-6">
            {selectedSmtpPreset ? (
              <Alert type="info" showIcon message={selectedSmtpPreset.authHint} />
            ) : (
              <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700">SMTP Host</label>
                  <UiInput
                    name="smtp_host"
                    value={smtpHost}
                    onChange={(event) => onSmtpHostChange(event.target.value)}
                    placeholder="例如 smtp.example.com"
                    autoComplete="off"
                    spellCheck={false}
                    className="h-10 border-slate-200"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700">端口</label>
                  <InputNumber
                    value={smtpPort > 0 ? smtpPort : null}
                    onChange={handlePortChange}
                    min={1}
                    max={65535}
                    placeholder="例如 465"
                    style={{ width: '100%' }}
                  />
                </div>
                <Alert type="info" showIcon message="SSL：端口 465；STARTTLS：端口 587" />
              </div>
            )}

            <div className="mt-2 flex flex-wrap items-center gap-3">
              <UiButton
                type="button"
                variant="outline"
                className="h-10 min-w-34 border-sky-200 bg-sky-50 text-sky-700 hover:bg-sky-100 hover:text-sky-800 shadow-sm"
                disabled={isTestingSmtp}
                onClick={onTestSmtp}
              >
                {isTestingSmtp ? <LoadingOutlined /> : <MailCheck className="size-4" />}
                测试连接
              </UiButton>
              <UiBadge variant="outline" className="border-slate-300 bg-white text-slate-700">
                <KeyRound className="size-3.5" />
                授权码不会明文显示
              </UiBadge>
            </div>

            {smtpTestState !== 'idle' && (
              <Alert
                showIcon
                icon={smtpTestState === 'testing' ? <LoadingOutlined spin /> : undefined}
                type={toSmtpTestAlertType(smtpTestState)}
                message={
                  smtpTestState === 'testing'
                    ? `正在测试 SMTP 连接（${smtpTestElapsedSec.toFixed(1)}s）`
                    : smtpTestMessage
                }
              />
            )}
          </UiCardContent>
        </UiCard>
      </div>
    </div>
  );
}

export const SenderSettingsWorkspace = memo(SenderSettingsWorkspaceInner);
