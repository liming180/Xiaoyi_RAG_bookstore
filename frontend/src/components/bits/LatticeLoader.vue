<template>
  <span
    role="status"
    class="ll-root"
    :class="className"
    :data-status="status"
    :data-shape="shape"
    :data-glow="glow ? '' : undefined"
    :style="rootStyle"
  >
    <span class="ll-stack" aria-hidden="true">
      <span class="ll-run">
        <span
          v-for="(unit, i) in pat.cells"
          :key="i"
          :class="cellClass(unit)"
          :data-hole="unit == null ? '' : undefined"
          :data-lit="pat.lit && pat.lit !== 0.62 ? Math.round(pat.lit * 100) : undefined"
          :style="unit == null ? undefined : { animationDelay: `${Math.round(unit * d)}ms` }"
        />
      </span>
      <span class="ll-mark">
        <span
          v-for="(_, i) in pat.cells"
          :key="i"
          class="ll-mark-cell"
          :data-on="marks[mark].includes(i) ? '' : undefined"
        />
      </span>
    </span>
    <span class="ll-label-wrap" aria-hidden="true">
      <span class="ll-text" :data-active="status === 'working' ? '' : undefined">{{ label }}</span>
      <span class="ll-text" :data-active="status === 'done' ? '' : undefined">{{ doneLabel }}</span>
      <span class="ll-text" :data-active="status === 'error' ? '' : undefined">{{ errorLabel }}</span>
    </span>
    <span v-if="showTimer" ref="timerRef" class="ll-timer">0.0s</span>
    <span class="sr-only">{{ announce }}</span>
  </span>
</template>

<script setup lang="ts">
// 来源：vue-bits src/content/Micro/LatticeLoader/LatticeLoader.vue
// （DavidHDev/vue-bits @ 3766ebee，https://vue-bits.dev/micro/lattice-loader）
// 官方零 npm 依赖实现（纯 Vue + CSS keyframes）。脚本逻辑与 keyframes 原样保留；
// 改动仅限样式承载方式：上游 33 处 Tailwind 任意值类名（[gap:...]、
// group-data-[status=done]:... 等）在本文件改写为 scoped CSS 属性选择器，
// 视觉参数（尺寸/间距/透明度/缓动）与上游一一对应。
import { computed, onMounted, onUnmounted, ref, watch, type CSSProperties } from 'vue';

export type LatticeStatus = 'working' | 'done' | 'error';
export type LatticePatternName =
  | 'arrow'
  | 'dots'
  | 'orbit'
  | 'ripple'
  | 'snake'
  | 'spiral'
  | 'sweep'
  | 'spin'
  | 'rain'
  | 'pulse';
export type LatticeGrid = 3 | 4;

export interface LatticePattern {
  cells: (number | null)[];
  loop?: number;
  scale?: number;
  lit?: 0.25 | 0.35 | 0.45 | 0.62;
}

interface LatticeLoaderProps {
  label?: string;
  doneLabel?: string;
  errorLabel?: string;
  status?: LatticeStatus;
  pattern?: LatticePatternName | LatticePattern;
  grid?: LatticeGrid;
  shape?: 'square' | 'round';
  color?: string;
  doneColor?: string;
  errorColor?: string;
  cellSize?: number;
  gap?: number;
  fontSize?: number;
  step?: number;
  idleOpacity?: number;
  glow?: boolean;
  glowColor?: string;
  showTimer?: boolean;
  elapsed?: number;
  className?: string;
}

type ResolvedPattern = { cells: (number | null)[]; loop: number; scale: number; lit?: number };

const PATTERNS: Record<LatticePatternName, Partial<Record<LatticeGrid, ResolvedPattern>>> = {
  arrow: { 3: { cells: [1, 2, 3, 0, 1, 2, 1, 2, 3], loop: 7.2, scale: 1 } },
  dots: { 3: { cells: [0, 1, 2, 0, 1, 2, 0, 1, 2], loop: 3, scale: 2.4 } },
  ripple: { 3: { cells: [2, 1, 2, 1, 0, 1, 2, 1, 2], loop: 4.8, scale: 1.5 } },
  spiral: { 3: { cells: [0, 1, 2, 7, 8, 3, 6, 5, 4], loop: 9, scale: 1.2, lit: 0.35 } },
  orbit: {
    3: { cells: [0, 1, 2, 7, null, 3, 6, 5, 4], loop: 8, scale: 1.2 },
    4: {
      cells: [0, 1, 2, 3, 11, null, null, 4, 10, null, null, 5, 9, 8, 7, 6],
      loop: 6,
      scale: 1.2,
      lit: 0.45,
    },
  },
  snake: {
    3: { cells: [0, 1, 2, 5, 4, 3, 6, 7, 8], loop: 9, scale: 1, lit: 0.35 },
    4: {
      cells: [0, 1, 2, 3, 7, 6, 5, 4, 8, 9, 10, 11, 15, 14, 13, 12],
      loop: 16,
      scale: 1,
      lit: 0.25,
    },
  },
  sweep: { 4: { cells: [0, 1, 2, 3, 1, 2, 3, 4, 2, 3, 4, 5, 3, 4, 5, 6], loop: 5, scale: 1, lit: 0.45 } },
  spin: { 4: { cells: [0, 0, 1, 1, 0, 0, 1, 1, 3, 3, 2, 2, 3, 3, 2, 2], loop: 4, scale: 1.6, lit: 0.35 } },
  rain: { 4: { cells: [0, 2, 1, 3, 1, 3, 2, 4, 2, 4, 3, 5, 3, 5, 4, 6], loop: 4, scale: 1.2, lit: 0.35 } },
  pulse: { 4: { cells: [2, 1, 1, 2, 1, 0, 0, 1, 1, 0, 0, 1, 2, 1, 1, 2], loop: 2.4, scale: 2.5, lit: 0.45 } },
};
const DEFAULT_PATTERN: Record<LatticeGrid, LatticePatternName> = { 3: 'orbit', 4: 'sweep' };
const MARKS: Record<LatticeGrid, Record<'done' | 'error', number[]>> = {
  3: { done: [2, 3, 5, 7], error: [0, 2, 4, 6, 8] },
  4: { done: [7, 8, 10, 13], error: [0, 3, 5, 6, 9, 10, 12, 15] },
};

const resolvePattern = (
  pattern: LatticePatternName | LatticePattern,
  grid: LatticeGrid,
): ResolvedPattern => {
  if (typeof pattern === 'string') {
    const named = PATTERNS[pattern];
    return (named && named[grid]) || (PATTERNS[DEFAULT_PATTERN[grid]][grid] as ResolvedPattern);
  }
  const cells = Array.from({ length: grid * grid }, (_, i) => pattern.cells[i] ?? null);
  const max = Math.max(0, ...cells.filter((v): v is number => v != null));
  return { cells, loop: pattern.loop ?? max + 4.2, scale: pattern.scale ?? 1, lit: pattern.lit ?? 0.62 };
};

const fmt = (ds: number) =>
  ds < 600 ? `${(ds / 10).toFixed(1)}s` : `${Math.floor(ds / 600)}m ${((ds % 600) / 10).toFixed(1)}s`;
const spoken = (ds: number) =>
  ds < 600
    ? `${(ds / 10).toFixed(1)} seconds`
    : `${Math.floor(ds / 600)} minutes ${((ds % 600) / 10).toFixed(1)} seconds`;

const props = withDefaults(defineProps<LatticeLoaderProps>(), {
  label: 'Thinking',
  doneLabel: 'Done in',
  errorLabel: 'Failed after',
  status: 'working',
  pattern: 'orbit',
  grid: 3,
  shape: 'round',
  color: 'currentColor',
  doneColor: '#22c55e',
  errorColor: '#ef4444',
  cellSize: 6,
  gap: 2,
  fontSize: 14,
  step: 90,
  idleOpacity: 0.15,
  glow: false,
  glowColor: '',
  showTimer: true,
  elapsed: undefined,
  className: '',
});

const n = computed<LatticeGrid>(() => (props.grid === 4 ? 4 : 3));
const pat = computed(() => resolvePattern(props.pattern, n.value));
const marks = computed(() => MARKS[n.value]);
const d = computed(() => props.step * pat.value.scale);
const cycle = computed(() => Math.round(pat.value.loop * d.value));

let lastMark: 'done' | 'error' = 'done';
const mark = computed(() => {
  if (props.status !== 'working') lastMark = props.status;
  return lastMark;
});

const timerRef = ref<HTMLSpanElement | null>(null);
let ds = 0;
let clock: ReturnType<typeof setInterval> | undefined;
const announce = ref(`${props.label}, in progress`);

const paint = (next: number) => {
  ds = next;
  if (timerRef.value) timerRef.value.textContent = fmt(next);
};

const syncClock = () => {
  clearInterval(clock);
  if (props.elapsed != null) {
    paint(Math.round(props.elapsed * 10));
    return;
  }
  if (props.status !== 'working') return;
  const startedAt = performance.now();
  paint(0);
  clock = setInterval(() => paint(Math.floor((performance.now() - startedAt) / 100)), 100);
};
const syncAnnounce = () => {
  announce.value =
    props.status === 'working'
      ? `${props.label}, in progress`
      : `${props.status === 'done' ? props.doneLabel : props.errorLabel}${props.showTimer ? ` ${spoken(ds)}` : ''}`;
};

onMounted(() => {
  syncClock();
  syncAnnounce();
});
watch(
  () => [props.status, props.elapsed],
  () => {
    syncClock();
    syncAnnounce();
  },
  { flush: 'post' },
);
onUnmounted(() => clearInterval(clock));

const cellClass = (unit: number | null) => {
  if (unit == null) return ['ll-cell', 'll-cell--hole'];
  return ['ll-cell', 'll-cell--lit'];
};

const rootStyle = computed(
  () =>
    ({
      '--ll-n': n.value,
      '--ll-cell': `${props.cellSize}px`,
      '--ll-gap': `${props.gap}px`,
      '--ll-font': `${props.fontSize}px`,
      '--ll-color': props.color,
      '--ll-mark': props.status === 'error' ? props.errorColor : props.doneColor,
      '--ll-idle': props.idleOpacity,
      '--ll-glow': props.glowColor || props.color,
      '--ll-mark-glow':
        props.glowColor || (props.status === 'error' ? props.errorColor : props.doneColor),
      '--ll-cycle': `${cycle.value}ms`,
      '--ll-peak': 1,
      '--ll-ease-out': 'cubic-bezier(0.23, 1, 0.32, 1)',
      '--ll-ease-in-out': 'cubic-bezier(0.77, 0, 0.175, 1)',
    }) as CSSProperties,
);
</script>

<style scoped>
/* ---- 结构（对应上游模板上的 Tailwind 结构类） ---- */
.ll-root {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: calc(var(--ll-font) * 0.625);
  font-size: var(--ll-font);
  font-family: inherit;
  line-height: 1;
}
.ll-stack {
  display: grid;
  flex-shrink: 0;
}
.ll-run,
.ll-mark {
  grid-area: 1 / 1;
  display: grid;
  grid-template-columns: repeat(var(--ll-n), var(--ll-cell));
  gap: var(--ll-gap);
}
.sr-only {
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

/* ---- 单元格 ---- */
.ll-cell {
  width: var(--ll-cell);
  height: var(--ll-cell);
  border-radius: max(1px, calc(var(--ll-cell) * 0.25));
  background: var(--ll-color);
}
.ll-root[data-shape='round'] .ll-cell {
  border-radius: 999px;
}
.ll-cell--hole {
  opacity: calc(var(--ll-idle) * 0.47);
}
.ll-cell--lit {
  opacity: var(--ll-idle);
  animation: lattice-on var(--ll-cycle) var(--ll-ease-in-out) infinite;
}
.ll-cell--lit[data-lit='45'] {
  animation-name: lattice-on-45;
}
.ll-cell--lit[data-lit='35'] {
  animation-name: lattice-on-35;
}
.ll-cell--lit[data-lit='25'] {
  animation-name: lattice-on-25;
}
.ll-root[data-glow] .ll-cell--lit {
  box-shadow: 0 0 calc(var(--ll-cell) * 1.2) calc(var(--ll-cell) * 0.12) var(--ll-glow);
}

/* ---- done/error 印记层 ---- */
.ll-mark {
  transform-origin: center;
  opacity: 0;
  transform: scale(0.9);
  transition:
    opacity 160ms var(--ll-ease-out),
    transform 160ms var(--ll-ease-out);
}
.ll-mark-cell {
  width: var(--ll-cell);
  height: var(--ll-cell);
  border-radius: max(1px, calc(var(--ll-cell) * 0.25));
  background: var(--ll-color);
  opacity: var(--ll-idle);
  transition:
    opacity 200ms ease,
    background-color 200ms ease;
}
.ll-root[data-shape='round'] .ll-mark-cell {
  border-radius: 999px;
}
.ll-mark-cell[data-on] {
  background: var(--ll-mark);
  opacity: var(--ll-peak);
}
.ll-root[data-glow] .ll-mark-cell[data-on] {
  box-shadow: 0 0 calc(var(--ll-cell) * 1.2) calc(var(--ll-cell) * 0.12) var(--ll-mark-glow);
}
.ll-root[data-status='done'] .ll-run,
.ll-root[data-status='error'] .ll-run {
  opacity: 0;
}
.ll-root[data-status='done'] .ll-run > span,
.ll-root[data-status='error'] .ll-run > span {
  animation-play-state: paused;
}
.ll-root[data-status='done'] .ll-mark,
.ll-root[data-status='error'] .ll-mark {
  opacity: 1;
  transform: none;
  transition:
    opacity 200ms ease,
    transform 200ms var(--ll-ease-out);
}

/* ---- 文字 ---- */
.ll-label-wrap {
  position: relative;
  display: inline-block;
  font-weight: 500;
}
.ll-text {
  position: absolute;
  top: 0;
  left: 0;
  white-space: nowrap;
  opacity: 0;
  filter: blur(2px);
  transition:
    opacity 200ms ease,
    filter 200ms ease;
}
.ll-text[data-active] {
  position: static;
  opacity: 1;
  filter: blur(0);
}

/* ---- 计时 ---- */
.ll-timer {
  opacity: 0.6;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: calc(var(--ll-font) * 0.875);
}
</style>

<style>
/* 上游全局 keyframes，原样保留（名称带 lattice- 前缀，无冲突） */
@keyframes lattice-on {
  0%,
  100% {
    opacity: var(--ll-idle);
  }
  18%,
  42% {
    opacity: var(--ll-peak);
  }
  62% {
    opacity: var(--ll-idle);
  }
}
@keyframes lattice-on-45 {
  0%,
  100% {
    opacity: var(--ll-idle);
  }
  13%,
  31% {
    opacity: var(--ll-peak);
  }
  45% {
    opacity: var(--ll-idle);
  }
}
@keyframes lattice-on-35 {
  0%,
  100% {
    opacity: var(--ll-idle);
  }
  10%,
  24% {
    opacity: var(--ll-peak);
  }
  35% {
    opacity: var(--ll-idle);
  }
}
@keyframes lattice-on-25 {
  0%,
  100% {
    opacity: var(--ll-idle);
  }
  7%,
  17% {
    opacity: var(--ll-peak);
  }
  25% {
    opacity: var(--ll-idle);
  }
}
@media (prefers-reduced-motion: reduce) {
  .ll-run {
    --ll-peak: 0.7;
  }
  .ll-run > span {
    animation-delay: 0ms !important;
    animation-duration: 1400ms !important;
  }
  .ll-mark {
    transform: none !important;
  }
  .ll-text {
    filter: none !important;
  }
}
</style>
