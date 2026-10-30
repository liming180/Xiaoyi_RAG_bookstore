<script setup lang="ts">
import { computed } from 'vue';
import type { Experiment, ExperimentAxis, ExperimentRun } from '@/types/api';
import { CHUNK_SIZE_DEFAULT, K_DEFAULT, OVERLAP_DEFAULT } from '@/constants/app';
import { downloadCsv, csvTimestamp, toCsv } from '@/utils/csv';
import { ElMessage } from 'element-plus';
import {
  experimentCsvRows,
  experimentPercent,
  formatElapsed,
  formatRate,
  isBestRun,
  paramsLabel,
} from '../composables/experiment';

/**
 * ExperimentMatrix —— 参数矩阵配置 + 对比表（套餐 E3）。
 *
 * 配置区用「勾选取值」而不是自由输入：矩阵实验的本质是穷举离散组合，
 * 自由输入会让人写出 180/170 这种把 overlap 逼近 chunkSize 的退化组，
 * 勾选固定候选值（180/300/500 等）能保证每组都有实际意义。
 */
const props = defineProps<{
  axes: ExperimentAxis;
  name: string;
  groupCount: number;
  experiment: Experiment | null;
  runs: ExperimentRun[];
  best: ExperimentRun | null;
  creating: boolean;
  polling: boolean;
  progress: number;
  error?: string | null;
  conflict?: string | null;
  isRunning: boolean;
  isDone: boolean;
}>();

const emit = defineEmits<{
  'update:name': [string];
  toggle: [keyof ExperimentAxis, number | boolean];
  create: [];
  reset: [];
}>();

const CHUNK_OPTIONS = [CHUNK_SIZE_DEFAULT, 300, 500];
const OVERLAP_OPTIONS = [OVERLAP_DEFAULT, 50, 100];
const K_OPTIONS = [K_DEFAULT, 4, 5];
const FLAG_OPTIONS = [
  { key: 'rerank' as const, label: '重排' },
  { key: 'summary' as const, label: '摘要' },
];

function has(key: keyof ExperimentAxis, value: number | boolean): boolean {
  return (props.axes[key] as Array<number | boolean>).includes(value);
}

function onToggle(key: keyof ExperimentAxis, value: number | boolean): void {
  emit('toggle', key, value);
}

const percent = computed(() => experimentPercent(props.progress));
const totalGroups = computed(() => props.experiment?.totalGroups ?? props.groupCount);
const finishedGroups = computed(() => props.experiment?.finishedGroups ?? 0);

const sortedRuns = computed(() => [...props.runs]);

function exportCsv(): void {
  if (props.runs.length === 0) {
    ElMessage.warning('还没有实验结果可导出');
    return;
  }
  downloadCsv(
    `参数实验-${csvTimestamp()}.csv`,
    toCsv(experimentCsvRows(props.runs, props.best)),
  );
  ElMessage.success('已导出对比表');
}

/** 最优行的参数，展示成「推荐参数：180/30 · k=3」 */
const bestLabel = computed(() => (props.best ? paramsLabel(props.best.params) : '—'));
</script>

<template>
  <section class="exp" data-testid="experiment-matrix">
    <!-- 配置区 -->
    <div class="exp__config" data-testid="exp-config">
      <div class="exp__row">
        <label class="exp__field">
          <span class="exp__label">实验名称</span>
          <el-input
            :model-value="name"
            size="small"
            data-testid="exp-name"
            @update:model-value="(v: string) => emit('update:name', v)"
          />
        </label>
      </div>

      <div class="exp__row exp__row--wrap">
        <div class="exp__field">
          <span class="exp__label">片段长度 chunk_size</span>
          <div class="exp__checks">
            <el-checkbox
              v-for="v in CHUNK_OPTIONS"
              :key="v"
              :model-value="has('chunkSize', v)"
              :data-testid="`axis-chunkSize-${v}`"
              @update:model-value="onToggle('chunkSize', v)"
            >
              {{ v }}
            </el-checkbox>
          </div>
        </div>

        <div class="exp__field">
          <span class="exp__label">重叠 overlap</span>
          <div class="exp__checks">
            <el-checkbox
              v-for="v in OVERLAP_OPTIONS"
              :key="v"
              :model-value="has('overlap', v)"
              :data-testid="`axis-overlap-${v}`"
              @update:model-value="onToggle('overlap', v)"
            >
              {{ v }}
            </el-checkbox>
          </div>
        </div>

        <div class="exp__field">
          <span class="exp__label">取回数量 k</span>
          <div class="exp__checks">
            <el-checkbox
              v-for="v in K_OPTIONS"
              :key="v"
              :model-value="has('k', v)"
              :data-testid="`axis-k-${v}`"
              @update:model-value="onToggle('k', v)"
            >
              {{ v }}
            </el-checkbox>
          </div>
        </div>

        <div class="exp__field">
          <span class="exp__label">开关</span>
          <div class="exp__checks">
            <el-checkbox
              v-for="opt in FLAG_OPTIONS"
              :key="opt.key"
              :model-value="has(opt.key, true)"
              :data-testid="`axis-${opt.key}`"
              @update:model-value="onToggle(opt.key, true)"
            >
              {{ opt.label }}
            </el-checkbox>
          </div>
        </div>
      </div>

      <div class="exp__row exp__row--actions">
        <span class="exp__count" data-testid="exp-group-count">
          共 <strong>{{ groupCount }}</strong> 组参数
          <span v-if="groupCount === 0" class="exp__count-warn">（矩阵为空，无法创建）</span>
        </span>
        <div class="exp__buttons">
          <el-button
            type="primary"
            size="small"
            :loading="creating"
            :disabled="creating || isRunning || groupCount === 0"
            data-testid="exp-create"
            @click="emit('create')"
          >
            {{ isRunning ? '实验进行中…' : '创建实验' }}
          </el-button>
          <el-button size="small" data-testid="exp-reset" @click="emit('reset')">清空结果</el-button>
        </div>
      </div>

      <p v-if="conflict" class="exp__conflict" data-testid="exp-conflict">{{ conflict }}</p>
      <p v-if="error" class="exp__error" data-testid="exp-error">{{ error }}</p>
    </div>

    <!-- 进度 -->
    <div v-if="experiment" class="exp__progress" data-testid="exp-progress">
      <div class="exp__progress-head">
        <span class="exp__progress-title">
          {{ experiment.name }}
          <code class="exp__progress-id">{{ experiment.id }}</code>
        </span>
        <span class="exp__progress-meta" data-testid="exp-progress-meta">
          {{ finishedGroups }} / {{ totalGroups }} 组 · {{ percent }}%
        </span>
      </div>
      <el-progress
        :percentage="percent"
        :status="isDone ? 'success' : undefined"
        :stroke-width="8"
        data-testid="exp-progress-bar"
      />
      <p v-if="isRunning" class="exp__notice" data-testid="exp-running-notice">
        实验串行执行中，期间提问将返回 409（互斥保护），完成后自动恢复。
      </p>
    </div>

    <!-- 对比表 -->
    <div v-if="runs.length > 0" class="exp__compare" data-testid="exp-compare">
      <div class="exp__compare-head">
        <h3 class="exp__compare-title">参数对比</h3>
        <div class="exp__compare-actions">
          <span class="exp__best" data-testid="exp-best">推荐参数：{{ bestLabel }}</span>
          <el-button size="small" data-testid="exp-export" @click="exportCsv">导出 CSV</el-button>
        </div>
      </div>

      <table class="exp__table">
        <thead>
          <tr>
            <th class="exp__col-idx">#</th>
            <th>参数组</th>
            <th class="exp__col-num">命中率</th>
            <th class="exp__col-num">平均耗时</th>
            <th class="exp__col-num">来源数</th>
            <th class="exp__col-num">失败</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(run, i) in sortedRuns"
            :key="run.id"
            :data-testid="`exp-row-${run.id}`"
            :class="{ 'exp__row--best': isBestRun(run, best) }"
            :data-best="isBestRun(run, best) ? 'true' : 'false'"
          >
            <td class="exp__col-idx">
              <span v-if="isBestRun(run, best)" class="exp__crown" title="最优组">★</span>
              <span v-else>{{ i + 1 }}</span>
            </td>
            <td>
              <span class="exp__params">{{ paramsLabel(run.params) }}</span>
            </td>
            <td class="exp__col-num exp__col-rate">{{ formatRate(run.metrics.hitRate) }}</td>
            <td class="exp__col-num">{{ formatElapsed(run.metrics.avgElapsedMs) }}</td>
            <td class="exp__col-num">{{ run.metrics.avgSources }}</td>
            <td class="exp__col-num">{{ run.metrics.failed }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else-if="!experiment" class="exp__empty" data-testid="exp-empty">
      勾选参数取值后点「创建实验」，跑完会在这里给出每组参数的命中率对比与推荐参数。
    </div>
  </section>
</template>

<style scoped>
.exp {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.exp__config {
  padding: 14px 16px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.exp__row {
  display: flex;
  gap: 16px;
  align-items: center;
}

.exp__row--wrap {
  flex-wrap: wrap;
}

.exp__row--actions {
  justify-content: space-between;
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.exp__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.exp__label {
  font-size: 12px;
  color: var(--muted);
}

.exp__checks {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.exp__count {
  font-size: 12px;
  color: var(--muted);
}

.exp__count strong {
  font-size: 15px;
  color: var(--ink);
}

.exp__count-warn {
  color: var(--red);
}

.exp__buttons {
  display: flex;
  gap: 8px;
}

.exp__conflict {
  margin: 0;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--amber);
  background: var(--amber-soft);
  border-radius: var(--radius-sm);
}

.exp__error {
  margin: 0;
  font-size: 12px;
  color: var(--red);
}

.exp__progress {
  padding: 14px 16px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.exp__progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.exp__progress-title {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.exp__progress-id {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--muted);
  font-weight: 400;
}

.exp__progress-meta {
  font-size: 12px;
  color: var(--muted);
  font-family: var(--font-mono);
}

.exp__notice {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--amber);
}

.exp__compare {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

.exp__compare-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

.exp__compare-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.exp__compare-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.exp__best {
  font-size: 12px;
  color: var(--teal-dark);
  font-family: var(--font-mono);
}

.exp__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.exp__table th {
  padding: 8px 12px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

.exp__table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}

.exp__table tbody tr:last-child td {
  border-bottom: 0;
}

.exp__row--best {
  background: color-mix(in srgb, var(--teal) 9%, transparent);
}

.exp__row--best td {
  font-weight: 600;
}

.exp__col-idx {
  width: 44px;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.exp__col-num {
  width: 92px;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12px;
}

.exp__col-rate {
  color: var(--teal-dark);
}

.exp__crown {
  color: var(--amber);
}

.exp__params {
  font-family: var(--font-mono);
  font-size: 12px;
}

.exp__empty {
  padding: 32px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  background: var(--paper);
  border: 1px dashed var(--line);
  border-radius: var(--radius);
}
</style>
