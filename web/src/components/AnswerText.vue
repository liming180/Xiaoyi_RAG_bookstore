<script setup>
import { computed } from 'vue';
import { answerNodes } from '../utils/text.js';
import { actions } from '../store.js';

const props = defineProps({
  text: { type: String, default: '' },
  citations: { type: Array, default: () => [] },
});

const nodes = computed(() => answerNodes(props.text, props.citations));

function focus(chunkId) {
  actions.focusCard(chunkId);
}
</script>

<template>
  <!-- 有效编号渲染成可点击徽标；无效编号作为普通文本输出，界面不造假来源 -->
  <template v-for="(node, index) in nodes" :key="index">
    <span
      v-if="node.type === 'cite'"
      class="cite"
      :data-chunk="node.chunk_id"
      @click="focus(node.chunk_id)"
    >{{ node.raw }}</span>
    <template v-else>{{ node.value }}</template>
  </template>
</template>
