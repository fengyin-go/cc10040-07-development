<template>
  <section class="page sharing-page">
    <header class="page-head">
      <div>
        <h2>受控共享</h2>
        <p class="page-desc">
          分群团队以授权实验汇总的形式共享成员数据：接收团队只能查看获准的群组人数，
          个人资料与成员明细始终留在分群团队；撤回后过期权限不得复用。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reloadAll">刷新数据</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">有效授权</span>
        <strong class="stat-value">{{ snapshot.active_grants }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已撤回授权</span>
        <strong class="stat-value">{{ snapshot.revoked_grants }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">授权实验汇总</span>
        <strong class="stat-value">{{ snapshot.summary_count }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">失去资格评估</span>
        <strong class="stat-value">{{ snapshot.blocked_evaluations }}</strong>
      </article>
    </div>

    <!-- 1. 共享授权 -->
    <section class="panel">
      <h3>① 共享授权与授权实验汇总</h3>
      <form class="analysis-form" @submit.prevent="submitGrant">
        <label>
          用户分群
          <select v-model.number="grantForm.cohort_id" data-testid="grant-cohort">
            <option v-for="cohort in cohortOptions" :key="cohort.id" :value="cohort.id">
              {{ cohort.name }}（成员 {{ cohort.headcount }} 人）
            </option>
          </select>
        </label>
        <label>接收团队<input v-model="grantForm.recipient_team" data-testid="grant-team" required /></label>
        <label>分群负责人<input v-model="grantForm.owner" data-testid="grant-owner" required /></label>
        <button class="btn primary" type="submit" data-testid="grant-submit">授权并生成汇总</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th><th>分群</th><th>接收团队</th><th>负责人</th>
            <th>共享范围</th><th>授权状态</th><th>授权时间</th><th>撤回信息</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="grant in grants" :key="grant.id" :data-testid="`grant-row-${grant.id}`">
            <td>{{ grant.id }}</td>
            <td>{{ grant.cohort_name }}</td>
            <td>{{ grant.recipient_team }}</td>
            <td>{{ grant.owner }}</td>
            <td>{{ grant.scope }}</td>
            <td><span class="badge" :class="grant.status === '有效' ? 'badge-ok' : 'badge-off'">{{ grant.status }}</span></td>
            <td>{{ grant.granted_at }}</td>
            <td>
              <template v-if="grant.revoked_at">
                {{ grant.revoked_by }} · {{ grant.revoked_at }}<br />
                <small>{{ grant.revoke_reason }}</small>
              </template>
              <span v-else>—</span>
            </td>
            <td>
              <button
                v-if="grant.status === '有效'"
                class="link danger"
                type="button"
                :data-testid="`grant-revoke-${grant.id}`"
                @click="submitRevoke(grant)"
              >
                撤回共享
              </button>
              <span v-else class="muted">不可复用</span>
            </td>
          </tr>
          <tr v-if="!grants.length">
            <td colspan="9" class="empty-state">暂无共享授权</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 2. 接收团队可见的授权实验汇总 -->
    <section class="panel">
      <h3>② 接收团队可见的授权实验汇总（仅群组人数）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>汇总ID</th><th>来源分群</th><th>接收团队</th><th>群组人数</th>
            <th>数据范围</th><th>汇总状态</th><th>生成时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="summary in summaries" :key="summary.id" :data-testid="`summary-row-${summary.id}`">
            <td>{{ summary.id }}</td>
            <td>{{ summary.cohort_name }}</td>
            <td>{{ summary.recipient_team }}</td>
            <td><strong>{{ summary.headcount }}</strong></td>
            <td>{{ summary.data_scope }}</td>
            <td><span class="badge" :class="summary.status === '有效' ? 'badge-ok' : 'badge-off'">{{ summary.status }}</span></td>
            <td>{{ summary.generated_at }}</td>
          </tr>
          <tr v-if="!summaries.length">
            <td colspan="7" class="empty-state">暂无授权实验汇总</td>
          </tr>
        </tbody>
      </table>
      <p class="muted small">汇总由成员明细聚合得到，任何记录都不含 user_id、姓名等个人资料字段。</p>
    </section>

    <!-- 3. 实验评估 -->
    <section class="panel">
      <h3>③ 实验评估：对照组 / 实验组在同一有效授权边界内确认</h3>
      <form class="analysis-form" @submit.prevent="submitEvaluation">
        <label>实验名称<input v-model="evaluationForm.experiment_name" data-testid="eval-name" required /></label>
        <label>
          对照组授权
          <select v-model.number="evaluationForm.control_grant_id" data-testid="eval-control">
            <option v-for="grant in activeGrants" :key="`c-${grant.id}`" :value="grant.id">
              #{{ grant.id }} {{ grant.cohort_name }}
            </option>
          </select>
        </label>
        <label>
          实验组授权
          <select v-model.number="evaluationForm.treatment_grant_id" data-testid="eval-treatment">
            <option v-for="grant in activeGrants" :key="`t-${grant.id}`" :value="grant.id">
              #{{ grant.id }} {{ grant.cohort_name }}
            </option>
          </select>
        </label>
        <label>分析员<input v-model="evaluationForm.analyst" data-testid="eval-analyst" required /></label>
        <button class="btn primary" type="submit" data-testid="eval-submit">发起评估</button>
      </form>

      <div v-for="evaluation in evaluations" :key="evaluation.evaluation_id" class="eval-card"
           :data-testid="`eval-card-${evaluation.evaluation_id}`">
        <div class="eval-head">
          <div>
            <strong>#{{ evaluation.evaluation_id }} {{ evaluation.experiment_name }}</strong>
            <span class="badge" :class="statusClass(evaluation.status)">{{ evaluation.status }}</span>
          </div>
          <div class="muted small">授权边界：[{{ evaluation.boundary_grant_ids.join(', ') }}]</div>
        </div>
        <table class="data-table inner">
          <thead>
            <tr><th>分组</th><th>分群</th><th>授权</th><th>授权状态</th><th>确认人数</th><th>确认时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="group in evaluation.groups" :key="group.group_role">
              <td>{{ roleLabel(group.group_role) }}</td>
              <td>{{ group.cohort_name }}</td>
              <td>#{{ group.grant_id }}</td>
              <td>{{ group.grant_status }}</td>
              <td>{{ group.confirmed_headcount ?? '—' }}</td>
              <td>{{ group.confirmed_at ?? '—' }}</td>
              <td>
                <button
                  v-if="!group.confirmed && evaluation.status !== '失去资格'"
                  class="link"
                  type="button"
                  :data-testid="`confirm-${evaluation.evaluation_id}-${group.group_role}`"
                  @click="submitConfirm(evaluation.evaluation_id, group.group_role)"
                >
                  确认汇总范围
                </button>
                <span v-else class="muted">{{ group.confirmed ? '已确认' : '边界失效' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="eval-meta">
          <p>
            是否有资格生成：
            <strong :class="evaluation.eligible_to_generate ? 'text-ok' : 'text-off'">
              {{ evaluation.eligible_to_generate ? '是' : '否' }}
            </strong>
            ｜ 能否发起新一轮评估：
            <strong :class="evaluation.can_start_new_round ? 'text-ok' : 'text-off'">
              {{ evaluation.can_start_new_round ? '能' : '不能' }}
            </strong>
            ｜ 实验组/对照组比例：
            <strong>{{ evaluation.control_treatment_ratio ?? '—' }}</strong>
          </p>
          <p v-if="evaluation.block_reasons.length" class="text-off small">
            阻断原因：{{ evaluation.block_reasons.join('；') }}
          </p>
          <details class="events">
            <summary>实际获得的汇总范围与边界事件（{{ evaluation.events.length }}）</summary>
            <ul>
              <li v-for="(event, index) in timeline(evaluation)" :key="index">
                <small>{{ event.time }} ｜ {{ event.event }} ｜ {{ event.detail }}</small>
              </li>
            </ul>
          </details>
        </div>
      </div>
      <p v-if="!evaluations.length" class="empty-state">暂无实验评估</p>
    </section>

    <!-- 4. 成员名单保护验证 -->
    <section class="panel">
      <h3>④ 成员名单保护验证</h3>
      <form class="analysis-form" @submit.prevent="submitRosterRequest">
        <label>
          分群
          <select v-model.number="rosterForm.cohort_id" data-testid="roster-cohort">
            <option v-for="cohort in cohortOptions" :key="cohort.id" :value="cohort.id">
              {{ cohort.name }}
            </option>
          </select>
        </label>
        <label>
          请求团队
          <select v-model="rosterForm.requesting_team" data-testid="roster-team">
            <option value="实验团队">实验团队（接收方）</option>
            <option value="分群团队">分群团队（数据所有方）</option>
          </select>
        </label>
        <button class="btn primary" type="submit" data-testid="roster-submit">尝试读取成员名单</button>
      </form>
      <div v-if="rosterResult" class="roster-result" :class="rosterResult.ok ? 'roster-ok' : 'roster-denied'"
           data-testid="roster-result">
        <p>
          HTTP {{ rosterResult.status }} —
          <strong>{{ rosterResult.ok ? '读取成功（仅分群团队）' : '访问被受控共享边界拒绝' }}</strong>
        </p>
        <p class="small">{{ rosterResult.message }}</p>
        <template v-if="rosterResult.ok">
          <p class="small">成员总数：{{ rosterResult.memberCount }}，前 3 条预览：</p>
          <ul class="small">
            <li v-for="member in previewMembers" :key="member.user_id">
              {{ member.user_id }} ｜ {{ member.name }}
            </li>
          </ul>
        </template>
      </div>
    </section>

    <footer class="page-foot">
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else class="muted">所有授权判断在后端领域服务完成，前端只负责展示与发起操作。</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  confirmGroup,
  createEvaluation,
  createGrant,
  getSnapshot,
  listEvaluations,
  listGrants,
  listSummaries,
  requestMemberRoster,
  revokeGrant,
} from '@/api/sharing'
import type {
  EligibilityReport,
  ExperimentSummary,
  SharingGrant,
  SharingSnapshot,
} from '@/api/sharing'

// 演示用分群与后端种子数据（user_cohort id 4/5）保持一致。
const cohortOptions = [
  { id: 4, name: '高价值付费用户群', headcount: 1200 },
  { id: 5, name: '新注册活跃用户群', headcount: 800 },
]

const snapshot = ref<SharingSnapshot>({
  grant_count: 0, active_grants: 0, revoked_grants: 0,
  summary_count: 0, evaluation_count: 0, blocked_evaluations: 0,
})
const grants = ref<SharingGrant[]>([])
const summaries = ref<ExperimentSummary[]>([])
const evaluations = ref<EligibilityReport[]>([])
const errorMessage = ref('')

const grantForm = ref({ cohort_id: 4, recipient_team: '实验团队', owner: '' })
const evaluationForm = ref({
  experiment_name: '',
  control_grant_id: 0,
  treatment_grant_id: 0,
  analyst: '',
})
const rosterForm = ref({ cohort_id: 4, requesting_team: '实验团队' })
const rosterResult = ref<Awaited<ReturnType<typeof requestMemberRoster>> | null>(null)

const activeGrants = computed(() => grants.value.filter((grant) => grant.status === '有效'))

function roleLabel(role: string): string {
  return role === 'control' ? '对照组' : role === 'treatment' ? '实验组' : role
}

function statusClass(status: string): string {
  if (status === '可生成') return 'badge-ok'
  if (status === '失去资格') return 'badge-off'
  return 'badge-pending'
}

type TimelineEvent = { time: string | null; event: string; detail: string }
type MemberPreview = { user_id: string; name: string }

const previewMembers = computed<MemberPreview[]>(() =>
  (rosterResult.value?.preview ?? []) as MemberPreview[],
)

function timeline(evaluation: EligibilityReport): TimelineEvent[] {
  const rangeEvents: TimelineEvent[] = evaluation.confirmed_summary_ranges.map((range) => ({
    time: range.confirmed_at,
    event: '汇总范围留档',
    detail: `${roleLabel(range.group_role)}「${range.cohort_name}」群组人数 ${range.headcount}，`
      + `授权当前${range.grant_valid_now ? '有效' : '失效'}`,
  }))
  return [...rangeEvents, ...evaluation.events]
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    const [snapshotPayload, grantPayload, summaryPayload, evaluationPayload] = await Promise.all([
      getSnapshot(), listGrants(), listSummaries(), listEvaluations(),
    ])
    snapshot.value = snapshotPayload
    grants.value = grantPayload.items
    summaries.value = summaryPayload.items
    evaluations.value = evaluationPayload.items
    if (!evaluationForm.value.control_grant_id && activeGrants.value.length) {
      evaluationForm.value.control_grant_id = activeGrants.value[0].id
      evaluationForm.value.treatment_grant_id = activeGrants.value[Math.min(1, activeGrants.value.length - 1)].id
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '受控共享数据读取失败'
  }
}

async function submitGrant() {
  try {
    await createGrant({ ...grantForm.value })
    grantForm.value.owner = ''
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '授权失败'
  }
}

async function submitRevoke(grant: SharingGrant) {
  try {
    await revokeGrant(grant.id, { revoked_by: grant.owner || '分群负责人', reason: '负责人手动撤回' })
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '撤回失败'
  }
}

async function submitEvaluation() {
  try {
    await createEvaluation({ ...evaluationForm.value })
    evaluationForm.value.experiment_name = ''
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发起评估失败'
  }
}

async function submitConfirm(evaluationId: number, groupRole: string) {
  if (groupRole !== 'control' && groupRole !== 'treatment') return
  try {
    await confirmGroup(evaluationId, groupRole)
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '确认失败'
  }
}

async function submitRosterRequest() {
  try {
    rosterResult.value = await requestMemberRoster(
      rosterForm.value.cohort_id,
      rosterForm.value.requesting_team,
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '成员名单请求失败'
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.sharing-page .panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.sharing-page h3 { margin: 0 0 12px; font-size: 15px; }
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  margin-left: 6px;
}
.badge-ok { background: #dcfae6; color: #067647; }
.badge-off { background: #fee4e2; color: #b42318; }
.badge-pending { background: #fef0c7; color: #b54708; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.link.danger { color: #b42318; }
.text-ok { color: #067647; }
.text-off { color: #b42318; }
.eval-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: #fafbfc;
}
.eval-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.data-table.inner { background: #fff; }
.eval-meta { margin-top: 8px; }
.eval-meta p { margin: 4px 0; }
.events { margin-top: 6px; }
.events ul { margin: 6px 0 0; padding-left: 18px; }
.roster-result { border-radius: 8px; padding: 10px 14px; margin-top: 8px; }
.roster-denied { background: #fee4e2; border: 1px solid #fda29b; }
.roster-ok { background: #dcfae6; border: 1px solid #73dfa3; }
.roster-result ul { margin: 6px 0 0; padding-left: 18px; }
</style>
