import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import ListSkeleton from '@/components/ListSkeleton.vue';
import RunHistory from '@/features/eval/components/RunHistory.vue';
import { DOC_STATUS_META } from '@/constants/app';

/**
 * P6 打磨项：空态 / 骨架屏 / 错误态全覆盖。
 *
 * 这一组测试不是「组件渲染得出来」的烟雾测试，而是守一条规格：
 * **每个列表页三态齐备**（加载中 / 空 / 出错）。少一个态，
 * 用户在看到空白页时无从判断是「还没数据」还是「请求挂了」。
 */

/** 挂载选项：RunHistory 里有 el-button，不装 Element Plus 会刷一堆 resolve 警告。 */
const global = { plugins: [ElementPlus] };

describe('骨架屏（ListSkeleton）', () => {
  it('默认 4 行，并带读屏可读的加载文案', () => {
    const wrapper = mount(ListSkeleton);

    expect(wrapper.findAll('.skeleton__row')).toHaveLength(4);
    expect(wrapper.attributes('role')).toBe('status');
    expect(wrapper.attributes('aria-label')).toBe('正在加载…');
    // 视觉隐藏但仍在 DOM 里，读屏软件能读到
    expect(wrapper.get('.skeleton__sr').text()).toBe('正在加载…');
  });

  it('行数与文案可定制，装饰块对读屏隐藏', () => {
    const wrapper = mount(ListSkeleton, { props: { rows: 6, label: '正在加载片段…' } });

    expect(wrapper.findAll('.skeleton__row')).toHaveLength(6);
    expect(wrapper.attributes('aria-label')).toBe('正在加载片段…');
    const row = wrapper.get('.skeleton__row');
    expect(row.attributes('aria-hidden')).toBe('true');
  });

  it('骨架条有节奏差异，不是一堆等宽灰块', () => {
    const wrapper = mount(ListSkeleton, { props: { rows: 6 } });

    const wide = wrapper.findAll('.skeleton__row--wide');
    // i % 3 === 1 的行更宽 → 6 行里有 2 行
    expect(wide).toHaveLength(2);
  });
});

describe('列表三态：加载中 / 出错 / 空', () => {
  const runs = [
    {
      id: 'r1',
      createdAt: 1_700_000_000_000,
      finishedAt: 1_700_000_010_000,
      status: 'SUCCEEDED' as const,
      progress: 100,
      stats: { total: 10, passedDirect: 3, passedRag: 9 },
      mode: 'both' as const,
      k: 3,
    },
  ];

  it('加载中优先于出错与空态', () => {
    const wrapper = mount(RunHistory, {
      global,
      props: { runs: [], loading: true, error: '网络挂了' },
    });

    expect(wrapper.find('[data-testid="history-loading"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="history-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="history-empty"]').exists()).toBe(false);
  });

  it('出错态显示后端文案，且不再显示「还没记录」', () => {
    const wrapper = mount(RunHistory, {
      global,
      props: { runs: [], loading: false, error: '历史加载失败' },
    });

    expect(wrapper.get('[data-testid="history-error"]').text()).toBe('历史加载失败');
    expect(wrapper.find('[data-testid="history-empty"]').exists()).toBe(false);
  });

  it('无数据且无错误才是空态', () => {
    const wrapper = mount(RunHistory, {
      global,
      props: { runs: [], loading: false, error: null },
    });

    expect(wrapper.get('[data-testid="history-empty"]').text()).toContain('还没有评测记录');
  });

  it('有数据时三态都不出现，只出表格', () => {
    const wrapper = mount(RunHistory, { global, props: { runs, loading: false, error: null } });

    expect(wrapper.find('[data-testid="history-loading"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="history-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="history-empty"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="history-row-r1"]').exists()).toBe(true);
  });
});

describe('六态徽标的色调映射', () => {
  it('六种资料状态各自有 label 与 tone，无一遗漏', () => {
    const statuses = [
      'UPLOADING',
      'PARSING',
      'INDEXED',
      'FAILED',
      'NEEDS_REBUILD',
      'DISABLED',
    ] as const;

    for (const status of statuses) {
      const meta = DOC_STATUS_META[status];
      expect(meta, `缺少 ${status} 的展示元数据`).toBeTruthy();
      expect(meta.label.length).toBeGreaterThan(0);
      expect(['ok', 'warn', 'error', 'muted', 'info']).toContain(meta.tone);
    }
  });

  it('语义对的色调不能反：入库=ok、待重建=warn、失败=error、停用=muted', () => {
    expect(DOC_STATUS_META.INDEXED.tone).toBe('ok');
    expect(DOC_STATUS_META.NEEDS_REBUILD.tone).toBe('warn');
    expect(DOC_STATUS_META.FAILED.tone).toBe('error');
    expect(DOC_STATUS_META.DISABLED.tone).toBe('muted');
  });
});
