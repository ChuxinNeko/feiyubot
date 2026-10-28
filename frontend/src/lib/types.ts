export type Provider = {
  id: string
  name: string
  base_url: string
  api_key_mask: string
  has_api_key: boolean
  model: string
  enabled: boolean
  priority: number
  timeout_seconds: number
  ok: boolean | null
  last_error: string
}

export type Persona = {
  id: string
  name: string
  prompt: string
  is_active: boolean
}

export type ChatMessage = {
  id: number
  role: string
  content: string
  sender_name: string | null
  notice: boolean
}

export type SessionSummary = {
  id: string
  kind: string
  title: string
  group_id: string | null
  persona_id: string | null
  wake_mode: string | null
  enabled: boolean
  summary: string
  memory_notes: string
  knowledge: string
  message_count: number
  updated_at: string
}

export type SessionDetail = SessionSummary & {
  messages: ChatMessage[]
}

export type Settings = {
  wake_mode: string
  wake_words: string[]
  keep_recent: number
  compress_after: number
  context_token_budget: number
  temperature: number
  max_tokens: number
  memory_update_every: number
  memory_enabled: boolean
  request_timeout: number
  max_retries: number
  min_interval_seconds: number
  group_whitelist: string[]
  group_blacklist: string[]
  bot_name: string
  knowledge: string
  disabled_extensions: string[]
}

export type OneBotStatus = {
  connected: { id: string; adapter: string }[]
  reverse_ws_path: string
  http_path: string
  token_configured: boolean
  saved_token_configured: boolean
  saved_ws_urls: string
  restart_required: boolean
}

export type Status = {
  bot_name: string
  message_count: number
  session_count: number
  active_persona: { id: string; name: string } | null
  providers: { id: string; name: string; enabled: boolean; ok: boolean | null; last_error: string }[]
  onebot: OneBotStatus
  password_is_default: boolean
}

export type ExtensionInfo = {
  name: string
  doc: string
  enabled: boolean
}

export type ProbeResult = {
  ok: boolean
  reply?: string
  error?: string
  latency_ms: number
}
