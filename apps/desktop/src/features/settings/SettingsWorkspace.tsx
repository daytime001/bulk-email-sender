import { memo } from 'react';
import { Alert } from 'antd';
import { FolderCog, FolderOpen, RefreshCw, RotateCcw, ShieldCheck, Wrench } from 'lucide-react';

import type { AppPaths, RuntimeStatus } from '@/types';
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

interface SettingsWorkspaceProps {
  runtimeStatus: RuntimeStatus | null;
  runtimePath: string;
  runtimeBusy: boolean;
  dataDirInput: string;
  dataPathBusy: boolean;
  dataPaths: AppPaths | null;
  onResetDraft: () => void;
  onPickPythonBinary: () => void;
  onAutoDetectRuntime: () => void;
  onRefreshRuntimeStatus: () => void;
  onClearRuntime: () => void;
  onDataDirInputChange: (value: string) => void;
  onPickDataDir: () => void;
  onApplyDataDir: () => void;
  onResetDataDir: () => void;
  onOpenDataDir: () => void;
  onOpenReadableRecord: () => void;
  onOpenDraftConfig: () => void;
}

function SettingsWorkspaceInner({
  runtimeStatus,
  runtimePath,
  runtimeBusy,
  dataDirInput,
  dataPathBusy,
  dataPaths,
  onResetDraft,
  onPickPythonBinary,
  onAutoDetectRuntime,
  onRefreshRuntimeStatus,
  onClearRuntime,
  onDataDirInputChange,
  onPickDataDir,
  onApplyDataDir,
  onResetDataDir,
  onOpenDataDir,
  onOpenReadableRecord,
  onOpenDraftConfig,
}: SettingsWorkspaceProps) {
  const runtimeReady = runtimeStatus?.ready ?? false;
  const runtimeBadgeClass = runtimeReady
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-amber-200 bg-amber-50 text-amber-700';
  const runtimeBadgeText = runtimeReady
    ? `就绪 · ${runtimeStatus?.version ?? runtimeStatus?.source ?? 'Python'}`
    : '未配置';

  return (
    <div className="settings-workbench">
      <div className="settings-layout">
        <div className="settings-left-column">
          <UiCard className="settings-runtime-card py-0 h-full">
            <UiCardHeader className="px-6 pt-6 pb-4">
              <div className="flex flex-wrap items-center gap-2">
                <UiBadge variant="secondary" className="bg-teal-100 text-teal-700">
                  <ShieldCheck className="size-3.5" />
                  Python 运行时
                </UiBadge>
                <UiBadge variant="outline" className={runtimeBadgeClass}>
                  {runtimeBadgeText}
                </UiBadge>
              </div>
              <UiCardTitle className="text-xl text-slate-900">运行环境</UiCardTitle>
              <UiCardDescription>建议先确认运行时状态，再进行邮件发送。</UiCardDescription>
            </UiCardHeader>
            <UiCardContent className="settings-runtime-content space-y-4 px-6 pb-6">
              {runtimeStatus && (
                <Alert
                  type={runtimeReady ? 'success' : 'warning'}
                  showIcon
                  message={runtimeReady ? 'Python 运行时已就绪' : '需要先配置 Python 运行时'}
                  description={`来源：${runtimeStatus.source}${runtimeStatus.version ? ` ｜ ${runtimeStatus.version}` : ''} ｜ ${runtimeStatus.message}`}
                />
              )}

              <UiInput
                name="runtime_path"
                value={runtimePath}
                readOnly
                placeholder="尚未配置，请选择文件或点击自动安装"
                className="h-11 border-slate-200 bg-white"
              />

              <div className="settings-runtime-actions">
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-10"
                  disabled={runtimeBusy}
                  onClick={onPickPythonBinary}
                >
                  <Wrench className="size-4" />
                  选择 Python 文件
                </UiButton>
                <UiButton
                  type="button"
                  className="h-10 border border-teal-300 bg-teal-100 text-teal-800 hover:bg-teal-200"
                  disabled={runtimeBusy}
                  onClick={onAutoDetectRuntime}
                >
                  自动安装 Python（推荐）
                </UiButton>
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-10"
                  disabled={runtimeBusy}
                  onClick={onRefreshRuntimeStatus}
                >
                  <RefreshCw className="size-4" />
                  刷新检测
                </UiButton>
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-10 border-rose-200 text-rose-600 hover:bg-rose-50"
                  disabled={runtimeBusy}
                  onClick={onClearRuntime}
                >
                  清除配置
                </UiButton>
              </div>

              <div className="settings-draft-reset">
                <div className="settings-draft-reset-text">
                  <p className="settings-draft-reset-title">重置邮件草稿</p>
                  <p className="settings-draft-reset-desc">
                    仅重置发件人、主题、正文和附件，不影响 Python 运行时安装。
                  </p>
                </div>
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-10 border-amber-300 text-amber-700 hover:bg-amber-50"
                  onClick={onResetDraft}
                >
                  <RotateCcw className="size-4" />
                  重置邮件草稿
                </UiButton>
              </div>
            </UiCardContent>
          </UiCard>
        </div>

        <div className="settings-right-column">
          <UiCard className="settings-storage-card py-0 h-full">
            <UiCardHeader className="px-6 pt-6 pb-4">
              <div className="flex flex-wrap items-center gap-2">
                <UiBadge variant="secondary" className="bg-sky-100 text-sky-700">
                  <FolderCog className="size-3.5" />
                  记录与配置
                </UiBadge>
                <UiBadge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700">
                  本地持久化
                </UiBadge>
              </div>
              <UiCardTitle className="text-xl text-slate-900">数据目录</UiCardTitle>
              <UiCardDescription>可自定义发送记录、日志与草稿配置的保存位置。</UiCardDescription>
            </UiCardHeader>
            <UiCardContent className="space-y-4 px-6 pb-6">
              <div className="flex flex-col gap-3 md:flex-row">
                <UiInput
                  name="data_dir"
                  value={dataDirInput}
                  onChange={(event) => onDataDirInputChange(event.target.value)}
                  placeholder="选择记录与配置保存目录"
                  className="h-11 flex-1 border-slate-200 bg-white"
                  autoComplete="off"
                  spellCheck={false}
                />
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-11"
                  disabled={dataPathBusy}
                  onClick={onPickDataDir}
                >
                  <FolderOpen className="size-4" />
                  选择目录
                </UiButton>
              </div>

              <div className="settings-storage-actions-main">
                <UiButton
                  type="button"
                  className="h-10 border border-sky-300 bg-sky-100 text-sky-800 hover:bg-sky-200"
                  disabled={dataPathBusy}
                  onClick={onApplyDataDir}
                >
                  保存目录
                </UiButton>
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-10"
                  disabled={dataPathBusy}
                  onClick={onResetDataDir}
                >
                  恢复默认目录
                </UiButton>
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-10"
                  disabled={!dataPaths}
                  onClick={onOpenDataDir}
                >
                  打开数据目录
                </UiButton>
              </div>
              <div className="settings-storage-actions-files">
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-10"
                  disabled={!dataPaths}
                  onClick={onOpenReadableRecord}
                >
                  打开发送记录（txt）
                </UiButton>
                <UiButton
                  type="button"
                  variant="outline"
                  className="h-10"
                  disabled={!dataPaths}
                  onClick={onOpenDraftConfig}
                >
                  打开配置文件
                </UiButton>
              </div>

              {dataPaths && (
                <Alert
                  type="info"
                  showIcon
                  message="配置与记录路径"
                  description={
                    <>
                      <div><code>{dataPaths.data_dir}</code></div>
                      <div><code>{dataPaths.sent_store_text_file}</code></div>
                      <div><code>{dataPaths.sent_store_file}</code></div>
                      <div><code>{dataPaths.app_draft_file}</code></div>
                    </>
                  }
                />
              )}
            </UiCardContent>
          </UiCard>
        </div>
      </div>
    </div>
  );
}

export const SettingsWorkspace = memo(SettingsWorkspaceInner);
