<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  CHUNK_SIZE_DEFAULT,
  CHUNK_SIZE_MAX,
  CHUNK_SIZE_MIN,
  OVERLAP_DEFAULT,
} from '@/constants/app';
import type { IndexTask } from '@/types/api';
import {
  formatBuildSummary,
  isParamsDirty,
  progressPercent,
  stageLabel,
  validateBuildParams,
} from '../composables/buildParams';

/**
 * BuildPanel —— 建库设置与进度（F02）。
 *
 * 参数默认 180 / 30（功能规格 F02 与项目实际建库口径一致）。
 * 校验 0 ≤ overlap < size，不合法直接禁用按钮并给出原因。
 */
const props = defineProps<{
  builtParams?: { chunkSize: number; overlap: number } | null;
  task?: IndexTask | null;
  running?: boolean;
  error?: string | null;
}>();

const emit = defineEmits<{
  rebuild: [{ chunkSize: number; overlap: number }];
}>();

const chunkSize = ref(props.builtParams?.chunkSize ?? CHUNK_SIZE_DEFAULT);
const overlap = ref(props.builtParams?.overlap ?? OVERLAP_DEFAULT);

// 外部状态（页面拉回来的 index/status）变化时同步到输入框，避免「显示旧值」
watch(
  () => props.builtParams,
  (next) => {
    if (!next) return;
    chunkSize.value = next.chunkSize;
    overlap.value = next.overlap;
  },
);

const params = computed(() => ({
  chunkSize: Number(chunkSize.value),
  overlap: Number(overlap.value),
}));

const validationError = computed(() => validateBuildParams(params.value));
const dirty = computed(() => isParamsDirty(params.value, props.builtParams ?? null));
const canRebuild = computed(() => !validationError.value && !props.running);

const percent = computed(() => progressPercent(props.task ?? null));
const stage = computed(() => stageLabel(props.task ?? null));
const summary = computed(() => formatBuildSummary(props.task ?? null));
const showProgress = computed(() => Boolean(props.task) && props.task?.status !== 'PENDING');

function onRebuild(): void {
  if (!canRebuild.value) return;
  emit('rebuild', params.value);
}
</script>

<template>
  <section class="build card" data-testid="build-panel">
    <header class="build__head">
      <h2 class="build__title">建库设置</h2>
      <span v-if="dirty" class="badge badge--warn" data-testid="build-dirty">参数已改动</span>
    </header>

    <div class="build__fields">
      <label class="build__field">
        <span class="build__label">片段长度</span>
        <el-input-number
          v-model="chunkSize"
          :min="CHUNK_SIZE_MIN"
          :max="CHUNK_SIZE_MAX"
          :step="10"
          :disabled="running"
          size="small"
          controls-position="right"
          data-testid="chunk-size-input"
        />
        <span class="build__unit">字（{{ CHUNK_SIZE_MIN }}–{{ CHUNK_SIZE_MAX }}）</span>
      </label>

      <label class="build__field">
        <span class="build__label">重叠字数</span>
        <el-input-number
          v-model="overlap"
          :min="0"
          :max="CHUNK_SIZE_MAX"
          :step="5"
          :disabled="running"
          size="small"
          controls-position="right"
          data-testid="overlap-input"
        />
        <span class="build__unit">字（须小于片段长度）</span>
      </label>
    </div>

    <p v-if="validationError" class="build__invalid" data-testid="build-invalid">
      {{ validationError }}
    </p>

    <p v-else-if="dirty" class="build__dirty-hint" data-testid="build-dirty-hint">
      参数已改动，重新建库后新设置才会生效。
    </p>

    <div class="build__actions">
      <el-button
        type="primary"
        size="small"
        :disabled="!canRebuild"
        :loading="running"
        data-testid="build-submit"
        @click="onRebuild"
      >
        重新建库
      </el-button>
      <span v-if="builtParams" class="build__current" data-testid="build-current">
        当前库：{{ builtParams.chunkSize }} / {{ builtParams.overlap }}
      </span>
    </div>

    <div v-if="showProgress" class="build__progress" data-testid="build-progress">
      <el-progress
        :percentage="percent"
        :status="task?.status === 'FAILED' ? 'exception' : undefined"
        :stroke-width="8"
      />
      <div class="build__progress-meta">
        <span data-testid="build-stage">{{ stage }}</span>
        <span v-if="task?.status === 'RUNNING'" class="build__count"
          >片段 {{ task?.chunkCount ?? 0 }} 条</span
        >
        <span v-else-if="summary" class="build__summary" data-testid="build-summary">{{
          summary
        }}</span>
      </div>
      <p v-if="task?.error" class="build__error" data-testid="build-error">{{ task.error }}</p>
    </div>

    <p v-if="error" class="build__error" data-testid="build-request-error">{{ error }}</p>
  </section>
</template>

<style scoped>
.build {
  padding: 14px 16px;
}

.build__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.build__title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.build__fields {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.build__field {
  display: flex;
  align-items: center;
  gap: 6px;
}

.build__label {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}

.build__unit {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.build__invalid {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--red);
}

.build__dirty-hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--amber);
}

.build__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.build__current {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--muted);
}

.build__progress {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.build__progress-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}

.build__count,
.build__summary {
  font-family: var(--font-mono);
}

.build__error {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--red);
}
</style>
