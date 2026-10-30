<script setup lang="ts">
import { computed } from 'vue';
import type { Message } from '@/types/api';
import AnswerBody from './AnswerBody.vue';

/**
 * ComparePane —— 对照模式两栏（F06）。
 *
 * 左：查资料（带引用）；右：直接答（无引用，模型自身知识）。
 * 两栏共用同一问题，便于看清「有资料 vs 无资料」的差别。
 */
const props = defineProps<{
  rag: Message | null;
  direct: Message | null;
  ragDraft?: string;
  directDraft?: string;
  ragPending?: boolean;
}>();

const ragText = computed(() => props.ragDraft ?? props.rag?.content ?? '');
const directText = computed(() => props.directDraft ?? props.direct?.content ?? '');
const ragCitations = computed(() => props.rag?.citations ?? []);

const emit = defineEmits<{ cite: [Message['citations'][number]] }>();
</script>

<template>
  <section class="compare" data-testid="compare-pane">
    <div class="compare__col" data-testid="compare-rag">
      <header class="compare__head">
        <span class="compare__title">查资料</span>
        <span class="compare__tag compare__tag--rag">引用知识库</span>
      </header>
      <div class="compare__body">
        <p v-if="ragPending && !ragText" class="compare__pending" aria-busy="true">正在检索…</p>
        <AnswerBody
          v-else-if="ragText"
          :content="ragText"
          :citations="ragCitations"
          @cite="emit('cite', $event)"
        />
        <p v-else class="compare__empty">暂无结果</p>
      </div>
    </div>

    <div class="compare__col" data-testid="compare-direct">
      <header class="compare__head">
        <span class="compare__title">直接答</span>
        <span class="compare__tag compare__tag--direct">不查资料</span>
      </header>
      <div class="compare__body">
        <p v-if="!directText" class="compare__empty">暂无结果</p>
        <p v-else class="compare__plain">{{ directText }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.compare {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin: 0 20px 10px;
}

@media (max-width: 900px) {
  .compare {
    grid-template-columns: 1fr;
  }
}

.compare__col {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.compare__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--sidebar);
}

.compare__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

.compare__tag {
  padding: 1px 7px;
  font-size: 10px;
  border-radius: 999px;
}

.compare__tag--rag {
  color: var(--teal-dark);
  background: var(--soft);
}

.compare__tag--direct {
  color: var(--amber);
  background: var(--amber-soft);
}

.compare__body {
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.7;
  max-height: 320px;
  overflow-y: auto;
}

.compare__pending {
  margin: 0;
  color: var(--teal);
  font-size: 12px;
}

.compare__empty {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.compare__plain {
  margin: 0;
  white-space: pre-wrap;
  color: var(--text);
}
</style>
