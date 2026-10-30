<script setup lang="ts">
import { computed, ref } from 'vue';
import { ElMessage } from 'element-plus';
import type { EvalCandidate, FeedbackSummary } from '@/types/api';
import { formatTime } from '../composables/batch';

/**
 * CandidatePool —— 候选题池（套餐 §5）。
 *
 * 数据来源是对话页的 👎 反馈：用户点踩即把该问题送进池子（source=feedback）。
 * 本页只做「纳入实验 / 忽略」两个决定，不提供新增入口 —— 规格明确要求
 * 「反馈入口不在本页，本页只消费」。
 */
const props = defineProps<{
  candidates: EvalCandidate[];
  summary: FeedbackSummary | null;
  loading?: boolean;
  error?: string | null;
  busyId?: string | null;
}>();

const emit = defineEmits<{
  decide: [string, 'accepted' | 'ignored'];
  refresh: [];
}>();

/** 只看待定：已处理的历史放进折叠区，主列表保持干净 */
const showAll = ref(false);

const pending = computed(() => props.candidates.filter((c) => c.status === 'pending'));
const decided = computed(() => props.candidates.filter((c) => c.status !== 'pending'));
const visible = computed(() => (showAll.value ? props.candidates : pending.value));

const acceptedCount = computed(() => props.candidates.filter((c) => c.status === 'accepted').length);
const ignoredCount = computed(() => props.candidates.filter((c) => c.status === 'ignored').length);

function onDecide(id: string, status: 'accepted' | 'ignored'): void {
  emit('decide', id, status);
}

function onRefresh(): void {
  ElMessage.info('已刷新候选池');
  emit('refresh');
}
</script>

<template>
  <section class="pool" data-testid="candidate-pool">
    <header class="pool__head">
      <div>
        <h2 class="pool__title">候选题池</h2>
        <p class="pool__desc">对话页点「👎」的问题会进入这里，确认后纳入实验问题集。</p>
      </div>
      <div class="pool__actions">
        <el-button size="small" data-testid="pool-refresh" @click="onRefresh">刷新</el-button>
        <el-button
          size="small"
          text
          data-testid="pool-toggle-all"
          @click="showAll = !showAll"
        >
          {{ showAll ? '只看待定' : `查看全部（${candidates.length}）` }}
        </el-button>
      </div>
    </header>

    <div class="pool__stats">
      <span class="pool__stat" data-testid="pool-stat-pending">
        待定 <strong>{{ pending.length }}</strong>
      </span>
      <span class="pool__stat" data-testid="pool-stat-accepted">
        已纳入 <strong>{{ acceptedCount }}</strong>
      </span>
      <span class="pool__stat" data-testid="pool-stat-ignored">
        已忽略 <strong>{{ ignoredCount }}</strong>
      </span>
      <span v-if="summary" class="pool__stat pool__stat--muted" data-testid="pool-stat-feedback">
        反馈总量 {{ summary.total }}（👍 {{ summary.up }} / 👎 {{ summary.down }}）
      </span>
    </div>

    <div v-if="loading" class="pool__state" data-testid="pool-loading">正在加载候选…</div>
    <div v-else-if="error" class="pool__state pool__state--error" data-testid="pool-error">
      {{ error }}
    </div>
    <div v-else-if="visible.length === 0" class="pool__state" data-testid="pool-empty">
      还没有候选题。在对话页对回答点「👎」，问题会自动进池。
    </div>

    <ul v-else class="pool__list">
      <li
        v-for="item in visible"
        :key="item.id"
        class="pool__item"
        :class="`pool__item--${item.status}`"
        :data-testid="`candidate-${item.id}`"
      >
        <div class="pool__item-main">
          <p class="pool__question">{{ item.question }}</p>
          <div class="pool__meta">
            <span class="badge badge--muted">{{ item.source === 'feedback' ? '来自反馈' : '手动添加' }}</span>
            <span
              class="badge"
              :class="
                item.status === 'pending'
                  ? 'badge--warn'
                  : item.status === 'accepted'
                    ? 'badge--ok'
                    : 'badge--muted'
              "
              :data-testid="`candidate-status-${item.id}`"
            >
              {{ item.status === 'pending' ? '待定' : item.status === 'accepted' ? '已纳入' : '已忽略' }}
            </span>
            <span class="pool__time">{{ formatTime(item.createdAt) }}</span>
          </div>
        </div>
        <div class="pool__item-actions">
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="item.status !== 'pending' || busyId === item.id"
            :data-testid="`candidate-accept-${item.id}`"
            @click="onDecide(item.id, 'accepted')"
          >
            纳入实验
          </el-button>
          <el-button
            size="small"
            text
            :disabled="item.status !== 'pending' || busyId === item.id"
            :data-testid="`candidate-ignore-${item.id}`"
            @click="onDecide(item.id, 'ignored')"
          >
            忽略
          </el-button>
        </div>
      </li>
    </ul>

    <p v-if="!showAll && decided.length > 0" class="pool__foot">
      已处理 {{ decided.length }} 条，点「查看全部」可回看。
    </p>
  </section>
</template>

<style scoped>
.pool {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.pool__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.pool__title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
}

.pool__desc {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.pool__actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.pool__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding: 10px 14px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}

.pool__stat {
  font-size: 12px;
  color: var(--muted);
}

.pool__stat strong {
  font-size: 15px;
  color: var(--ink);
  margin-left: 2px;
}

.pool__stat--muted {
  color: var(--muted);
}

.pool__state {
  padding: 32px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  background: var(--paper);
  border: 1px dashed var(--line);
  border-radius: var(--radius);
}

.pool__state--error {
  color: var(--red);
  border-color: color-mix(in srgb, var(--red) 30%, var(--line));
}

.pool__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.pool__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}

.pool__item--pending {
  border-left: 3px solid var(--amber);
}

.pool__item--accepted {
  border-left: 3px solid var(--teal);
}

.pool__item--ignored {
  opacity: 0.65;
  border-left: 3px solid var(--line);
}

.pool__item-main {
  min-width: 0;
  flex: 1;
}

.pool__question {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
  word-break: break-word;
}

.pool__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--muted);
}

.pool__time {
  font-family: var(--font-mono);
}

.pool__item-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.pool__foot {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}
</style>
