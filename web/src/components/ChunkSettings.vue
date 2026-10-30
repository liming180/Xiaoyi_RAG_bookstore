<script setup>
import { computed, ref, watch } from 'vue';
import { actions, fail, indexHint, state } from '../store.js';
import { usePolling } from '../composables/usePolling.js';
import { toast } from '../composables/useToast.js';

const size = ref(180);
const overlap = ref(30);
const building = ref(false);

watch(
  () => state.status,
  (status) => {
    if (!status) return;
    size.value = status.chunk_size;
    overlap.value = status.chunk_overlap;
  },
  { immediate: true },
);

const hint = computed(() => indexHint(state.status));

/* 表3 第②项：把片段长度改成 120 后，界面就要提示「需要重新建库」，
 * 而不是等用户点按钮才由后端比对 manifest 才发现。
 * 判定条件：输入框的值与当前索引实际使用的分块参数不一致。 */
const dirty = computed(() => {
  const status = state.status;
  if (!status || !status.ready) return null;
  const sizeChanged = Number(size.value) !== Number(status.chunk_size);
  const overlapChanged = Number(overlap.value) !== Number(status.chunk_overlap);
  if (!sizeChanged && !overlapChanged) return null;
  return `分块设置已改为 ${size.value}/${overlap.value}，与当前索引的 ${status.chunk_size}/${status.chunk_overlap} 不同，需要重新建库。`;
});

const poller = usePolling(async () => {
  const running = await actions.pollIndex();
  if (!running) {
    building.value = false;
    const status = state.status || {};
    if (status.ready) toast(`建库成功，文档 ${status.doc_count} 份，片段 ${status.chunks} 条。`);
  }
  return running;
}, 300);

async function build() {
  building.value = true;
  try {
    await actions.buildIndex(size.value, overlap.value);
    poller.start();
  } catch (err) {
    building.value = false;
    fail(err);
  }
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2>分块设置</h2>
    </div>

    <div class="field">
      <label for="chunkSize">片段长度</label>
      <input id="chunkSize" v-model.number="size" type="number" min="50" max="1000" step="10">
    </div>
    <div class="field">
      <label for="chunkOverlap">重叠字数</label>
      <input id="chunkOverlap" v-model.number="overlap" type="number" min="0" max="999" step="5">
    </div>

    <button class="btn primary block mt8" :disabled="building" @click="build">
      {{ building ? '正在建库…' : '重新建库' }}
    </button>

    <div class="progress mt8">
      <i :style="{ width: hint.bar }" />
    </div>
    <p class="hint">{{ hint.text }}</p>
    <p v-if="dirty" class="hint warn-text">{{ dirty }}</p>
  </section>
</template>
