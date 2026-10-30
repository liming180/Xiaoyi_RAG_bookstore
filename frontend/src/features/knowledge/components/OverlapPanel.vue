<script setup lang="ts">
import { computed } from 'vue';
import type { ChunkItem } from '@/types/api';
import { positionText } from '@/utils/text';
import { overlapLength } from '../composables/chunkMerge';

/**
 * OverlapPanel —— 相邻片段并排（P4-B 拓展 B）。
 *
 * 目的是让 overlap 变得「看得见」：左栏片段尾部与右栏片段头部会重复同一段文字。
 * 这里除了并排展示，还把重复部分单独抽出来高亮 —— 用户不用自己数重叠了多少字。
 */
const props = defineProps<{
  prev: ChunkItem | null;
  self: ChunkItem;
  next: ChunkItem | null;
}>();

const emit = defineEmits<{
  close: [];
}>();

/** 左栏 = prev ?? self，右栏 = next ?? self —— 保证两栏始终都有内容 */
const left = computed<ChunkItem>(() => props.prev ?? props.self);
const right = computed<ChunkItem>(() => props.next ?? props.self);

/** 两栏真实的重叠字数（用相邻对求最长公共前后缀） */
const overlap = computed(() => overlapLength(left.value, right.value));

/** 重叠的那段文字（左栏尾部 = 右栏头部） */
const overlapText = computed(() => {
  if (overlap.value <= 0) return '';
  return left.value.text.slice(left.value.text.length - overlap.value);
});

/** 左栏去掉重叠尾部的正文 */
const leftBody = computed(() => {
  if (overlap.value <= 0) return left.value.text;
  return left.value.text.slice(0, left.value.text.length - overlap.value);
});

/** 右栏去掉重叠头部的正文 */
const rightBody = computed(() => {
  if (overlap.value <= 0) return right.value.text;
  return right.value.text.slice(overlap.value);
});
</script>

<template>
  <section class="overlap" data-testid="overlap-panel">
    <header class="overlap__head">
      <h3 class="overlap__title">相邻片段重叠观察</h3>
      <span class="overlap__stat" data-testid="overlap-length">重叠 {{ overlap }} 字</span>
      <el-button size="small" text data-testid="overlap-close" @click="emit('close')">
        关闭
      </el-button>
    </header>

    <div v-if="overlap > 0" class="overlap__hit" data-testid="overlap-text">
      {{ overlapText }}
    </div>
    <p v-else class="overlap__none" data-testid="overlap-none">
      这两段之间没有重叠（可能跨了文档边界，或 overlap 设为 0）。
    </p>

    <div class="overlap__grid">
      <article class="overlap__col" data-testid="overlap-left">
        <header class="overlap__col-head">
          <code>{{ left.chunkId }}</code>
          <span>{{ positionText(left.start, left.end) }}</span>
        </header>
        <p class="overlap__body">
          <span>{{ leftBody }}</span>
          <mark v-if="overlap > 0" class="overlap__mark">{{ overlapText }}</mark>
        </p>
      </article>

      <article class="overlap__col" data-testid="overlap-right">
        <header class="overlap__col-head">
          <code>{{ right.chunkId }}</code>
          <span>{{ positionText(right.start, right.end) }}</span>
        </header>
        <p class="overlap__body">
          <mark v-if="overlap > 0" class="overlap__mark">{{ overlapText }}</mark>
          <span>{{ rightBody }}</span>
        </p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.overlap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  background: var(--paper);
  border: 1px solid var(--teal);
  border-radius: var(--radius);
}

.overlap__head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.overlap__title {
  margin: 0;
  font-size: 13px;
}

.overlap__stat {
  padding: 1px 8px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--teal-dark);
  background: var(--soft);
  border-radius: 999px;
}

.overlap__hit {
  padding: 6px 10px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink);
  background: var(--amber-soft);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
  word-break: break-word;
}

.overlap__none {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.overlap__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

@media (max-width: 900px) {
  .overlap__grid {
    grid-template-columns: 1fr;
  }
}

.overlap__col {
  padding: 8px 10px;
  background: var(--bg);
  border-radius: var(--radius-sm);
}

.overlap__col-head {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--muted);
}

.overlap__col-head code {
  font-family: var(--font-mono);
  color: var(--teal-dark);
}

.overlap__body {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.overlap__mark {
  padding: 0 1px;
  color: var(--ink);
  background: var(--amber-soft);
  border-radius: 2px;
}
</style>
