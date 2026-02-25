export type WorkerEvent =
  | { type: 'job_accepted'; job_id: string }
  | { type: 'job_started'; job_id: string; total: number }
  | { type: 'recipient_started'; job_id: string; index: number; email: string; name: string }
  | { type: 'recipient_sent'; job_id: string; index: number; email: string; name: string }
  | { type: 'recipient_failed'; job_id: string; index: number; email: string; name: string; error: string }
  | { type: 'recipient_skipped'; job_id: string; index: number; email: string; name: string; reason: string }
  | { type: 'job_finished'; job_id: string; success: number; failed: number; skipped: number; total: number; failures: Array<{ email: string; name: string; error: string }> }
  | { type: 'job_cancelled'; job_id: string; success: number; failed: number; skipped: number; total: number }
  | { type: 'cancel_requested' }
  | { type: 'smtp_test_succeeded' }
  | { type: 'recipients_loaded'; stats: RecipientStats; recipients_preview: Recipient[] }
  | { type: 'error'; error: string };

export interface Recipient {
  email: string;
  name: string;
}

export interface RecipientStats {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  empty_rows: number;
}

export interface LoadRecipientsResult {
  stats: RecipientStats;
  recipientsPreview: Recipient[];
}

export interface SmtpPayload {
  host: string;
  port: number;
  username: string;
  password: string;
  use_ssl: boolean;
  use_starttls: boolean;
  timeout_sec: number;
}

export interface SendPayload {
  job_id?: string;
  sender: {
    email: string;
    name: string;
  };
  smtp: SmtpPayload;
  template: {
    subject: string;
    body_text: string;
    body_html?: string;
  };
  recipients: Recipient[];
  attachments: string[];
  options: {
    min_delay_sec: number;
    max_delay_sec: number;
    randomize_order: boolean;
    retry_count: number;
    add_teacher_suffix: boolean;
    skip_sent: boolean;
  };
  paths: {
    log_file: string;
    sent_store_file: string;
  };
}

export interface RuntimeStatus {
  ready: boolean;
  source: string;
  executable_path?: string | null;
  version?: string | null;
  message: string;
}
