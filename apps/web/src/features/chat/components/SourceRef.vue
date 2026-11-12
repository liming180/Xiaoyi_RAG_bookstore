<script setup lang="ts">
import { computed } from 'vue';
import type { Citation } from '@/types/api';
import { citeLabel, resolveCitation } from '@/utils/text';

/**
 * SourceRef —— 回答正文里的引用徽标（F05）。
 *
 * - 有效引用：实心可点，点击上抛 select，由父层打开引用卡
 * - 幻觉引用（文本有、citations 里没有）：灰色 + disabled，不可点
 *
 * 注意：prop 名不能叫 `ref` —— 那是 Vue 的保留属性（模板 ref / 虚拟节点 key）。
 * 这里用 citeRef。
 */
const props = defineProps<{
  citeRef: number | string;
  chunkId: string | null;
  citations: Citation[];
}>();

const emit = defineEmits<{ select: [Citation] }>();

const hit = computed<Citation | null>(() =>
  resolveCitation(props.citations, props.citeRef, props.chunkId),
);

const label = computed(() => citeLabel(props.citeRef, props.chunkId));

const title = computed(() => {
  if (!hit.value) return '该编号在本次回答的引用列表中不存在（可能为模型编造），不可点击';
  return `${hit.value.docTitle}${hit.value.headingPath ? ' · ' + hit.value.headingPath : ''}`;
});

function onClick(): void {
  if (hit.value) emit('select', hit.value);
}
</script>

<template>
  <button
    type="button"
    class="source-ref"
    :class="hit ? 'source-ref--valid' : 'source-ref--ghost'"
    :disabled="!hit"
    :title="title"
    :data-testid="hit ? 'cite-badge' : 'cite-badge-ghost'"
    :data-ref="String(citeRef)"
    @click="onClick"
  >
    {{ label }}
  </button>
</template>

<style scoped>
.source-ref {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  margin: 0 1px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  border-radius: 6px;
  border: 1px solid transparent;
  vertical-align: baseline;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}

.source-ref--valid {
  color: var(--teal);
  background: var(--soft);
  border-color: color-mix(in srgb, var(--teal) 24%, transparent);
}

.source-ref--valid:hover {
  color: var(--paper);
  background: var(--teal);
}

.source-ref--ghost {
  color: var(--muted);
  background: transparent;
  border-color: var(--line);
  border-style: dashed;
  cursor: not-allowed;
  text-decoration: line-through;
}
</style>
