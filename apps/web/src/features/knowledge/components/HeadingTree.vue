<script setup lang="ts">
import { computed } from 'vue';
import type { HeadingNode } from '../composables/chunkFilter';
import HeadingTreeItem from './HeadingTreeItem.vue';

/**
 * HeadingTree —— 标题路径树（P4-B）。
 *
 * 只做展示与选中：点击节点把全路径 key 上抛，父层用 matchesHeading 做前缀过滤。
 * 递归渲染交给 HeadingTreeItem（自引用 SFC），这里只负责顶层「全部章节」开关。
 */
const props = defineProps<{
  nodes: HeadingNode[];
  selected?: string | null;
}>();

const emit = defineEmits<{
  select: [string | null];
}>();

const hasNodes = computed(() => props.nodes.length > 0);
</script>

<template>
  <div class="heading-tree" data-testid="heading-tree">
    <div v-if="!hasNodes" class="heading-tree__empty" data-testid="heading-tree-empty">
      暂无可选章节
    </div>

    <template v-else>
      <button
        type="button"
        class="heading-tree__reset"
        :class="{ 'heading-tree__reset--on': !selected }"
        data-testid="heading-all"
        @click="emit('select', null)"
      >
        全部章节
      </button>
      <ul class="heading-tree__root">
        <HeadingTreeItem
          v-for="node in nodes"
          :key="node.key"
          :node="node"
          :selected="selected"
          @select="(key) => emit('select', key)"
        />
      </ul>
    </template>
  </div>
</template>

<style scoped>
.heading-tree {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.heading-tree__empty {
  padding: 10px 8px;
  font-size: 12px;
  color: var(--muted);
}

.heading-tree__reset {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 4px 8px;
  font-size: 12px;
  color: var(--ink);
  background: transparent;
  border: 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  text-align: left;
}

.heading-tree__reset:hover {
  background: var(--soft);
}

.heading-tree__reset--on {
  color: var(--teal-dark);
  background: var(--soft);
  font-weight: 600;
}

.heading-tree__root {
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
