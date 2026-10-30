<script setup lang="ts">
import type { Citation } from '@/types/api';
import type { Inline } from '@/utils/markdown';
import SourceRef from './SourceRef.vue';

/**
 * InlineRenderer —— 把 parseInline 的 token 数组渲染成节点。
 *
 * 关键：全程使用模板绑定，没有任何 v-html。
 * 检索资料里夹带的 `<img onerror=...>` 会被 Vue 当作文本转义输出，不会执行。
 */
defineProps<{
  inlines: Inline[];
  citations: Citation[];
}>();

const emit = defineEmits<{ cite: [Citation] }>();
</script>

<template>
  <template v-for="(node, i) in inlines" :key="i">
    <strong v-if="node.type === 'bold'">{{ node.value }}</strong>
    <a
      v-else-if="node.type === 'link'"
      :href="node.href"
      target="_blank"
      rel="noopener noreferrer"
      >{{ node.value }}</a
    >
    <SourceRef
      v-else-if="node.type === 'cite'"
      :cite-ref="node.ref"
      :chunk-id="node.chunkId"
      :citations="citations"
      @select="emit('cite', $event)"
    />
    <template v-else>{{ node.value }}</template>
  </template>
</template>
