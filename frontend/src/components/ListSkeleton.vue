<script setup lang="ts">
/**
 * 列表页骨架屏（P6 打磨项）。
 *
 * 为什么抽成一个共享组件而不是各页各写一段：
 * 1. 五个列表页（资料 / 片段 / 候选池 / 历史 / 题目）的加载态必须长得一样，
 *    否则切页签时视觉会「跳」——同一套骨架，尺寸与节奏才能对齐；
 * 2. 骨架屏是纯装饰，`aria-hidden` 让读屏软件跳过，同时保留一行
 *    视觉隐藏的文字（`role="status"`），保证「正在加载」这个信息不丢。
 *
 * 用骨架而不是「正在加载…」文字的原因：数据回来时布局不塌陷，
 * 用户不会看到「文字 → 表格」的高度突变。
 */
withDefaults(
  defineProps<{
    /** 骨架行数，默认 4 行；列表页通常 4~6 行足够占住首屏。 */
    rows?: number;
    /** 读屏与测试用的加载文案。 */
    label?: string;
  }>(),
  { rows: 4, label: '正在加载…' },
);
</script>

<template>
  <div class="skeleton" role="status" :aria-label="label">
    <span class="skeleton__sr">{{ label }}</span>
    <div
      v-for="i in rows"
      :key="i"
      class="skeleton__row"
      :class="{ 'skeleton__row--wide': i % 3 === 1 }"
      aria-hidden="true"
    >
      <span class="skeleton__bar skeleton__bar--title" />
      <span class="skeleton__bar skeleton__bar--meta" />
    </div>
  </div>
</template>

<style scoped>
.skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.skeleton__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

.skeleton__row {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 22px;
}

.skeleton__bar {
  display: block;
  height: 12px;
  border-radius: 999px;
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--line) 55%, transparent) 0%,
    color-mix(in srgb, var(--line) 100%, transparent) 50%,
    color-mix(in srgb, var(--line) 55%, transparent) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-sweep 1.3s ease-in-out infinite;
}

.skeleton__bar--title {
  width: 42%;
}

.skeleton__bar--meta {
  width: 22%;
  opacity: 0.7;
}

.skeleton__row--wide .skeleton__bar--title {
  width: 56%;
}

/* 尊重系统的「减少动态效果」：动画只留静态灰块。 */
@media (prefers-reduced-motion: reduce) {
  .skeleton__bar {
    animation: none;
  }
}

@keyframes skeleton-sweep {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>
