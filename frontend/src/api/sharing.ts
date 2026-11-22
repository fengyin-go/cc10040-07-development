/** 受控共享接口封装：共享授权、授权实验汇总、实验评估与成员名单保护。 */
import { request } from './client'

export type SharingGrant = {
  id: number
  cohort_id: number
  cohort_name: string
  owner_team: string
  owner: string
  recipient_team: string
  scope: string
  status: string
  granted_at: string
  revoked_at: string | null
  revoked_by: string | null
  revoke_reason: string | null
  summary_id: number
}

export type ExperimentSummary = {
  id: number
  grant_id: number
  cohort_id: number
  cohort_name: string
  recipient_team: string
  headcount: number
  data_scope: string
  status: string
  generated_at: string
  invalidated_at: string | null
}

export type EvaluationGroup = {
  group_role: string
  cohort_name: string
  grant_id: number
  summary_id: number
  confirmed: boolean
  confirmed_headcount: number | null
  confirmed_at: string | null
  grant_status?: string
}

export type SummaryRange = {
  group_role: string
  cohort_name: string
  grant_id: number
  summary_id: number
  headcount: number
  confirmed_at: string | null
  grant_valid_now: boolean
}

export type EligibilityReport = {
  evaluation_id: number
  experiment_name: string
  status: string
  eligible_to_generate: boolean
  can_start_new_round: boolean
  boundary_grant_ids: number[]
  groups: EvaluationGroup[]
  control_treatment_ratio: number | null
  confirmed_summary_ranges: SummaryRange[]
  block_reasons: string[]
  events: { time: string; event: string; detail: string }[]
}

export type SharingSnapshot = {
  grant_count: number
  active_grants: number
  revoked_grants: number
  summary_count: number
  evaluation_count: number
  blocked_evaluations: number
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = (payload as { detail?: string }).detail ?? '请求失败'
    throw new Error(detail)
  }
  return payload as T
}

export function getSnapshot(): Promise<SharingSnapshot> {
  return send('/api/sharing/snapshot')
}

export function listGrants(): Promise<{ items: SharingGrant[]; total: number }> {
  return send('/api/sharing/grants')
}

export function createGrant(input: {
  cohort_id: number
  recipient_team: string
  owner: string
  scope?: string
}): Promise<{ grant: SharingGrant; summary: ExperimentSummary }> {
  return send('/api/sharing/grants', { method: 'POST', body: JSON.stringify(input) })
}

export function revokeGrant(
  grantId: number,
  input: { revoked_by: string; reason?: string },
): Promise<{ grant: SharingGrant; summary: ExperimentSummary; affected_evaluation_ids: number[] }> {
  return send(`/api/sharing/grants/${grantId}/revoke`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function listSummaries(
  recipientTeam?: string,
): Promise<{ items: ExperimentSummary[]; total: number }> {
  const query = recipientTeam ? `?recipient_team=${encodeURIComponent(recipientTeam)}` : ''
  return send(`/api/sharing/summaries${query}`)
}

export function listEvaluations(): Promise<{ items: EligibilityReport[]; total: number }> {
  return send('/api/sharing/evaluations')
}

export function createEvaluation(input: {
  experiment_name: string
  control_grant_id: number
  treatment_grant_id: number
  analyst: string
}): Promise<EligibilityReport> {
  return send('/api/sharing/evaluations', { method: 'POST', body: JSON.stringify(input) })
}

export function confirmGroup(
  evaluationId: number,
  groupRole: 'control' | 'treatment',
): Promise<EligibilityReport> {
  return send(`/api/sharing/evaluations/${evaluationId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ group_role: groupRole }),
  })
}

export function getEligibility(evaluationId: number): Promise<EligibilityReport> {
  return send(`/api/sharing/evaluations/${evaluationId}/eligibility`)
}

export function requestMemberRoster(
  cohortId: number,
  requestingTeam: string,
): Promise<{ ok: boolean; status: number; message: string; memberCount?: number; preview?: unknown[] }> {
  return request(`/api/sharing/cohorts/${cohortId}/member-roster`, {
    method: 'POST',
    body: JSON.stringify({ requesting_team: requestingTeam }),
  }).then(async (response) => {
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) {
      return { ok: false, status: response.status, message: payload.detail ?? '请求被拒绝' }
    }
    return {
      ok: true,
      status: response.status,
      message: payload.note ?? '读取成功',
      memberCount: payload.member_count,
      preview: (payload.members ?? []).slice(0, 3),
    }
  })
}
