<script setup>
import AnswerBlock from './AnswerBlock.vue';

defineProps({
  turn: { type: Object, required: true },
});
</script>

<template>
  <!-- 资料全文气泡（点击侧栏文件名时插入，对应旧版 openDoc） -->
  <div v-if="turn.kind === 'doc'" class="turn">
    <div class="bubble assistant">
      <div class="who">资料原文 · {{ turn.name }} · {{ turn.chars }} 字</div>
      <pre class="mono" style="white-space:pre-wrap;margin:0">{{ turn.text }}</pre>
    </div>
  </div>

  <!-- 问答气泡 -->
  <div v-else class="turn">
    <div class="bubble user">{{ turn.question }}</div>
    <div v-if="turn.status === 'pending'" class="bubble assistant pending">正在回答…</div>
    <div v-else-if="turn.status === 'fail'" class="bubble assistant">
      <span class="fail">{{ turn.error }}</span>
    </div>
    <div v-else class="bubble assistant">
      <AnswerBlock :payload="turn.payload" :question="turn.question" />
    </div>
  </div>
</template>
