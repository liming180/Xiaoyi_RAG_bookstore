<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Citation } from '@/types/api';
import { positionText, scoreWidth, truncate } from '@/utils/text';

/**
 * CitationCard —— 引用卡（F05 五要素）。
 *
 * 引用编号 + 片段 ID（等宽） + 所属文件名 + 得分条 + 摘录（可展开完整原文）。
 * kind=summary 时显示「🌐 全局汇总」（套餐 A5）；verified=false 显示「未核实」（F11）。
 */
const props = defineProps<{
  citation: Citation;
  /** 触发它的原始问题，用于摘录高亮 */
  question?: string;
  /** 是否高亮（点击徽标后定位到的那一张） */
  active?: boolean;
}>();

const emit = defineEmits<{ close: []; openInKnowledge: [Citation] }>();

const expanded = ref(false);

const kindLabel = computed(() => {
  switch (props.citation.kind) {
    case 'summary':
      return '🌐 全局汇总';
    case 'rule':
      return '规则片段';
    default:
      return '原文片段';
  }
});

const refLabel = computed(() => `[${String(props.citation.ref)}]`);

const range = computed(() => positionText(props.citation.start, props.citation.end));

const excerpt = computed(() => truncate(props.citation.text, 220));

const scorePct = computed(() => props.citation.score.toFixed(2));

/** 摘录里命中问题关键词的片段（简单按整词包含切分，避免正则注入） */
const segments = computed(() => {
  const q = (props.question ?? '').trim();
  const text = excerpt.value;
  if (!q) return [{ text, hit: false }];
  const tokens = q
    .split(/[\s，。？！、；：“”‘’（）()《》[\]{}<>:;,.?!"'`~@#$%^&*+=|\\/_—-]+/)
    .map((t) => t.trim())
    .filter((t) => t.length >= 2)
    .slice(0, 6);
  if (tokens.length === 0) return [{ text, hit: false }];

  const out: { text: string; hit: boolean }[] = [];
  let cursor = 0;
  while (cursor < text.length) {
    let nextIdx = -1;
    let nextTok = '';
    for (const tok of tokens) {
      const idx = text.indexOf(tok, cursor);
      if (idx >= 0 && (nextIdx === -1 || idx < nextIdx)) {
        nextIdx = idx;
        nextTok = tok;
      }
    }
    if (nextIdx === -1) {
      out.push({ text: text.slice(cursor), hit: false });
      break;
    }
    if (nextIdx > cursor) out.push({ text: text.slice(cursor, nextIdx), hit: false });
    out.push({ text: nextTok, hit: true });
    cursor = nextIdx + nextTok.length;
  }
  return out.length > 0 ? out : [{ text, hit: false }];
});

function toggle(): void {
  expanded.value = !expanded.value;
}
</script>

<template>
  <article
    class="cite-card"
    :class="{ 'cite-card--active': active }"
    :data-testid="'cite-card-' + String(citation.ref)"
  >
    <header class="cite-card__head">
      <span class="cite-card__ref">{{ refLabel }}</span>
      <code class="cite-card__chunk">{{ citation.chunkId || '—' }}</code>
      <span class="cite-card__doc" :title="citation.docTitle">{{ citation.docTitle }}</span>
      <span class="cite-card__kind" :class="`cite-card__kind--${citation.kind}`">{{ kindLabel }}</span>
      <span v-if="!citation.verified" class="cite-card__unverified" data-testid="cite-unverified"
        >未核实</span
      >
      <button type="button" class="cite-card__close" aria-label="关闭引用卡" @click="emit('close')">
        ✕
      </button>
    </header>

    <p v-if="citation.headingPath" class="cite-card__heading">{{ citation.headingPath }}</p>

    <div class="cite-card__score">
      <div class="cite-card__score-bar">
        <div class="cite-card__score-fill" :style="{ width: scoreWidth(citation.score) }" />
      </div>
      <span class="cite-card__score-num">{{ scorePct }}</span>
    </div>

    <p class="cite-card__excerpt" data-testid="cite-excerpt">
      <template v-for="(seg, i) in segments" :key="i">
        <mark v-if="seg.hit">{{ seg.text }}</mark>
        <template v-else>{{ seg.text }}</template>
      </template>
    </p>

    <p v-if="expanded" class="cite-card__full" data-testid="cite-full">{{ citation.text }}</p>

    <footer class="cite-card__foot">
      <span class="cite-card__range">{{ range }}</span>
      <button type="button" class="cite-card__link" @click="toggle">
        {{ expanded ? '收起原文' : '展开完整片段' }}
      </button>
      <button type="button" class="cite-card__link" @click="emit('openInKnowledge', citation)">
        在知识库中查看
      </button>
    </footer>
  </article>
</template>

<style scoped>
.cite-card {
  padding: 12px 14px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
  font-size: 13px;
}

.cite-card--active {
  border-color: var(--teal);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--teal) 18%, transparent);
}

.cite-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cite-card__ref {
  font-weight: 700;
  color: var(--teal);
}

.cite-card__chunk {
  padding: 1px 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text);
  background: var(--sidebar);
  border-radius: 4px;
}

.cite-card__doc {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: var(--ink);
}

.cite-card__kind {
  padding: 1px 6px;
  font-size: 11px;
  border-radius: 999px;
  background: var(--soft);
  color: var(--teal);
}

.cite-card__kind--summary {
  background: #eaf2ec;
  color: var(--teal-dark);
}

.cite-card__kind--rule {
  background: var(--amber-soft);
  color: var(--amber);
}

.cite-card__unverified {
  padding: 1px 6px;
  font-size: 11px;
  border-radius: 999px;
  background: var(--amber-soft);
  color: var(--amber);
}

.cite-card__close {
  border: 0;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
}

.cite-card__close:hover {
  color: var(--red);
}

.cite-card__heading {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.cite-card__score {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
}

.cite-card__score-bar {
  flex: 1;
  height: 5px;
  background: var(--line);
  border-radius: 999px;
  overflow: hidden;
}

.cite-card__score-fill {
  height: 100%;
  background: var(--teal);
  border-radius: 999px;
}

.cite-card__score-num {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
}

.cite-card__excerpt {
  margin: 0;
  color: var(--text);
  line-height: 1.7;
}

.cite-card__excerpt :deep(mark) {
  padding: 0 2px;
  background: #fdf3d3;
  color: var(--ink);
  border-radius: 3px;
}

.cite-card__full {
  margin: 8px 0 0;
  padding: 8px 10px;
  max-height: 220px;
  overflow: auto;
  background: var(--sidebar);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.cite-card__foot {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--muted);
}

.cite-card__range {
  font-family: var(--font-mono);
}

.cite-card__link {
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--teal);
  cursor: pointer;
  font-size: 11px;
}

.cite-card__link:hover {
  text-decoration: underline;
}
</style>
