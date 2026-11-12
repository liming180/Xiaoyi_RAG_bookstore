<script setup lang="ts">
import { computed } from 'vue';
import type { Message } from '@/types/api';
import AnswerBody from './AnswerBody.vue';
import { compareCells, compareVerdict, sideMetrics } from '../composables/compare';
import CountUp from '@/components/bits/CountUp.vue';
import SpotlightCard from '@/components/bits/SpotlightCard.vue';

/**
 * ComparePane —— 对照模式两栏（F06 + P6 完善）。
 *
 * 左：查资料（带引用）；右：直接答（无引用，模型自身知识）。
 *
 * 相比早期版本补了两样东西：
 *   1. **差异摘要条**：字数 / 引用 / 耗时 / 资料诚实度四格量化对比。
 *      早期只有两段文字，用户得用眼睛逐字比对才知道「有资料多知道了什么」。
 *   2. **两栏独立加载态**：右栏不再从始至终显示「暂无结果」，
 *      而是有自己的「正在独立生成…」提示 —— 它是**另一次** LLM 调用。
 */
const props = defineProps<{
  rag: Message | null;
  direct: Message | null;
  ragDraft?: string;
  directDraft?: string;
  /** 查资料侧是否在生成（含检索阶段） */
  ragPending?: boolean;
  /** 直接答侧是否在生成（检索完成后才开始，串行） */
  directPending?: boolean;
  /** 展示的两栏是否为实时生成（决定要不要显示加载态） */
  live?: boolean;
}>();

const ragText = computed(() => props.ragDraft ?? props.rag?.content ?? '');
const directText = computed(() => props.directDraft ?? props.direct?.content ?? '');
const ragCitations = computed(() => props.rag?.citations ?? []);

const ragMetrics = computed(() => sideMetrics(props.rag, ragText.value));
const directMetrics = computed(() => sideMetrics(props.direct, directText.value));
const cells = computed(() => compareCells(ragMetrics.value, directMetrics.value));
const verdict = computed(() => compareVerdict(ragMetrics.value, directMetrics.value));

/** 摘要条只在两栏都有正文时才有意义 */
const showSummary = computed(() => ragMetrics.value.hasText && directMetrics.value.hasText);

/**
 * vue-bits 动效接入（U-x1 选型，草图已确认）：
 *  - SpotlightCard 包住摘要条，光标柔光用项目主色（浅/深主题各一档）
 *  - CountUp 让「字数 / 引用」两格 0 → 终值弹一次
 *
 * CountUp 上游行为：数值 prop 变化只复位不重播（IntersectionObserver 只在首挂载触发），
 * 流式落定后数值才定稿，所以用值本身作 :key 强制重挂载重播。
 * prefers-reduced-motion 时不播计数动画，直接渲染终值。
 */
const summarySpotColor = computed(() =>
  document?.documentElement?.getAttribute('data-theme') === 'dark'
    ? 'rgba(78, 157, 132, 0.18)'
    : 'rgba(39, 99, 82, 0.12)',
);
const reduceMotion =
  typeof window !== 'undefined' &&
  !!window.matchMedia &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const charsCountKey = computed(
  () => `chars-${ragMetrics.value.chars}-${directMetrics.value.chars}`,
);
const citeCountKey = computed(
  () => `cite-${ragMetrics.value.citations}-${directMetrics.value.citations}`,
);
const countDuration = reduceMotion ? 0 : 0.9;
const countDelay = reduceMotion ? 0 : 0.15;

const emit = defineEmits<{
  cite: [Message['citations'][number]];
  /** 以此题建评测用例（把对照时发现的差异送进候选池） */
  capture: [];
}>();
</script>

<template>
  <section class="compare" data-testid="compare-pane">
    <div class="compare__col compare__col--rag" data-testid="compare-rag">
      <header class="compare__head">
        <span class="compare__bar" />
        <span class="compare__title">查资料</span>
        <span class="compare__tag compare__tag--rag">引用知识库</span>
        <span v-if="ragMetrics.citations > 0" class="compare__count">
          {{ ragMetrics.citations }} 条来源
        </span>
      </header>
      <div class="compare__body">
        <p v-if="ragPending && !ragText" class="compare__pending" aria-busy="true">
          正在检索资料…
        </p>
        <AnswerBody
          v-else-if="ragText"
          :content="ragText"
          :citations="ragCitations"
          @cite="emit('cite', $event)"
        />
        <p v-else class="compare__empty">暂无结果</p>
      </div>
    </div>

    <div class="compare__col compare__col--direct" data-testid="compare-direct">
      <header class="compare__head">
        <span class="compare__bar" />
        <span class="compare__title">直接答</span>
        <span class="compare__tag compare__tag--direct">不查资料</span>
        <span v-if="directText" class="compare__count compare__count--warn">无来源可核对</span>
      </header>
      <div class="compare__body">
        <p v-if="directPending && !directText" class="compare__pending compare__pending--direct" aria-busy="true">
          正在独立作答…（不查资料）
        </p>
        <p v-else-if="directText" class="compare__plain">{{ directText }}</p>
        <p v-else class="compare__empty">暂无结果</p>
      </div>
    </div>

    <!-- 差异摘要条：对照模式的真正产出。SpotlightCard 包裹提供光标柔光（vue-bits） -->
    <SpotlightCard
      v-if="showSummary"
      class="compare__summary-spot"
      :spotlight-color="summarySpotColor"
    >
      <footer class="compare__summary" data-testid="compare-summary">
        <div class="compare__metrics">
          <div
            v-for="cell in cells"
            :key="cell.key"
            class="compare__metric"
            :class="`compare__metric--${cell.tone}`"
            :data-testid="`compare-metric-${cell.key}`"
          >
            <span class="compare__metric-label">{{ cell.label }}</span>
            <span v-if="cell.key === 'chars'" class="compare__metric-pair" :data-testid="`compare-count-chars`">
              <template v-if="live">
                <b>{{ ragMetrics.chars }}</b><i>/</i><b>{{ directMetrics.chars }}</b>
              </template>
              <template v-else>
                <b><CountUp :key="`rag-${charsCountKey}`" :to="ragMetrics.chars" :duration="countDuration" :delay="countDelay" /></b><i>/</i><b><CountUp :key="`direct-${charsCountKey}`" :to="directMetrics.chars" :duration="countDuration" :delay="countDelay" /></b>
              </template>
            </span>
            <span v-else-if="cell.key === 'citations'" class="compare__metric-pair" :data-testid="`compare-count-citations`">
              <template v-if="live">
                <b>{{ ragMetrics.citations }}</b><i>/</i><b>{{ directMetrics.citations }}</b>
              </template>
              <template v-else>
                <b><CountUp :key="`rag-${citeCountKey}`" :to="ragMetrics.citations" :duration="countDuration" :delay="countDelay" /></b><i>/</i><b><CountUp :key="`direct-${citeCountKey}`" :to="directMetrics.citations" :duration="countDuration" :delay="countDelay" /></b>
              </template>
            </span>
            <span v-else class="compare__metric-pair">
              <b>{{ cell.rag }}</b><i>/</i><b>{{ cell.direct }}</b>
            </span>
          </div>
        </div>
        <p class="compare__verdict" data-testid="compare-verdict">{{ verdict }}</p>
        <el-button
          size="small"
          text
          type="primary"
          data-testid="compare-capture"
          title="把这一问一答存入评测候选池，后续补上判分关键词即可计分"
          @click="emit('capture')"
        >
          以此题建评测用例 →
        </el-button>
      </footer>
    </SpotlightCard>
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
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px 8px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--sidebar);
}

/* 左侧色条：一眼分开「有资料」与「无资料」两栏 */
.compare__bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
}

.compare__col--rag .compare__bar {
  background: var(--teal);
}

.compare__col--direct .compare__bar {
  background: var(--amber);
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

.compare__count {
  margin-left: auto;
  font-size: 11px;
  color: var(--teal-dark);
}

.compare__count--warn {
  color: var(--amber);
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

.compare__pending--direct {
  color: var(--amber);
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

/* ------------------------------------------------------- 差异摘要条 */

.compare__summary-spot {
  grid-column: 1 / -1;
  background: var(--paper);
}

.compare__summary {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 10px 14px;
}

.compare__metrics {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
}

.compare__metric {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
}

.compare__metric-label {
  color: var(--muted);
}

.compare__metric-pair {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  font-family: var(--font-mono);
}

.compare__metric-pair i {
  font-style: normal;
  color: var(--line);
}

.compare__metric-pair b {
  font-weight: 600;
  color: var(--text);
}

/* 差异着色：优势侧用该栏的主色，避免用红绿去暗示「对错」 */
.compare__metric--rag .compare__metric-pair b:first-child {
  color: var(--teal-dark);
}

.compare__metric--direct .compare__metric-pair b:last-child {
  color: var(--amber);
}

.compare__verdict {
  flex: 1;
  min-width: 220px;
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
}
</style>
