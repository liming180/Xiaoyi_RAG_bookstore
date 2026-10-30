import { computed, ref } from 'vue';
import { K_DEFAULT, K_MAX, K_MIN, STORAGE_KEYS } from '@/constants/app';
import { readStorage, writeStorage } from '@/utils/storage';
import type { AnswerMode } from '@/types/api';

const MODES: AnswerMode[] = ['rag', 'direct', 'both'];

function readMode(): AnswerMode {
  const raw = readStorage(STORAGE_KEYS.mode);
  return MODES.includes(raw as AnswerMode) ? (raw as AnswerMode) : 'rag';
}

function readK(): number {
  const raw = readStorage(STORAGE_KEYS.k);
  // 注意：Number(null) === 0，必须先判 null，否则默认值会被夹成 K_MIN
  if (raw === null || raw.trim() === '') return K_DEFAULT;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return K_DEFAULT;
  return Math.min(K_MAX, Math.max(K_MIN, Math.round(parsed)));
}

/**
 * 提问参数（F06 模式 + F07 检索数量）。
 *
 * 为什么不用 Pinia：这两个参数只有对话页用，且必须跨「清空对话」保留 ——
 * 用 localStorage 持久化 + 组合式函数即可，避免把 UI 局部状态塞进全局 store。
 */
export function useQueryPrefs() {
  const mode = ref<AnswerMode>(readMode());
  const k = ref<number>(readK());

  function setMode(next: AnswerMode): void {
    mode.value = next;
    writeStorage(STORAGE_KEYS.mode, next);
  }

  function setK(next: number): void {
    const clamped = Math.min(K_MAX, Math.max(K_MIN, Math.round(next)));
    k.value = clamped;
    writeStorage(STORAGE_KEYS.k, String(clamped));
  }

  const modeLabel = computed(() => (mode.value === 'rag' ? '查资料' : mode.value === 'direct' ? '直接答' : '对照'));

  return { mode, k, modeLabel, setMode, setK, K_MIN, K_MAX, K_DEFAULT };
}
