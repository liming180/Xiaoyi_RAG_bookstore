<template>
  <div
    ref="divRef"
    @mousemove="handleMouseMove"
    @focus="handleFocus"
    @blur="handleBlur"
    @mouseenter="handleMouseEnter"
    @mouseleave="handleMouseLeave"
    :class="['spot-card', className]"
  >
    <div
      class="spot-card__glow"
      :style="{
        opacity,
        background: `radial-gradient(circle at ${position.x}px ${position.y}px, ${spotlightColor}, transparent 80%)`,
      }"
    />

    <slot />
  </div>
</template>

<script setup lang="ts">
// 来源：vue-bits src/content/Components/SpotlightCard/SpotlightCard.vue
// （DavidHDev/vue-bits @ 3766ebee，https://vue-bits.dev/components/spotlight-card）
// 官方零依赖实现；唯一改动：模板上 4 个 Tailwind 常规类
// （relative rounded-3xl border overflow-hidden p-8）改写为本文件 scoped CSS，
// padding 交还给使用方的布局（本项目摘要条自带 10px 14px）。
import { ref, useTemplateRef } from 'vue';

interface Position {
  x: number;
  y: number;
}

interface SpotlightCardProps {
  className?: string;
  spotlightColor?: string;
}

const { className = '', spotlightColor = 'rgba(255, 255, 255, 0.25)' } =
  defineProps<SpotlightCardProps>();

const divRef = useTemplateRef<HTMLDivElement>('divRef');
const isFocused = ref<boolean>(false);
const position = ref<Position>({ x: 0, y: 0 });
const opacity = ref<number>(0);

const handleMouseMove = (e: MouseEvent) => {
  if (!divRef.value || isFocused.value) return;

  const rect = divRef.value.getBoundingClientRect();
  position.value = { x: e.clientX - rect.left, y: e.clientY - rect.top };
};

const handleFocus = () => {
  isFocused.value = true;
  opacity.value = 0.6;
};

const handleBlur = () => {
  isFocused.value = false;
  opacity.value = 0;
};

const handleMouseEnter = () => {
  opacity.value = 0.6;
};

const handleMouseLeave = () => {
  opacity.value = 0;
};
</script>

<style scoped>
.spot-card {
  position: relative;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  overflow: hidden;
}

/* 官方结构：绝对定位渐变层，pointer-events:none，不挡按钮点击 */
.spot-card__glow {
  pointer-events: none;
  position: absolute;
  inset: 0;
  opacity: 0;
  transition: opacity 0.3s ease-in-out;
}
</style>
