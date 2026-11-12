<script setup lang="ts">
import { computed } from 'vue';
import type { Citation } from '@/types/api';
import { parseMarkdown } from '@/utils/markdown';
import InlineRenderer from './InlineRenderer.vue';

/**
 * AnswerBody —— 结构化回答渲染（套餐 B3）。
 *
 * 白名单：标题 / 列表 / 表格 / 加粗 / 链接 / 引用编号。
 * 其它一切（img、script、on* 属性、javascript: 链接）要么降级成纯文本，
 * 要么由 Vue 自动转义 —— 全仓 0 处 v-html 是硬性门禁项。
 */
const props = defineProps<{
  content: string;
  citations: Citation[];
}>();

const emit = defineEmits<{ cite: [Citation] }>();

const blocks = computed(() => parseMarkdown(props.content ?? ''));
</script>

<template>
  <div class="answer-body" data-testid="answer-body">
    <template v-for="(block, bi) in blocks" :key="bi">
      <component :is="`h${Math.min(block.level + 2, 6)}`" v-if="block.type === 'heading'">
        <InlineRenderer :inlines="block.inlines" :citations="citations" @cite="emit('cite', $event)" />
      </component>

      <ul v-else-if="block.type === 'list' && !block.ordered">
        <li v-for="(item, ii) in block.items" :key="ii">
          <InlineRenderer :inlines="item" :citations="citations" @cite="emit('cite', $event)" />
        </li>
      </ul>
      <ol v-else-if="block.type === 'list'">
        <li v-for="(item, ii) in block.items" :key="ii">
          <InlineRenderer :inlines="item" :citations="citations" @cite="emit('cite', $event)" />
        </li>
      </ol>

      <table v-else-if="block.type === 'table'" class="answer-body__table">
        <thead>
          <tr>
            <th v-for="(cell, ci) in block.header" :key="ci">
              <InlineRenderer :inlines="cell" :citations="citations" @cite="emit('cite', $event)" />
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ri) in block.rows" :key="ri">
            <td v-for="(cell, ci) in row" :key="ci">
              <InlineRenderer :inlines="cell" :citations="citations" @cite="emit('cite', $event)" />
            </td>
          </tr>
        </tbody>
      </table>

      <p v-else>
        <InlineRenderer
          :inlines="block.inlines"
          :citations="citations"
          @cite="emit('cite', $event)"
        />
      </p>
    </template>
  </div>
</template>

<style scoped>
.answer-body {
  font-size: 14px;
  line-height: 1.75;
  color: var(--text);
  word-break: break-word;
}

.answer-body :deep(h3),
.answer-body :deep(h4),
.answer-body :deep(h5),
.answer-body :deep(h6) {
  margin: 14px 0 6px;
  font-size: 14px;
  font-weight: 650;
  color: var(--ink);
}

.answer-body :deep(p) {
  margin: 0 0 10px;
}

.answer-body :deep(p:last-child) {
  margin-bottom: 0;
}

.answer-body :deep(ul),
.answer-body :deep(ol) {
  margin: 0 0 10px;
  padding-left: 20px;
}

.answer-body :deep(li) {
  margin: 3px 0;
}

.answer-body :deep(a) {
  color: var(--teal);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.answer-body__table {
  width: 100%;
  margin: 8px 0 12px;
  border-collapse: collapse;
  font-size: 13px;
}

.answer-body__table :deep(th),
.answer-body__table :deep(td) {
  padding: 6px 10px;
  border: 1px solid var(--line);
  text-align: left;
}

.answer-body__table :deep(th) {
  background: var(--sidebar);
  font-weight: 600;
  color: var(--ink);
}
</style>
