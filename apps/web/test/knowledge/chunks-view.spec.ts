import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { createPinia, setActivePinia } from 'pinia';
import { createRouter, createMemoryHistory, type Router } from 'vue-router';
import ChunksView from '@/features/knowledge/views/ChunksView.vue';
import { resetState } from '@/mocks/state';

/**
 * 片段浏览页集成（P4-B 拓展 B + F05 跳转定位）。
 *
 * 真走 MSW：六份资料 → 约 40 条片段；断言重点是
 *  ① 按文档 / 章节 / 关键词 / 类型四类筛选真的收敛
 *  ② ?chunk_id= 跳进来能定位到那条片段（高亮 + 定位条）
 *  ③ 「相邻并排」把 overlap 那段文字显式标出来
 */

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/knowledge', name: 'knowledge', component: { template: '<div />' } },
      { path: '/knowledge/chunks', name: 'chunks', component: { template: '<div />' } },
    ],
  });
}

async function mountPage(query: Record<string, string> = {}) {
  const router = makeRouter();
  await router.push({ name: 'chunks', query });
  await router.isReady();
  const wrapper = mount(ChunksView, {
    global: { plugins: [ElementPlus, router] },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, router };
}

async function waitFor(check: () => boolean, timeout = 6000, label = '条件'): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await flushPromises();
    if (check()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error(`等待超时：${label}`);
}

function cardIds(wrapper: ReturnType<typeof mount>): string[] {
  return wrapper.findAll('[data-testid^="chunk-card-"]').map((el) => el.attributes('data-testid')!);
}

describe('片段浏览页（P4-B）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('挂载后加载全部片段并按文档分组', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    const total = Number(
      /共 (\d+) 条片段/.exec(wrapper.get('[data-testid="chunk-count"]').text())?.[1] ?? '0',
    );
    // 六份资料按 180/30 切分 → 15 条片段（D01 2 / D02 2 / D03 3 / D04 2 / D05 3 / D06 3）
    expect(total).toBe(15);
    expect(wrapper.findAll('[data-testid^="chunk-card-"]')).toHaveLength(15);

    // 六份资料都在左栏
    for (const id of ['D01', 'D02', 'D03', 'D04', 'D05', 'D06']) {
      expect(wrapper.find(`[data-testid="doc-filter-${id}"]`).exists()).toBe(true);
    }
    wrapper.unmount();
  });

  it('按资料筛选只留该文档的片段', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    await wrapper.get('[data-testid="doc-filter-D02"]').trigger('click');
    await flushPromises();

    const ids = cardIds(wrapper);
    expect(ids.length).toBeGreaterThan(0);
    expect(ids.every((id) => id.includes('D02-C'))).toBe(true);
    wrapper.unmount();
  });

  it('关键词过滤命中正文（续借）', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    // el-input 的根元素就是 <input>，data-testid 落在它身上
    const input = wrapper.get('[data-testid="chunk-keyword"]');
    await input.setValue('续借');
    await flushPromises();

    const cards = wrapper.findAll('[data-testid^="chunk-card-"]');
    expect(cards.length).toBeGreaterThan(0);
    expect(cards.length).toBeLessThan(15);
    // 每条卡片的正文都真的含「续借」，且被 <mark> 标出来了
    for (const card of cards) {
      expect(card.text()).toContain('续借');
      expect(card.find('mark').exists()).toBe(true);
    }
    wrapper.unmount();
  });

  it('关键词无命中时显示空态而不是崩', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    await wrapper.get('[data-testid="chunk-keyword"]').setValue('这段文字一定不存在zzz');
    await flushPromises();

    expect(wrapper.find('[data-testid="chunks-empty"]').exists()).toBe(true);
    expect(wrapper.findAll('[data-testid^="chunk-card-"]')).toHaveLength(0);
    wrapper.unmount();
  });

  it('?chunk_id= 跳进来能定位并高亮（F05 引用卡跳转）', async () => {
    const { wrapper } = await mountPage({ chunk_id: 'D02-C002', doc: '02_借阅规则.md' });
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    // 定位条出现且写的是目标片段
    const locator = wrapper.get('[data-testid="chunk-locator"]');
    expect(locator.text()).toContain('D02-C002');
    expect(locator.text()).toContain('来自引用卡');

    // 目标卡片带 focused 标记
    const focused = wrapper.get('[data-testid="chunk-card-D02-C002"]');
    expect(focused.attributes('data-focused')).toBe('true');
    expect(focused.classes()).toContain('chunk-card--focused');

    // 其它卡片不是 focused
    const others = wrapper
      .findAll('[data-testid^="chunk-card-"]')
      .filter((c) => c.attributes('data-testid') !== 'chunk-card-D02-C002');
    expect(others.every((c) => c.attributes('data-focused') === 'false')).toBe(true);

    // 取消定位后高亮消失
    await wrapper.get('[data-testid="chunk-locator-reset"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="chunk-locator"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="chunk-card-D02-C002"]').attributes('data-focused')).toBe(
      'false',
    );
    wrapper.unmount();
  });

  it('相邻并排显示真实重叠字数与重叠文字（拓展 B）', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    // 点第一张卡片之外的「观察相邻」，取一个中间片段
    const cards = wrapper.findAll('[data-testid^="chunk-card-"]');
    expect(cards.length).toBeGreaterThan(2);
    const targetId = cards[1]!.attributes('data-testid')!.replace('chunk-card-', '');

    await wrapper.get(`[data-testid="chunk-focus-${targetId}"]`).trigger('click');
    await flushPromises();

    const panel = wrapper.get('[data-testid="overlap-panel"]');
    expect(panel.exists()).toBe(true);

    // 180/30 建库 → 相邻片段重叠 30 字
    const stat = wrapper.get('[data-testid="overlap-length"]').text();
    const overlap = Number(/重叠 (\d+) 字/.exec(stat)?.[1] ?? '0');
    expect(overlap).toBe(30);

    // 重叠文字非空，且左右两栏都把它标成 <mark>
    const overlapText = wrapper.get('[data-testid="overlap-text"]').text().trim();
    expect(overlapText.length).toBe(overlap);
    expect(wrapper.get('[data-testid="overlap-left"]').find('mark').text()).toBe(overlapText);
    expect(wrapper.get('[data-testid="overlap-right"]').find('mark').text()).toBe(overlapText);

    // 关闭后消失
    await wrapper.get('[data-testid="overlap-close"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="overlap-panel"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it('复制片段正文调用剪贴板', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      writable: true,
      configurable: true,
      value: { writeText },
    });

    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    const first = wrapper.findAll('[data-testid^="chunk-card-"]')[0]!;
    const id = first.attributes('data-testid')!.replace('chunk-card-', '');
    await wrapper.get(`[data-testid="chunk-copy-${id}"]`).trigger('click');
    await flushPromises();

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0]![0]).toBe(first.get('[data-testid="chunk-text"]').text());
    wrapper.unmount();
  });

  it('清除筛选后回到全量', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    const all = wrapper.findAll('[data-testid^="chunk-card-"]').length;
    await wrapper.get('[data-testid="doc-filter-D01"]').trigger('click');
    await flushPromises();
    const narrowed = wrapper.findAll('[data-testid^="chunk-card-"]').length;
    expect(narrowed).toBeLessThan(all);

    await wrapper.get('[data-testid="chunks-clear"]').trigger('click');
    await flushPromises();
    expect(wrapper.findAll('[data-testid^="chunk-card-"]').length).toBe(all);
    wrapper.unmount();
  });

  it('章节树点击后只留该章节下的片段，再点取消', async () => {
    const { wrapper } = await mountPage();
    await waitFor(() => wrapper.findAll('[data-testid^="chunk-card-"]').length > 0, 6000, '片段列表');

    const all = wrapper.findAll('[data-testid^="chunk-card-"]').length;
    // 六份资料各有一个一级标题 → 树里 6 个节点，每个只覆盖自己文档的片段
    const nodes = wrapper.findAll('[data-testid^="heading-node-"]');
    expect(nodes.length).toBe(6);

    const node = nodes[0]!;
    const nodeKey = node.attributes('data-testid')!.replace('heading-node-', '');
    const expectCount = Number(node.get('.htree__count').text());
    expect(expectCount).toBeLessThan(all);

    await node.trigger('click');
    await flushPromises();
    expect(wrapper.findAll('[data-testid^="chunk-card-"]').length).toBe(expectCount);

    // 再点一次同一节点 = 取消选中，回到全量
    await wrapper.get(`[data-testid="heading-node-${nodeKey}"]`).trigger('click');
    await flushPromises();
    expect(wrapper.findAll('[data-testid^="chunk-card-"]').length).toBe(all);
    wrapper.unmount();
  });
});
