<script setup>
import { computed } from 'vue';
import AnswerText from './AnswerText.vue';
import SourceCard from './SourceCard.vue';

const props = defineProps({
  payload: { type: Object, required: true },
  question: { type: String, default: '' },
});

const isBoth = computed(() => props.payload.mode === 'both');

const ragSide = computed(() => (isBoth.value ? props.payload.rag || {} : props.payload));
const directSide = computed(() => (isBoth.value ? props.payload.direct || {} : null));

/** 底部诚实提示，逐项与旧版 renderAnswer 对齐，用「 · 」连接 */
const honesty = computed(() => {
  const bits = [`耗时 ${props.payload.elapsed_ms} ms`];
  if (!isBoth.value && props.payload.mode === 'rag' && !props.payload.used_knowledge_base) {
    bits.push('本轮没有取回任何片段');
  }
  const removed = props.payload.removed_citations || [];
  if (removed.length) bits.push(`已剔除无效编号 ${removed.join('、')}`);
  bits.push('引用只表示取回来源，仍需核对原文');
  return bits.join(' · ');
});
</script>

<template>
  <div v-if="isBoth" class="answer-grid">
    <div>
      <div class="col-head">
        查资料 <span class="badge">已引用知识库</span>
      </div>
      <div class="bubble assistant answer-col">
        <AnswerText :text="ragSide.answer || ''" :citations="ragSide.citations || []" />
      </div>
      <div class="cards mt8">
        <SourceCard
          v-for="(card, index) in ragSide.citations || []"
          :key="card.chunk_id"
          :card="card"
          :index="index"
          :question="question"
        />
      </div>
    </div>
    <div>
      <div class="col-head">
        不查资料 <span class="badge ghost">未引用知识库资料</span>
      </div>
      <div class="bubble assistant answer-col">{{ directSide.answer || '' }}</div>
    </div>
  </div>

  <div v-else>
    <AnswerText :text="payload.answer || ''" :citations="payload.citations || []" />
    <div class="cards mt8">
      <SourceCard
        v-for="(card, index) in payload.citations || []"
        :key="card.chunk_id"
        :card="card"
        :index="index"
        :question="question"
      />
    </div>
  </div>

  <div class="honesty">{{ honesty }}</div>
</template>
