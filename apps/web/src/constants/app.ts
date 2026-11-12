/**
 * 全局常量。集中放置，避免魔法数字散落在组件里。
 */

export const APP_TITLE = import.meta.env.VITE_APP_TITLE ?? '小忆 RAG 知识库问答';

/** F07：k 可选范围（后端校验 1..10，前端按验收清单收敛到 1..5，默认 3） */
export const K_MIN = 1;
export const K_MAX = 5;
export const K_DEFAULT = 3;

/** F02：分块参数约束 */
export const CHUNK_SIZE_MIN = 50;
export const CHUNK_SIZE_MAX = 1000;
export const CHUNK_SIZE_DEFAULT = 180;
export const OVERLAP_DEFAULT = 30;

/** F04：输入长度上限 */
export const QUESTION_MAX_LENGTH = 1000;

/** F01：上传约束 */
export const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;
export const ALLOWED_EXTENSIONS = ['.md', '.txt'] as const;

/** F11：未核实资料（教学数据里固定这一份） */
export const UNVERIFIED_DOCS = ['06_成员留言摘录.md'];

/** F03：系统状态轮询间隔（ms） */
export const STATUS_POLL_INTERVAL = 30_000;

/** 建库任务轮询间隔（ms） */
export const INDEX_TASK_POLL_INTERVAL = 1_000;

/** 批量评测轮询间隔（ms） */
export const EVAL_POLL_INTERVAL = 1_000;

/** 阶段文案：SSE status 事件 → 用户可读 */
export const STAGE_LABELS: Record<string, string> = {
  rewriting: '正在改写问题',
  retrieving: '正在检索资料',
  reranking: '正在重排结果',
  generating: '正在回答',
};

/** 建库阶段文案 */
export const INDEX_STAGE_LABELS: Record<string, string> = {
  parsing: '解析资料',
  splitting: '切分片段',
  embedding: '生成向量',
  summarizing: '生成摘要',
  done: '完成',
};

/** 文档状态徽标 */
export const DOC_STATUS_META: Record<
  string,
  { label: string; tone: 'ok' | 'warn' | 'error' | 'muted' | 'info' }
> = {
  UPLOADING: { label: '上传中', tone: 'info' },
  PARSING: { label: '解析中', tone: 'info' },
  INDEXED: { label: '已入库', tone: 'ok' },
  FAILED: { label: '失败', tone: 'error' },
  NEEDS_REBUILD: { label: '待重建', tone: 'warn' },
  DISABLED: { label: '已停用', tone: 'muted' },
};

/** 模式选项（F06） */
export const MODE_OPTIONS = [
  { value: 'rag', label: '查资料', hint: '先检索知识库再回答，带来源编号' },
  { value: 'direct', label: '直接答', hint: '不查资料，仅凭模型自身知识回答' },
  { value: 'both', label: '对照', hint: '同一问题并排显示两种回答' },
] as const;

/** localStorage 键 */
export const STORAGE_KEYS = {
  mode: 'xiaoyi.mode',
  k: 'xiaoyi.k',
  theme: 'xiaoyi.theme',
  conversationId: 'xiaoyi.conversationId',
} as const;
