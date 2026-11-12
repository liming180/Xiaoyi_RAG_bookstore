import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { createPinia, setActivePinia } from 'pinia';
import StatusBadge from '@/features/knowledge/components/StatusBadge.vue';
import DocumentTable from '@/features/knowledge/components/DocumentTable.vue';
import type { DocumentMeta, DocumentStatus } from '@/types/api';
import { resetState } from '@/mocks/state';

function doc(over: Partial<DocumentMeta> = {}): DocumentMeta {
  return {
    id: 'D01',
    name: '01_借阅规则.md',
    title: '借阅规则',
    tags: ['借阅', '规则'],
    version: 'v1',
    charCount: 512,
    chunkCount: 3,
    status: 'INDEXED',
    verified: true,
    updatedAt: '2026-01-01T00:00:00Z',
    error: null,
    ...over,
  };
}

const STATUSES: DocumentStatus[] = [
  'UPLOADING',
  'PARSING',
  'INDEXED',
  'FAILED',
  'NEEDS_REBUILD',
  'DISABLED',
];

const EXPECTED_LABEL: Record<DocumentStatus, string> = {
  UPLOADING: '上传中',
  PARSING: '解析中',
  INDEXED: '已入库',
  FAILED: '失败',
  NEEDS_REBUILD: '待重建',
  DISABLED: '已停用',
};

const EXPECTED_TONE: Record<DocumentStatus, string> = {
  UPLOADING: 'badge--info',
  PARSING: 'badge--info',
  INDEXED: 'badge--ok',
  FAILED: 'badge--error',
  NEEDS_REBUILD: 'badge--warn',
  DISABLED: 'badge--muted',
};

describe('六态状态徽标（F01/F03）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  for (const status of STATUSES) {
    it(`${status} 渲染 ${EXPECTED_LABEL[status]}`, () => {
      const wrapper = mount(StatusBadge, {
        props: { status },
        global: { plugins: [ElementPlus] },
      });
      const badge = wrapper.get(`[data-testid="doc-status-${status}"]`);
      expect(badge.text()).toBe(EXPECTED_LABEL[status]);
      expect(badge.attributes('data-status')).toBe(status);
      expect(badge.classes()).toContain(EXPECTED_TONE[status]);
    });
  }

  it('六态颜色语义互不相同（除上传中/解析中同为 info）', () => {
    const tones = new Set(STATUSES.map((s) => EXPECTED_TONE[s]));
    expect(tones.size).toBe(5);
  });
});

describe('资料表格（F01）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('渲染行、状态徽标与未核实标记', () => {
    const wrapper = mount(DocumentTable, {
      props: {
        documents: [
          doc(),
          doc({
            id: 'D06',
            name: '06_成员留言摘录.md',
            title: '成员留言摘录',
            verified: false,
            status: 'NEEDS_REBUILD',
          }),
        ],
      },
      global: { plugins: [ElementPlus] },
    });

    expect(wrapper.findAll('tbody tr')).toHaveLength(2);
    expect(wrapper.find('[data-testid="doc-row-D01"]').attributes('data-status')).toBe('INDEXED');
    expect(wrapper.find('[data-testid="doc-status-INDEXED"]').text()).toBe('已入库');
    expect(wrapper.find('[data-testid="doc-row-D06"]').text()).toContain('未核实');
    expect(wrapper.find('[data-testid="doc-row-D01"]').text()).not.toContain('未核实');
  });

  it('加载中显示占位，不渲染表格', () => {
    const wrapper = mount(DocumentTable, {
      props: { documents: [], loading: true },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.find('[data-testid="doc-loading"]').exists()).toBe(true);
    expect(wrapper.find('table').exists()).toBe(false);
  });

  it('错误态显示后端消息', () => {
    const wrapper = mount(DocumentTable, {
      props: { documents: [], error: '资料列表加载失败' },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.get('[data-testid="doc-error"]').text()).toBe('资料列表加载失败');
  });

  it('空列表给出上传引导', () => {
    const wrapper = mount(DocumentTable, {
      props: { documents: [] },
      global: { plugins: [ElementPlus] },
    });
    expect(wrapper.get('[data-testid="doc-empty"]').text()).toContain('先上传');
  });

  it('启停用按钮文案随状态翻转，上传中不可点', async () => {
    const wrapper = mount(DocumentTable, {
      props: {
        documents: [doc(), doc({ id: 'D07', status: 'DISABLED' }), doc({ id: 'D08', status: 'PARSING' })],
      },
      global: { plugins: [ElementPlus] },
    });

    expect(wrapper.get('[data-testid="doc-toggle-D01"]').text()).toBe('停用');
    expect(wrapper.get('[data-testid="doc-toggle-D07"]').text()).toBe('启用');
    expect(wrapper.get('[data-testid="doc-toggle-D08"]').attributes('disabled')).toBeDefined();

    await wrapper.get('[data-testid="doc-toggle-D01"]').trigger('click');
    const emitted = wrapper.emitted('toggle');
    expect(emitted).toHaveLength(1);
    expect((emitted![0]![0] as DocumentMeta).id).toBe('D01');
    expect(emitted![0]![1]).toBe(false);
  });

  it('删除与查看全文上抛整条资料', async () => {
    const wrapper = mount(DocumentTable, {
      props: { documents: [doc()] },
      global: { plugins: [ElementPlus] },
    });

    await wrapper.get('[data-testid="doc-delete-D01"]').trigger('click');
    expect((wrapper.emitted('remove')![0]![0] as DocumentMeta).name).toBe('01_借阅规则.md');

    await wrapper.get('.doc-table__name').trigger('click');
    expect((wrapper.emitted('view')![0]![0] as DocumentMeta).id).toBe('D01');
  });
});
