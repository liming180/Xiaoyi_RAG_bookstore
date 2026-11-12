<script setup lang="ts">
import { computed } from 'vue';
import type { ChunkItem } from '@/types/api';
import { positionText } from '@/utils/text';
import { headingLabel, splitHighlight } from '../composables/chunkFilter';

/**
 * ChunkCard —— 单条片段卡（P4-B）。
 *
 * 展示：片段 ID / 所属章节 / 起止位置 / 正文（关键词高亮）/ 未核实标记。
 * 命中定位（?chunk_id=）时挂 chunk-card--focused 做高亮描边。
 */
const props = defineProps<{
  chunk: ChunkItem;
  /** 关键词，用于正文高亮 */
  keyword?: string;
  /** 是否为当前定位片段 */
  focused?: boolean;
}>();

const emit = defineEmits<{
  focus: [ChunkItem];
  copy: [ChunkItem];
}>();

const slices = computed(() => splitHighlight(props.chunk.text, props.keyword ?? ''));
const heading = computed(() => headingLabel(props.chunk.headingPath));
const range = computed(() => positionText(props.chunk.start, props.chunk.end));

const KIND_LABEL: Record<string, string> = {
  chunk: '正文片段',
  summary: '全局汇总',
  rule: '规则条目',
};

const kindLabel = computed(() => KIND_LABEL[props.chunk.kind] ?? props.chunk.kind);
</script>

<template>
  <article
    class="chunk-card"
    :class="{ 'chunk-card--focused': focused }"
    :data-testid="`chunk-card-${chunk.chunkId}`"
    :data-focused="focused ? 'true' : 'false'"
  >
    <header class="chunk-card__head">
      <code class="chunk-card__id" data-testid="chunk-id">{{ chunk.chunkId }}</code>
      <span class="chunk-card__kind" data-testid="chunk-kind">{{ kindLabel }}</span>
      <span class="chunk-card__range" data-testid="chunk-range">{{ range }}</span>
      <span v-if="!chunk.verified" class="badge badge--warn chunk-card__unverified">未核实</span>
      <div class="chunk-card__ops">
        <el-button
          size="small"
          text
          :data-testid="`chunk-focus-${chunk.chunkId}`"
          @click="emit('focus', chunk)"
        >
          观察相邻
        </el-button>
        <el-button
          size="small"
          text
          :data-testid="`chunk-copy-${chunk.chunkId}`"
          @click="emit('copy', chunk)"
        >
          复制
        </el-button>
      </div>
    </header>

    <p class="chunk-card__heading" data-testid="chunk-heading">{{ heading }}</p>

    <p class="chunk-card__text" data-testid="chunk-text">
      <template v-for="(slice, i) in slices" :key="i">
        <mark v-if="slice.hit" class="chunk-card__hit">{{ slice.text }}</mark>
        <span v-else>{{ slice.text }}</span>
      </template>
    </p>

    <footer class="chunk-card__foot">
      <span class="chunk-card__doc">{{ chunk.docTitle }}</span>
      <span class="chunk-card__len">{{ chunk.text.length }} 字</span>
    </footer>
  </article>
</template>

<style scoped>
.chunk-card {
  padding: 10px 12px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}

.chunk-card--focused {
  border-color: var(--teal);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--teal) 22%, transparent);
}

.chunk-card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.chunk-card__id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--teal-dark);
}

.chunk-card__kind,
.chunk-card__range {
  font-size: 11px;
  color: var(--muted);
}

.chunk-card__unverified {
  transform: translateY(-1px);
}

.chunk-card__ops {
  margin-left: auto;
  display: flex;
  gap: 2px;
}

.chunk-card__heading {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--muted);
}

.chunk-card__text {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.chunk-card__hit {
  padding: 0 1px;
  color: var(--ink);
  background: var(--amber-soft);
  border-radius: 2px;
}

.chunk-card__foot {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 11px;
  color: var(--muted);
}

.chunk-card__doc {
  font-family: var(--font-mono);
}

.chunk-card__len {
  font-family: var(--font-mono);
}
</style>
