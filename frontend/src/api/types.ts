// Response types for API endpoints whose OpenAPI schema has no response model.
// Keep these in step with the backend handlers named in each comment.

/** GET /system/status (app/api/system.py). A 503 returns the health subset in ApiError.details. */
export interface SystemStatus {
  status: string
  services: Record<string, string>
  storage?: StorageDrive[]
  jobs?: Record<string, number>
  models?: { name: string; cached: boolean }[]
  errors?: { stage: string; reason: string; time: string }[]
  backup?: BackupStatus
  timezone?: string
  limits?: { image: number; pdf: number; pages: number }
}

/** One storage drive. The full status has ok/free/total bytes; the health subset has status. */
export interface StorageDrive {
  name: string
  message: string
  warning: boolean
  ok?: boolean
  status?: string
  free_bytes?: number | null
  total_bytes?: number | null
}

export interface BackupStatus {
  state: string
  last_success: string | null
  last_error: string | null
  warning: boolean
  same_filesystem_as_originals: boolean | null
}

/** GET/PUT /system/backup-settings */
export interface BackupSettings {
  enabled: boolean
  hour: number
  minute: number
  daily_keep: number
  weekly_keep: number
}

/** GET /system/backups */
export interface BackupRecord {
  id: string
  state: string
  trigger: string
  path: string
  bytes: number
  started_at: string | null
  finished_at: string | null
  error: string | null
  created_at: string
}

/** GET /accuracy (app/api/accuracy.py) */
export interface AccuracyReport {
  examples: {
    document_id: string
    title: string
    matches: Record<string, boolean> | null
    model: string | null
    input_revision: number | null
  }[]
  correct_field_groups: number
  measured_field_groups: number
  exact_match_percent: number | null
  policy: string
}

/** GET /settings/agent-tokens */
export interface AgentToken {
  id: string
  name: string
  scopes: string[]
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

/** GET /settings/agent-activity */
export interface AgentActivity {
  id: string
  token_id: string | null
  tool: string
  arguments_summary: Record<string, unknown>
  status: string
  created_at: string
}

/** GET /documents/{id}/progress (app/api/processing.py) */
export interface ProcessingStep {
  step: string
  state: string
  reason: string | null
}
export interface DocumentProgress {
  state: string
  steps: ProcessingStep[]
  review_reasons: string[]
}

/** GET /documents/{id}/permanent-removal (app/domain/trash.py) */
export interface RemovalPreview {
  document_id: string
  files: number
  bytes: number
  blocked_file_ids: string[]
  can_remove: boolean
}

/** Dashboard provider row (app/domain/dashboard.py) */
export interface DashboardProvider {
  provider: string
  state: string
  enabled: boolean
  connected: boolean
  processing_allowed: boolean
  spent: string
  spending_cap: string
}

/** Phone queue report (QueueReport record) */
export interface PhoneQueueReport {
  id: string
  client_uuid: string
  device_label: string
  files: number
  notes: number
  bytes: number
  updated_at: string
}

/** GET /exports (public Export record) */
export interface ExportRecord {
  id: string
  state: string
  format: string
  counts: Record<string, number>
  error: string | null
  expires_at: string | null
  created_at: string
}

/** POST /exports/preview */
export interface ExportPreview {
  counts: Record<string, number>
  rows: Record<string, Record<string, string>[]>
  fields: Record<string, string[]>
  warning?: string
}

/** GET /companies (company record plus contact names) */
export interface CompanySummary {
  id: string
  display_name: string
  description: string
  business_role: string
  products: string[]
  services: string[]
  channels: { kind: string; label: string; raw: string }[]
  people: string[]
}

/** GET /contacts (contact record, company name and review status) */
export interface ContactRow {
  id: string
  company_id: string
  company_name: string
  source_document_id: string | null
  full_name: string
  designation: string
  department: string
  channels: { kind: string; label: string; raw: string }[]
  review_status: string
  pending_changes: number
  review_warning: string
}
