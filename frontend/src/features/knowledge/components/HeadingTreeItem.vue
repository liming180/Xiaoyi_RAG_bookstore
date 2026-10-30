<script setup lang="ts">
import type { HeadingNode } from '../composables/chunkFilter';

/**
 * HeadingTreeItem —— 标题树的一个节点（自引用递归）。
 *
 * Vue SFC 允许在自身模板里用文件名引用自己，所以 children 直接再渲染
 * 一层 HeadingTreeItem 即可，不需要额外的手写 render 函数。
 */
const props = defineProps<{
  node: HeadingNode;
  selected?: string | null;
}>();

const emit = defineEmits<{
  select: [string | null];
}>();

function onSelect(): void {
  // 再点一次同一个节点 = 取消选中
  emit('select', props.selected === props.node.key ? null : props.node.key);
}
</script>

<template>
  <li class="htree__item">
    <button
      type="button"
      class="htree__node"
      :class="{ 'htree__node--on': selected === node.key }"
      :data-testid="`heading-node-${node.key}`"
      :style="{ paddingLeft: `${8 + node.depth * 12}px` }"
      @click="onSelect"
    >
      <span class="htree__label">{{ node.label }}</span>
      <span class="htree__count">{{ node.count }}</span>
    </button>

    <ul v-if="node.children.length > 0" class="htree__list">
      <HeadingTreeItem
        v-for="child in node.children"
        :key="child.key"
        :node="child"
        :selected="selected"
        @select="(key) => emit('select', key)"
      />
    </ul>
  </li>
</template>

<style scoped>
.htree__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.htree__item {
  list-style: none;
}

.htree__node {
  display: flex;
  align-items: center;
  justify-content: space-between;
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

.htree__node:hover {
  background: var(--soft);
}

.htree__node--on {
  color: var(--teal-dark);
  background: var(--soft);
  font-weight: 600;
}

.htree__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.htree__count {
  flex: none;
  margin-left: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
}
</style>
