<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import type { EvalQuestion } from '@/types/api';
import ListSkeleton from '@/components/ListSkeleton.vue';
import { typeHint, typeLabel, typeTone } from '../composables/batch';
import type { QuestionDraft } from '../composables/useQuestionBank';

/**
 * QuestionBank —— 题库管理（P5-08）。
 *
 * 解决的问题：旧实现把 13 道题写死在 jar 里的 CSV，资料一多就无题可测。
 * 这里把题库变成用户自己的数据：新增、编辑、停用、删除、CSV 导入导出。
 *
 * 两条刻意的约束：
 *   1. 内置种子题只能停用不能删 —— 种子只在题库为空时灌一次，删了拿不回来；
 *   2. 停用而不是删除 —— 历史评测的题号快照还引用着它，硬删会让历史详情变成孤儿。
 */
const props = defineProps<{
  questions: EvalQuestion[];
  loading?: boolean;
  error?: string | null;
  busyCode?: string | null;
  saving?: boolean;
  importing?: boolean;
  exporting?: boolean;
  /**
   * 编辑器草稿，由父层的 useQuestionBank 管理。
   *
   * <p>为什么状态放在父层而不是本组件：保存成功后父层要「关编辑器 + 刷新题库 +
   * 刷新批量页选题」，三件事必须一起发生。状态放在子组件里，父层就只能靠事件
   * 反推，容易出现「数据已经存了但弹窗还开着」的半吊子状态。
   */
  editing?: QuestionDraft | null;
}>();
const emit = defineEmits<{
  create: [];
  edit: [EvalQuestion];
  /** 保存草稿：由父层 useQuestionBank 落库，成功后父层负责关编辑器 */
  save: [QuestionDraft];
  remove: [EvalQuestion];
  toggleEnabled: [EvalQuestion];
  import: [string];
  export: [];
  refresh: [];
  closeEditor: [];
  'update:editing': [QuestionDraft];
}>();

const TYPE_OPTIONS = [
  { value: 'single', label: '单份资料可答' },
  { value: 'cross', label: '需综合多篇' },
  { value: 'out', label: '库外题（考察拒答）' },
];

/**
 * 编辑器草稿：本地持有。
 *
 * <p>不从 props 派生：草稿每个字段都要双向绑定，若它由 props 派生、改动再
 * emit 回父层改 props，ElSelect 内部同步会与这件事成环（实测直接报
 * Maximum recursive updates）。父层只负责「打开哪个题」，草稿内容归本组件。
 */
const draft = ref<QuestionDraft | null>(null);

/** 父层打开编辑器时把初始值灌进来（watch props.editing 的身份变化） */
watch(
  () => props.editing,
  (next) => {
    if (next) draft.value = { ...next };
    else draft.value = null;
  },
  { immediate: true },
);

/** 只看停用题 */
const onlyDisabled = ref(false);
const keyword = ref('');

/**
 * 判分关键词折叠（换肤 B3）。
 *
 * 问题（实测截图）：T01 的关键词是
 * `周六|14:00/14点/下午2点/下午两点|16:00/16点/下午4点/下午四点/到四点/至四点/到4点/至4点`，
 * 在 190px 宽的列里占 3 行，把整张表的行高撑成参差状，扫读时眼睛一直被绊。
 *
 * 方案：默认只显示第一组（`|` 之前），其余收进 +N 徽标；点开看完整串。
 * 用 Set 记录已展开的题号 —— 逐题控制，不搞「一键全展开」（列表一长就失控）。
 */
const expandedKw = ref<Set<string>>(new Set());

function toggleKw(id: string): void {
  const next = new Set(expandedKw.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedKw.value = next;
}

/** 关键词按 `|` 分组（与后端判分规则一致：组间全部命中，组内命中其一） */
function kwGroups(raw: string | null | undefined): string[] {
  if (!raw) return [];
  return raw
    .split('|')
    .map((s) => s.trim())
    .filter((s) => s !== '');
}

const rows = computed(() => {
  const kw = keyword.value.trim();
  return props.questions.filter((q) => {
    if (onlyDisabled.value && q.enabled) return false;
    if (kw === '') return true;
    return q.id.includes(kw) || q.question.includes(kw) || q.keywords.includes(kw);
  });
});

function openEditor(q?: EvalQuestion): void {
  if (q) emit('edit', q);
  else emit('create');
}

function closeEditor(): void {
  draft.value = null;
  emit('closeEditor');
}

/**
 * 草稿是 props（不可直接改），输入时向外抛一个完整新对象。
 *
 * <p>只在本字段真的变化时才 emit：ElSelect 的 model-value 一旦拿到新引用就会
 * 重新同步内部状态，无条件 emit 会让「输入 → 新对象 → 重渲染 → 再输入」成环，
 * Vue 会直接报 Maximum recursive updates。
 */
function patchDraft(patch: Partial<QuestionDraft>): void {
  if (!draft.value) return;
  draft.value = { ...draft.value, ...patch };
}

function onSubmit(): void {
  if (!draft.value) return;
  if (draft.value.question.trim() === '') {
    ElMessage.warning('题面不能为空');
    return;
  }
  emit('save', draft.value);
}

async function onRemove(q: EvalQuestion): Promise<void> {
  if (q.source === 'seed') {
    ElMessage.warning('内置题不能删除，可以改成停用');
    return;
  }
  try {
    await ElMessageBox.confirm(`删除题目 ${q.id}？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    });
    emit('remove', q);
  } catch {
    /* 用户取消 */
  }
}

/* ----------------------------------------------------------- CSV 导入 */

const importOpen = ref(false);
const importText = ref('');
const fileInput = ref<HTMLInputElement | null>(null);

function openImport(): void {
  importOpen.value = true;
  importText.value = '';
}

async function onPickFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  importText.value = await file.text();
  input.value = '';
}

function onImportSubmit(): void {
  if (importText.value.trim() === '') {
    ElMessage.warning('请粘贴 CSV 内容或选择文件');
  } else {
    emit('import', importText.value);
  }
}

/** 下载导入模板：列序与后端导出一致，避免用户不知道有哪几列 */
function downloadTemplate(): void {
  const csv = [
    '题号,类型,问题,关键词,证据文件',
    'S001,单文档,示例问题？,关键词A/同义词A|关键词B,示例资料.md',
    'X001,跨文档,需要两篇资料才能回答的问题？,要点A|要点B,资料1.md与资料2.md',
    'O001,库外,资料库里没有的问题？,,无',
  ].join('\r\n');
  importText.value = csv;
}
</script>

<template>
  <section class="bank" data-testid="question-bank">
    <header class="bank__head">
      <div>
        <h2 class="bank__title">题库</h2>
        <p class="bank__desc">
          资料变多后可以在这里加题。内置 {{ questions.length }} 道题只是种子，可停用、可编辑，自建题题号自动编号。
        </p>
      </div>
      <div class="bank__actions">
        <el-button size="small" data-testid="bank-refresh" @click="emit('refresh')">刷新</el-button>
        <el-button size="small" data-testid="bank-export" :loading="exporting" @click="emit('export')">
          导出 CSV
        </el-button>
        <el-button size="small" data-testid="bank-import-open" @click="openImport">导入 CSV</el-button>
        <el-button size="small" type="primary" data-testid="bank-create" @click="openEditor()">
          新增题目
        </el-button>
      </div>
    </header>

    <div class="bank__filter">
      <el-input
        v-model="keyword"
        size="small"
        placeholder="搜题号 / 题面 / 关键词"
        clearable
        style="max-width: 260px"
        data-testid="bank-search"
      />
      <el-checkbox v-model="onlyDisabled" size="small" data-testid="bank-only-disabled">
        只看停用
      </el-checkbox>
      <span class="bank__count" data-testid="bank-count">
        共 {{ questions.length }} 道 · 启用 {{ questions.filter((q) => q.enabled).length }} · 停用
        {{ questions.filter((q) => !q.enabled).length }}
      </span>
    </div>

    <ListSkeleton v-if="loading" data-testid="bank-loading" :rows="4" label="正在加载题库…" />
    <div v-else-if="error" class="bank__state bank__state--error" data-testid="bank-error">
      {{ error }}
    </div>
    <div v-else-if="rows.length === 0" class="bank__state" data-testid="bank-empty">
      没有匹配的题目。换个关键词，或点「新增题目」。
    </div>

    <table v-else class="bank__table">
      <thead>
        <tr>
          <th class="bank__col-code">题号</th>
          <th class="bank__col-type">题型</th>
          <th>题面</th>
          <th class="bank__col-kw">判分关键词</th>
          <th class="bank__col-evd">证据资料</th>
          <th class="bank__col-state">状态</th>
          <th class="bank__col-op">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="q in rows"
          :key="q.id"
          :data-testid="`bank-row-${q.id}`"
          :class="{ 'bank__row--off': !q.enabled }"
        >
          <td class="bank__col-code">
            <code>{{ q.id }}</code>
          </td>
          <td class="bank__col-type">
            <span class="badge" :class="`badge--${typeTone(q.type)}`" :title="typeHint(q.type)">
              {{ typeLabel(q.type) }}
            </span>
          </td>
          <td class="bank__question">{{ q.question }}</td>
          <td class="bank__col-kw">
            <template v-if="q.keywords">
              <!-- 折叠态：首组 + N；展开态：完整串（保留 | 分组结构） -->
              <div v-if="expandedKw.has(q.id)" class="kw kw--open">
                <code class="kw__full" :data-testid="`bank-kw-full-${q.id}`">{{ q.keywords }}</code>
                <button
                  type="button"
                  class="kw__toggle"
                  :data-testid="`bank-kw-toggle-${q.id}`"
                  @click="toggleKw(q.id)"
                >
                  收起
                </button>
              </div>
              <div v-else class="kw">
                <code class="kw__chip" :title="q.keywords" :data-testid="`bank-kw-${q.id}`">
                  {{ kwGroups(q.keywords)[0] }}
                </code>
                <button
                  v-if="kwGroups(q.keywords).length > 1"
                  type="button"
                  class="kw__more"
                  :title="`展开全部 ${kwGroups(q.keywords).length} 组关键词`"
                  :data-testid="`bank-kw-toggle-${q.id}`"
                  @click="toggleKw(q.id)"
                >
                  +{{ kwGroups(q.keywords).length - 1 }}
                </button>
              </div>
            </template>
            <span v-else class="kw__empty" title="没填关键词的题不参与计分">未填（不计分）</span>
          </td>
          <td class="bank__col-evd">{{ q.evidence || '—' }}</td>
          <td class="bank__col-state">
            <span class="badge" :class="q.enabled ? 'badge--ok' : 'badge--muted'">
              {{ q.enabled ? '启用' : '停用' }}
            </span>
            <span class="bank__source">{{ q.source === 'seed' ? '内置' : '自建' }}</span>
          </td>
          <td class="bank__col-op">
            <el-button
              size="small"
              text
              type="primary"
              :data-testid="`bank-edit-${q.id}`"
              @click="openEditor(q)"
            >
              编辑
            </el-button>
            <el-button
              size="small"
              text
              :loading="busyCode === q.id"
              :data-testid="`bank-toggle-${q.id}`"
              @click="emit('toggleEnabled', q)"
            >
              {{ q.enabled ? '停用' : '启用' }}
            </el-button>
            <el-button
              size="small"
              text
              type="danger"
              :disabled="q.source === 'seed'"
              :title="q.source === 'seed' ? '内置题只能停用' : '删除'"
              :data-testid="`bank-delete-${q.id}`"
              @click="onRemove(q)"
            >
              删除
            </el-button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 编辑器 -->
    <Teleport to="body">
      <div v-if="draft" class="bank-dialog" data-testid="bank-editor" @click.self="closeEditor">
        <div class="bank-dialog__card" role="dialog" aria-modal="true">
          <header class="bank-dialog__head">
            <strong>{{ draft.code ? `编辑 ${draft.code}` : '新增题目' }}</strong>
            <el-button size="small" circle aria-label="关闭" data-testid="bank-editor-close" @click="closeEditor">
              ✕
            </el-button>
          </header>

          <div class="bank-dialog__body">
            <label class="bank-dialog__field">
              <span>题号</span>
              <el-input
                :model-value="draft.code"
                size="small"
                disabled
                placeholder="留空自动编号（S001 / X001 / O001）"
                data-testid="bank-editor-code"
              />
              <small v-if="draft.code" class="bank-dialog__tip">题号已被历史评测引用，不可修改</small>
            </label>

            <label class="bank-dialog__field">
              <span>题型</span>
              <div class="bank-dialog__types" data-testid="bank-editor-type">
                <button
                  v-for="o in TYPE_OPTIONS"
                  :key="o.value"
                  type="button"
                  class="bank-dialog__type"
                  :class="{ 'bank-dialog__type--on': draft.type === o.value }"
                  :data-testid="`bank-editor-type-${o.value}`"
                  @click="patchDraft({ type: o.value })"
                >
                  {{ o.label }}
                </button>
              </div>
            </label>

            <label class="bank-dialog__field">
              <span>题面</span>
              <el-input
                :model-value="draft.question"
                type="textarea"
                :rows="2"
                size="small"
                placeholder="用户会怎么问？"
                data-testid="bank-editor-question"
                @update:model-value="(v: string) => patchDraft({ question: v })"
              />
            </label>

            <label class="bank-dialog__field">
              <span>判分关键词</span>
              <el-input
                :model-value="draft.keywords"
                size="small"
                placeholder="如 4本/4册|21天（组内 / 同义，组间 | 必须全中）"
                data-testid="bank-editor-keywords"
                @update:model-value="(v: string) => patchDraft({ keywords: v })"
              />
              <small class="bank-dialog__tip">留空 = 该题照常跑但不计分（自动判分靠它匹配）</small>
            </label>

            <label class="bank-dialog__field">
              <span>证据资料</span>
              <el-input
                :model-value="draft.evidence"
                size="small"
                placeholder="答案所在的资料文件名；库外题填「无」"
                data-testid="bank-editor-evidence"
                @update:model-value="(v: string) => patchDraft({ evidence: v })"
              />
            </label>
          </div>

          <footer class="bank-dialog__foot">
            <el-button size="small" data-testid="bank-editor-cancel" @click="closeEditor">取消</el-button>
            <el-button
              size="small"
              type="primary"
              :loading="saving"
              data-testid="bank-editor-submit"
              @click="onSubmit"
            >
              保存
            </el-button>
          </footer>
        </div>
      </div>
    </Teleport>

    <!-- 导入 -->
    <Teleport to="body">
      <div v-if="importOpen" class="bank-dialog" data-testid="bank-import" @click.self="importOpen = false">
        <div class="bank-dialog__card" role="dialog" aria-modal="true">
          <header class="bank-dialog__head">
            <strong>导入题库 CSV</strong>
            <el-button size="small" circle aria-label="关闭" data-testid="bank-import-close" @click="importOpen = false">
              ✕
            </el-button>
          </header>

          <div class="bank-dialog__body">
            <p class="bank-dialog__tip">
              列序：题号,类型,问题,关键词,证据文件。表头可省略；题号重复的行会跳过并计数，不会整批失败。
            </p>
            <div class="bank-dialog__row">
              <input
                ref="fileInput"
                type="file"
                accept=".csv,text/csv"
                class="bank-dialog__file"
                data-testid="bank-import-file"
                @change="onPickFile"
              />
              <el-button size="small" text type="primary" data-testid="bank-import-template" @click="downloadTemplate">
                填入模板
              </el-button>
            </div>
            <el-input
              v-model="importText"
              type="textarea"
              :rows="10"
              size="small"
              placeholder="粘贴 CSV 内容，或选择文件"
              data-testid="bank-import-text"
            />
          </div>

          <footer class="bank-dialog__foot">
            <el-button size="small" data-testid="bank-import-cancel" @click="importOpen = false">取消</el-button>
            <el-button
              size="small"
              type="primary"
              :loading="importing"
              data-testid="bank-import-submit"
              @click="onImportSubmit"
            >
              导入
            </el-button>
          </footer>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.bank {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.bank__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.bank__title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
}

.bank__desc {
  margin: 0;
  max-width: 620px;
  font-size: 12px;
  color: var(--muted);
}

.bank__actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.bank__filter {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.bank__count {
  font-size: 12px;
  color: var(--muted);
}

.bank__state {
  padding: 32px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  background: var(--paper);
  border: 1px dashed var(--line);
  border-radius: var(--radius);
}

.bank__state--error {
  color: var(--red);
  border-color: var(--red);
  background: var(--red-soft);
}

.bank__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

.bank__table th {
  padding: 8px 10px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

.bank__table td {
  padding: 10px;
  vertical-align: top;
  border-bottom: 1px solid var(--line);
}

.bank__table tbody tr:last-child td {
  border-bottom: 0;
}

.bank__row--off {
  opacity: 0.62;
}

.bank__col-code {
  width: 68px;
  font-family: var(--font-mono);
  font-size: 12px;
}

.bank__col-type {
  width: 132px;
}

.bank__col-kw {
  width: 180px;
}

.bank__col-evd {
  width: 140px;
  font-size: 12px;
  color: var(--muted);
}

.bank__col-state {
  width: 96px;
}

.bank__col-op {
  width: 190px;
  white-space: nowrap;
}

.bank__question {
  font-weight: 500;
}

/* ---- 判分关键词：折叠 / 展开（换肤 B3） ---- */
.kw {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.kw__chip {
  display: block;
  flex: 0 1 auto;
  min-width: 0;
  max-width: 130px;
  padding: 1px 6px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--teal-dark);
  background: var(--soft);
  border-radius: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kw__more,
.kw__toggle {
  flex: none;
  padding: 1px 6px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--teal);
  background: transparent;
  border: 1px dashed var(--teal-line);
  border-radius: 6px;
  cursor: pointer;
}

.kw__more:hover,
.kw__toggle:hover {
  background: var(--soft);
}

.kw--open {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.kw__full {
  display: block;
  width: 100%;
  padding: 6px 8px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.8;
  color: var(--text);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}

.kw__empty {
  font-size: 11px;
  color: var(--amber);
}

.bank__source {
  margin-left: 4px;
  font-size: 11px;
  color: var(--muted);
}

/* ---------------------------------------------------------- 弹窗 */

.bank-dialog {
  position: fixed;
  inset: 0;
  z-index: 2100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 26, 22, 0.45);
  backdrop-filter: blur(2px);
}

.bank-dialog__card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: min(640px, 100%);
  max-height: min(82vh, 760px);
  overflow: auto;
  padding: 18px 20px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.bank-dialog__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.bank-dialog__body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.bank-dialog__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}

.bank-dialog__tip {
  font-size: 11px;
  color: var(--muted);
}

.bank-dialog__row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bank-dialog__types {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.bank-dialog__type {
  padding: 5px 12px;
  font-size: 12px;
  color: var(--muted);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.bank-dialog__type:hover {
  color: var(--ink);
  border-color: var(--teal);
}

.bank-dialog__type--on {
  color: var(--paper);
  background: var(--teal);
  border-color: var(--teal);
}

.bank-dialog__file {
  font-size: 12px;
}

.bank-dialog__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
}
</style>
