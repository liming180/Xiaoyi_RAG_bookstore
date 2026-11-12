import type { Message } from '@/types/api';

/**
 * 对照模式的差异计算（F06）。
 *
 * 抽成纯函数的原因：两栏对比的判据必须可测。「有资料多知道什么」这种结论一旦
 * 写成模板里的内联表达式，就只能靠人眼看截图验证；抽出来之后可以逐条断言。
 */

/** 一侧的可测指标 */
export interface SideMetrics {
  /** 正文字数（去空白后） */
  chars: number;
  /** 引用条数 */
  citations: number;
  /** 耗时（ms），未知为 null */
  elapsedMs: number | null;
  /** 是否在说「资料中没有提到」 */
  noContext: boolean;
  /** 是否有正文 */
  hasText: boolean;
}

/** 判断一句话是不是「资料里没有」的委婉拒答 */
const NO_CONTEXT_TOKENS = [
  '资料中没有',
  '资料中未',
  '资料未提供',
  '资料没有',
  '未提供相关',
  '没有提到',
  '未提及',
  '无法确定',
];

/**
 * 一侧的指标。
 *
 * 字数按「去掉所有空白后的字符数」算：中文正文里的换行和缩进不该让
 * 「谁更详尽」这个比较失真。
 */
export function sideMetrics(message: Message | null, draft?: string): SideMetrics {
  const text = (draft ?? message?.content ?? '').trim();
  return {
    chars: text.replace(/\s+/g, '').length,
    citations: message?.citations?.length ?? 0,
    elapsedMs: message?.elapsedMs ?? null,
    noContext: NO_CONTEXT_TOKENS.some((token) => text.includes(token)),
    hasText: text.length > 0,
  };
}

/** 对照摘要的每一格 */
export interface CompareCell {
  key: string;
  label: string;
  rag: string;
  direct: string;
  /** 差异色调：rag 更好 / direct 更好 / 持平 */
  tone: 'rag' | 'direct' | 'tie';
}

/** 耗时格式：1.2s / 320ms */
export function formatElapsed(ms: number | null): string {
  if (ms === null || ms <= 0) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

/**
 * 差异摘要行（F06 的核心产出）。
 *
 * 四格：字数 / 引用 / 耗时 / 诚实度。
 *
 * - 字数：多者为「更详尽」，但**不判优劣** —— 冗长不等于更好，所以只有明确差距
 *   （相差 ≥ 20%）才标色，否则记为持平。
 * - 引用：查资料侧有引用就是它的结构性优势，direct 侧恒为 0。
 * - 耗时：查资料要多花检索时间，这是它的代价，所以 direct 更快时标 direct 色。
 * - 诚实度：查资料侧说「资料中没有提到」是**正确行为**（不编造），
 *   所以这种情况标 rag 色而不是扣分。
 */
export function compareCells(rag: SideMetrics, direct: SideMetrics): CompareCell[] {
  const charDiff =
    rag.chars === 0 || direct.chars === 0
      ? 0
      : (rag.chars - direct.chars) / Math.max(rag.chars, direct.chars);
  const charTone: CompareCell['tone'] =
    Math.abs(charDiff) < 0.2 ? 'tie' : charDiff > 0 ? 'rag' : 'direct';

  const citeTone: CompareCell['tone'] =
    rag.citations === direct.citations ? 'tie' : rag.citations > direct.citations ? 'rag' : 'direct';

  const elapsedTone: CompareCell['tone'] =
    rag.elapsedMs === null || direct.elapsedMs === null
      ? 'tie'
      : rag.elapsedMs <= direct.elapsedMs
        ? 'rag'
        : 'direct';

  return [
    {
      key: 'chars',
      label: '字数',
      rag: String(rag.chars),
      direct: String(direct.chars),
      tone: charTone,
    },
    {
      key: 'citations',
      label: '引用',
      rag: String(rag.citations),
      direct: String(direct.citations),
      tone: citeTone,
    },
    {
      key: 'elapsed',
      label: '耗时',
      rag: formatElapsed(rag.elapsedMs),
      direct: formatElapsed(direct.elapsedMs),
      tone: elapsedTone,
    },
    {
      key: 'honesty',
      label: '资料诚实度',
      rag: rag.noContext ? '如实说没有' : '有作答',
      direct: direct.noContext ? '如实说没有' : '凭知识作答',
      // 查资料侧如实说「没有」是防幻觉的正确行为，不是缺陷。
      tone: rag.noContext ? 'rag' : 'tie',
    },
  ];
}

/**
 * 一句话结论。
 *
 * 优先说「查资料多知道了什么」，其次是「直接答在编」，最后才是中性的持平提示。
 * 顺序很重要 —— 用户看对照是为了判断「值不值得为 RAG 付出检索成本」。
 */
export function compareVerdict(rag: SideMetrics, direct: SideMetrics): string {
  if (!rag.hasText && !direct.hasText) return '两侧都还没有结果';
  if (!direct.hasText) return '直接答还没有结果，对照暂不成立';
  if (!rag.hasText) return '查资料侧还没有结果';

  if (rag.noContext && !direct.noContext) {
    return '查资料侧如实说「资料中没有」，直接答仍在作答 —— 后者可能是在编。';
  }
  if (rag.citations > 0 && direct.citations === 0) {
    return '查资料侧给出了可核对的来源，直接答无引用，结论需自行判断可靠性。';
  }
  if (rag.citations === 0 && direct.citations === 0) {
    return '两侧都没有引用：本次检索未命中，对照只能看措辞差异。';
  }
  return '两侧都给出了带来源的答案，差别主要在看措辞与详略。';
}
