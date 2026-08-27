/**
 * Typed access to the Backstop API.
 *
 * Every call returns a discriminated result rather than throwing. A console that
 * reports on system health must render something useful when the system it is
 * reporting on is down - an unhandled fetch rejection is the one failure mode
 * this page cannot afford.
 */

const API_BASE = process.env.BACKSTOP_API_URL ?? 'http://localhost:8000'

export type Result<T> =
  | { ok: true; data: T; endpoint: string }
  | { ok: false; error: string; endpoint: string }

async function request<T>(
  path: string,
  init?: { method?: string; body?: unknown; timeoutMs?: number },
): Promise<Result<T>> {
  const endpoint = `${API_BASE}${path}`
  try {
    const response = await fetch(endpoint, {
      method: init?.method ?? 'GET',
      cache: 'no-store',
      headers: init?.body ? { 'content-type': 'application/json' } : undefined,
      body: init?.body ? JSON.stringify(init.body) : undefined,
      // Submitting a ticket runs the whole graph, including model calls, so it
      // needs a far longer budget than a health probe.
      signal: AbortSignal.timeout(init?.timeoutMs ?? 15_000),
    })

    // A 503 from /health/ready is a meaningful answer, not a transport failure:
    // it carries the per-dependency detail we want to render.
    if (!response.ok && response.status !== 503) {
      const detail = await response.text().catch(() => '')
      return { ok: false, error: `HTTP ${response.status} ${detail}`.trim(), endpoint }
    }

    return { ok: true, data: (await response.json()) as T, endpoint }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'unknown transport error'
    return { ok: false, error: message, endpoint }
  }
}

// -- health ------------------------------------------------------------------

export interface ReadinessPayload {
  ready: boolean
  dependencies: { database: boolean; redis: boolean }
}

export interface GovernancePayload {
  environment: string
  kill_switch_engaged: boolean
  max_auto_refund_eur: number
  daily_budget_usd: number
  pii_detokenize_channels: string[]
}

export const getReadiness = () => request<ReadinessPayload>('/health/ready')
export const getGovernance = () => request<GovernancePayload>('/health/governance')

// -- tickets -----------------------------------------------------------------

export interface TicketSummary {
  ticket_id: string
  channel: string
  status: string
  received_at: string
  intent: string | null
  order_id: string | null
  amount_eur: string | null
  awaiting_approval: boolean
  deliberated: boolean
  cost_usd: string
  guardrail_flags: number
  preview: string
}

export interface GuardrailEvent {
  detector: string
  severity: string
  action: string
  summary: string
  span: number[] | null
  detail: Record<string, unknown>
}

export interface AuditEntry {
  sequence: number
  at: string
  principal: string
  tool: string
  outcome: string
  refusal_code: string | null
  duration_ms: number | null
}

export interface PolicyRuling {
  rule_id: string
  effect: string
  reason: string
  clauses: string[]
  ambiguous: boolean
}

export interface TicketDetail {
  ticket_id: string
  status: string
  channel: string
  raw_message: string | null
  safe_message: string | null
  intent: string | null
  order_id: string | null
  customer_id: string | null
  guardrail_events: GuardrailEvent[]
  policy_refs: { clause_id: string; section_title: string; text: string; score: number }[]
  assessment: Record<string, unknown> | null
  policy_decision: {
    effect: string
    explanation: string
    clauses: string[]
    needs_deliberation: boolean
    rulings: PolicyRuling[]
  } | null
  deliberation: Record<string, unknown> | null
  approval_request: Record<string, unknown> | null
  approval: Record<string, unknown> | null
  execution: Record<string, unknown> | null
  reply: string | null
  fact_gaps: string[]
  model_calls: Record<string, string>[]
  cost_usd: string
  failure: string | null
  audit: AuditEntry[]
  pii_placeholders: string[]
}

export const listTickets = () =>
  request<{ count: number; awaiting_approval: number; tickets: TicketSummary[] }>('/tickets')

export const getTicket = (id: string) => request<TicketDetail>(`/tickets/${id}`)

export const submitTicket = (message: string, channel = 'email') =>
  request<TicketDetail>('/tickets', {
    method: 'POST',
    body: { message, channel },
    timeoutMs: 120_000,
  })

// -- approvals ---------------------------------------------------------------

export interface ApprovalItem {
  ticket_id: string
  received_at: string
  preview: string
  request: {
    proposed_resolution: string | null
    amount_eur: string | null
    rationale: string | null
    concerns: string[]
    policy_effect: string | null
    policy_explanation: string | null
    clauses: string[]
    deliberation: Record<string, unknown> | null
  }
}

export const listApprovals = () =>
  request<{ count: number; approvals: ApprovalItem[] }>('/approvals')

export const decideApproval = (
  ticketId: string,
  approved: boolean,
  approver: string,
  reason = '',
) =>
  request<TicketDetail>(`/approvals/${ticketId}`, {
    method: 'POST',
    body: { approved, approver, reason },
    timeoutMs: 120_000,
  })

// -- attack lab --------------------------------------------------------------

export interface LabResult {
  action: string
  severity: string
  blocked: boolean
  would_reach_a_model: boolean
  original_length: number
  normalised_length: number
  safe_message: string
  pii_placeholders: string[]
  events: GuardrailEvent[]
  prompt_block: string
}

export const scanText = (message: string) =>
  request<LabResult>('/lab/scan', { method: 'POST', body: { message }, timeoutMs: 20_000 })

// -- governance --------------------------------------------------------------

export interface GovernanceOverview {
  controls: {
    environment: string
    kill_switch_engaged: boolean
    auto_approve_ceiling_eur: number
    daily_budget_usd: number
    pii_detokenize_channels: string[]
  }
  spend: {
    total_usd: string
    by_task: Record<string, string>
    budget_usd: string | null
    remaining_usd: string | null
    circuit_breaker_tripped: boolean
  }
  tickets: {
    total: number
    by_status: Record<string, number>
    awaiting_approval: number
    deliberated: number
  }
  capability_use: {
    entries: number
    by_outcome: Record<string, number>
    refusals: Record<string, number>
    top_tools: Record<string, number>
  }
  audit_chain: { verified: boolean; problem: string | null; head: string }
}

export const getOverview = () => request<GovernanceOverview>('/governance/overview')

export const getPrompts = () =>
  request<{
    prompts: {
      reference: string
      owner: string
      changelog: string
      hash: string
    }[]
  }>('/governance/prompts')
