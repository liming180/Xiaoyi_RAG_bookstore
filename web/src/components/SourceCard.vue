<script setup>
import { computed, ref, watch } from 'vue';
import { highlightSegments, scoreWidth } from '../utils/text.js';
import { state } from '../store.js';

const props = defineProps({
  card: { type: Object, required: true },
  index: { type: Number, default: 0 },
  question: { type: String, default: '' },
});

const root = ref(null);
const open = ref(false);
const flash = ref(false);

const segments = computed(() => highlightSegments(props.card.excerpt || '', props.question));
const width = computed(() => scoreWidth(props.card.score));
const scoreText = computed(() => Number(props.card.score || 0).toFixed(4));
const position = computed(() => `第 ${props.card.start + 1}–${props.card.end} 字`);

/* 点击回答里的编号时（store.focusCard 写入 flashChunkId）滚动定位并高亮 1.4 秒 */
watch(
  () => state.flashChunkId,
  (chunkId) => {
    if (!chunkId || chunkId !== props.card.chunk_id) return;
    open.value = true;
    flash.value = true;
    if (root.value && root.value.scrollIntoView) {
      root.value.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setTimeout(() => { flash.value = false; }, 1400);
  },
);
</script>

<template>
  <div
    :id="`card-${card.chunk_id}`"
    ref="root"
    class="card"
    :class="{ unverified: !card.verified, flash }"
  >
    <div class="card-head">
      <span class="idx">[{{ index + 1 }}]</span>
      <span class="mono">{{ card.chunk_id }}</span>
      <span class="src">{{ card.source }}</span>
      <span v-if="!card.verified" class="badge warn">未核实</span>
      <span class="score-bar"><i :style="{ width }" /></span>
      <span class="num">{{ scoreText }}</span>
      <span class="mono">{{ position }}</span>
    </div>
    <div class="card-excerpt">
      <template v-for="(seg, i) in segments" :key="i">
        <mark v-if="seg.hit">{{ seg.text }}</mark>
        <template v-else>{{ seg.text }}</template>
      </template>
    </div>
    <details :open="open" @toggle="open = $event.target.open">
      <summary>查看片段原文</summary>
      <pre>{{ card.text }}</pre>
    </details>
  </div>
</template>
