import { computed, ref } from 'vue';
import type { EvalQuestion } from '@/types/api';
import * as evalApi from '@/api/modules/eval';
import { ApiError } from '@/api';
import { downloadCsv, csvTimestamp, toCsv } from '@/utils/csv';

/**
 * 题库管理状态（P5-08）。
 *
 * 为什么单独抽一个 composable：题库是**用户数据**，会持续增长；管理界面的增删改、
 * 导入导出、启停都要自己的一套加载态与错误态，塞进 useBatchRun 会让那个「跑评测」
 * 的状态机变得又长又难读。
 */
export type QuestionDraft = {
  code: string;
  type: string;
  question: string;
  keywords: string;
  evidence: string;
};

export function useQuestionBank() {
  const questions = ref<EvalQuestion[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const busyCode = ref<string | null>(null);
  const saving = ref(false);
  const importing = ref(false);
  const exporting = ref(false);

  /** 编辑器：null = 关着；code 为空串 = 新建 */
  const editing = ref<QuestionDraft | null>(null);

  const enabledCount = computed(() => questions.value.filter((q) => q.enabled).length);
  const disabledCount = computed(() => questions.value.filter((q) => !q.enabled).length);

  async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      questions.value = await evalApi.listAllQuestions();
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '题库加载失败';
    } finally {
      loading.value = false;
    }
  }

  function openCreate(): void {
    editing.value = { code: '', type: 'single', question: '', keywords: '', evidence: '' };
  }

  function openEdit(q: EvalQuestion): void {
    editing.value = {
      code: q.id,
      type: q.type,
      question: q.question,
      keywords: q.keywords,
      evidence: q.evidence,
    };
  }

  function closeEdit(): void {
    editing.value = null;
  }

  /**
   * 保存题目：code 为空走新建，否则走更新。
   *
   * @returns 成功返回 true，失败返回 false 并把错误挂在 error 上
   */
  async function save(draft: QuestionDraft): Promise<boolean> {
    if (saving.value) return false;
    if (draft.question.trim() === '') {
      error.value = '题面不能为空';
      return false;
    }
    saving.value = true;
    error.value = null;
    try {
      if (draft.code.trim() === '') {
        await evalApi.createQuestion({
          type: draft.type,
          question: draft.question,
          keywords: draft.keywords,
          evidence: draft.evidence,
        });
      } else {
        await evalApi.updateQuestion(draft.code, {
          type: draft.type,
          question: draft.question,
          keywords: draft.keywords,
          evidence: draft.evidence,
        });
      }
      await load();
      editing.value = null;
      return true;
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '保存失败';
      return false;
    } finally {
      saving.value = false;
    }
  }

  /** 停用 / 启用；停用不删行，历史评测照常可读。 */
  async function toggleEnabled(q: EvalQuestion): Promise<void> {
    if (busyCode.value) return;
    busyCode.value = q.id;
    try {
      const next = await evalApi.setQuestionEnabled(q.id, !q.enabled);
      const target = questions.value.find((item) => item.id === q.id);
      if (target) target.enabled = next.enabled;
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '操作失败';
    } finally {
      busyCode.value = null;
    }
  }

  /** 删除；内置种子题会被后端拒绝（只能停用）。 */
  async function remove(q: EvalQuestion): Promise<boolean> {
    if (busyCode.value) return false;
    busyCode.value = q.id;
    error.value = null;
    try {
      await evalApi.deleteQuestion(q.id);
      questions.value = questions.value.filter((item) => item.id !== q.id);
      return true;
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '删除失败';
      return false;
    } finally {
      busyCode.value = null;
    }
  }

  async function exportCsv(): Promise<void> {
    if (exporting.value) return;
    exporting.value = true;
    try {
      const blob = await evalApi.exportQuestions();
      // 走 downloadCsv 而不是直接塞 Blob：导出要带 UTF-8 BOM，Excel 才不乱码。
      const text = await blob.text();
      downloadCsv(`题库-${csvTimestamp()}.csv`, toCsv(parseCsv(text)));
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '导出失败';
    } finally {
      exporting.value = false;
    }
  }

  async function importCsv(csv: string): Promise<{ created: number; skipped: number; errors: string[] } | null> {
    if (importing.value) return null;
    importing.value = true;
    error.value = null;
    try {
      const result = await evalApi.importQuestions(csv);
      await load();
      return result;
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '导入失败';
      return null;
    } finally {
      importing.value = false;
    }
  }

  return {
    questions,
    loading,
    error,
    busyCode,
    saving,
    importing,
    exporting,
    editing,
    enabledCount,
    disabledCount,
    load,
    openCreate,
    openEdit,
    closeEdit,
    save,
    toggleEnabled,
    remove,
    exportCsv,
    importCsv,
  };
}

/**
 * CSV 文本 → 二维表。
 *
 * 只做够用的解析：支持双引号包裹、内部引号翻倍、单元格内换行。题库导出就是这几列，
 * 不需要引一个完整的 RFC4180 解析库。
 */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  // BOM 先去掉，否则第一列会带一个看不见的 \ufeff
  const body = text.replace(/^\ufeff/, '');
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (quoted) {
      if (ch === '"') {
        if (body[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }
    if (ch === '"') {
      quoted = true;
    } else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else if (ch !== '\r') {
      cell += ch;
    }
  }
  if (cell !== '' || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}
