import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { createPinia, setActivePinia } from 'pinia';
import { createRouter, createMemoryHistory, type Router } from 'vue-router';
import EvalView from '@/features/eval/views/EvalView.vue';
import BatchRunner from '@/features/eval/components/BatchRunner.vue';
import ExperimentMatrix from '@/features/eval/components/ExperimentMatrix.vue';
import CandidatePool from '@/features/eval/components/CandidatePool.vue';
import ExperimentBanner from '@/app/layout/ExperimentBanner.vue';
import { useSystemStatusStore } from '@/stores/systemStatus';
import { clearAllListeners, on } from '@/api';
import { getState, resetState } from '@/mocks/state';

/**
 * 评测页集成（P5 / F09 + 套餐 §5 + 套餐 E3）。
 *
 * 真走 MSW：题目 13 道 → 批量对照真跑 → 历史真读 → 候选池真决定 → 实验真轮询。
 * MSW 的 fetch 是宏任务链，`flushPromises()` 只排空微任务，
 * 所以凡「等接口/等轮询回来」的断言一律走 waitFor，不用固定 sleep。
 */

/** 种子题库题量：T01–T13（13 道，与 assets/eval/questions.csv 对齐） */
const QUESTION_COUNT = 13;

let pinia: ReturnType<typeof createPinia>;

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/eval', name: 'eval', component: { template: '<div />' } },
      { path: '/chat', name: 'chat', component: { template: '<div />' } },
    ],
  });
}

async function mountPage(tab = 'batch') {
  const router = makeRouter();
  await router.push({ name: 'eval', query: { tab } });
  await router.isReady();
  const wrapper = mount(EvalView, {
    // 显式传 pinia 而不是只靠 setActivePinia：本文件会额外挂 ExperimentBanner，
    // 两个组件必须落在同一个 store 实例上，否则横幅读不到评测页写的开关。
    global: { plugins: [ElementPlus, router, pinia] },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, router };
}

async function waitFor(check: () => boolean, timeout = 8000, label = '条件'): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await flushPromises();
    if (check()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error(`等待超时：${label}`);
}

describe('评测页（P5）', () => {
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    resetState();
    clearAllListeners();
  });

  it('挂载后默认落在批量对照页签，并拉满 13 道题', async () => {
    const { wrapper } = await mountPage();
    await waitFor(
      () => wrapper.findAll('[data-testid^="pick-"]').length === QUESTION_COUNT,
      8000,
      `${QUESTION_COUNT} 道题`,
    );

    expect(wrapper.find('[data-testid="page-eval"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="tab-batch"]').attributes('aria-selected')).toBe('true');
    expect(wrapper.find('[data-testid="batch-runner"]').exists()).toBe(true);
    // 默认全选
    expect(wrapper.get('[data-testid="question-picker"]').text()).toContain(
      `${QUESTION_COUNT} / ${QUESTION_COUNT}`,
    );
  });

  it('批量对照真跑：结果表 13 行、统计卡与「查资料更好」判定', async () => {
    const { wrapper } = await mountPage();
    await waitFor(
      () => wrapper.findAll('[data-testid^="pick-"]').length === QUESTION_COUNT,
      8000,
      '题目',
    );

    await wrapper.get('[data-testid="batch-start"]').trigger('click');
    await waitFor(
      () => wrapper.findAll('[data-testid^="case-"]').length === QUESTION_COUNT,
      8000,
      `结果表 ${QUESTION_COUNT} 行`,
    );

    expect(wrapper.get('[data-testid="stat-total"]').text()).toContain(String(QUESTION_COUNT));
    // 必须取 .batch__card-value 这一层：卡片里「通过数」和「百分比」是两个相邻元素，
    // Vue 的 whitespace:condense 会把它们之间的空白抹掉，整卡 textContent 拼成
    // "不查资料通过330%"，用正则抽数字会把 3 和 30 粘成 330。
    const cardValue = (testid: string): number =>
      Number(wrapper.get(`[data-testid="${testid}"] .batch__card-value`).text());
    const direct = cardValue('stat-direct');
    const rag = cardValue('stat-rag');
    // F09 验收：查资料通过数必须明显高于不查资料
    expect(rag).toBeGreaterThan(direct);
    expect(wrapper.get('[data-testid="batch-verdict"]').text()).toContain('检索链路有效');

    // 初判徽章与人工核对提示都在
    expect(wrapper.find('[data-testid="rag-badge-T01"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="batch-hint"]').text()).toContain('仍需人工核对');
  });

  it('批量结果可导出 CSV（带 BOM、文件名含时间戳）', async () => {
    const { wrapper } = await mountPage();
    await waitFor(
      () => wrapper.findAll('[data-testid^="pick-"]').length === QUESTION_COUNT,
      8000,
      '题目',
    );
    await wrapper.get('[data-testid="batch-start"]').trigger('click');
    await waitFor(
      () => wrapper.findAll('[data-testid^="case-"]').length === QUESTION_COUNT,
      8000,
      '结果',
    );

    const createSpy = vi.spyOn(URL, 'createObjectURL');
    await wrapper.get('[data-testid="batch-export"]').trigger('click');

    expect(createSpy).toHaveBeenCalledTimes(1);
    const blob = createSpy.mock.calls[0]?.[0] as Blob;
    // 不能用 blob.text() 验 BOM：TextDecoder 解码时会自动吞掉 UTF-8 BOM，
    // 只有看原始字节才知道 BOM 到底写没写。
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect([bytes[0], bytes[1], bytes[2]]).toEqual([0xef, 0xbb, 0xbf]);
    const text = new TextDecoder().decode(bytes);
    expect(text).toContain('题号,题型,问题');
    expect(text).toContain('T01');
  });

  it('页签由 ?tab= 驱动：直接落到历史页签并读回刚才那次运行', async () => {
    // 先真跑一次，让历史里有记录
    const { wrapper, router } = await mountPage();
    await waitFor(
      () => wrapper.findAll('[data-testid^="pick-"]').length === QUESTION_COUNT,
      8000,
      '题目',
    );
    await wrapper.get('[data-testid="batch-start"]').trigger('click');
    await waitFor(
      () => wrapper.findAll('[data-testid^="case-"]').length === QUESTION_COUNT,
      8000,
      '结果',
    );

    await router.push({ name: 'eval', query: { tab: 'history' } });
    await flushPromises();
    await waitFor(
      () => wrapper.findAll('[data-testid^="history-row-"]').length >= 1,
      8000,
      '历史 1 行',
    );

    expect(wrapper.get('[data-testid="tab-history"]').attributes('aria-selected')).toBe('true');
    // 历史页签本身不渲染批量面板；只有点「查看详情」后才在该卡片下方就地展开结果表
    expect(wrapper.find('[data-testid^="history-detail-"]').exists()).toBe(false);

    // 点「查看详情」把结果表内联展开到卡片下方
    const openBtn = wrapper.get('[data-testid^="history-open-"]');
    await openBtn.trigger('click');
    await waitFor(
      () => wrapper.find('[data-testid^="history-detail-"]').exists(),
      8000,
      '历史详情',
    );
    expect(
      wrapper.get('[data-testid^="history-detail-"]').findAll('[data-testid^="case-"]'),
    ).toHaveLength(QUESTION_COUNT);

    /*
     * 详情里不应再出现「跑测试」的控件：
     * 原实现把整个 BatchRunner 塞进详情，选题面板（pick-*）、开始测试按钮
     * 和历史记录混在一起，既误导（以为能改这次结果）又要滚很久才看到结果。
     */
    const detail = wrapper.get('[data-testid^="history-detail-"]');
    expect(detail.find('[data-testid="batch-start"]').exists()).toBe(false);
    expect(detail.find('[data-testid^="pick-"]').exists()).toBe(false);
    // 结果表本体仍在
    expect(detail.find('[data-testid="history-result"]').exists()).toBe(true);
  });

  it('候选池：纳入要先补关键词（可留空）/ 忽略直接生效，且「只看待定」把已处理的藏起来', async () => {
    const st = getState();
    // 种子数据自带一条 pending，先清空才能断言精确条数
    st.candidates.length = 0;
    st.candidates.unshift(
      { id: 'cand-a', question: '续借可以续几次？', source: 'feedback', status: 'pending', createdAt: Date.now() },
      { id: 'cand-b', question: '活动室怎么预约？', source: 'feedback', status: 'pending', createdAt: Date.now() },
    );

    const { wrapper } = await mountPage('candidates');
    // 只能按 `candidate-cand-` 前缀数卡片：`candidate-` 这个前缀同时命中
    // candidate-accept-cand-a / candidate-ignore-cand-a / candidate-status-cand-a，
    // 用它数出来的永远是按钮数而不是候选数。
    const cards = (): number => wrapper.findAll('[data-testid^="candidate-cand-"]').length;
    await waitFor(() => cards() >= 2, 8000, '候选 2 条');

    expect(wrapper.get('[data-testid="pool-stat-pending"]').text()).toContain('2');

    // N4：点「纳入实验」只打开关键词输入框，不直接提交 —— 否则一补关键词就得先忽略再重来。
    await wrapper.get('[data-testid="candidate-accept-cand-a"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="candidate-keywords-cand-a"]').exists()).toBe(true);
    // 取消不发请求，状态保持待定
    await wrapper.get('[data-testid="candidate-cancel-cand-a"]').trigger('click');
    await flushPromises();
    expect(getState().candidates.find((c) => c.id === 'cand-a')?.status).toBe('pending');

    await wrapper.get('[data-testid="candidate-accept-cand-a"]').trigger('click');
    await flushPromises();
    const input = wrapper.get('[data-testid="candidate-keywords-cand-a"] input');
    await input.setValue('3次');
    await wrapper.get('[data-testid="candidate-confirm-cand-a"]').trigger('click');
    await waitFor(
      () => getState().candidates.find((c) => c.id === 'cand-a')?.status === 'accepted',
      8000,
      '纳入成功',
    );
    // 关键词要真的发出去，落在 mock 状态里
    await waitFor(
      () => getState().candidates.find((c) => c.id === 'cand-a')?.keywords === '3次',
      8000,
      '关键词落库',
    );
    await waitFor(() => cards() === 1, 8000, '只看待定只剩 1 条');

    await wrapper.get('[data-testid="candidate-ignore-cand-b"]').trigger('click');
    await waitFor(
      () => getState().candidates.find((c) => c.id === 'cand-b')?.status === 'ignored',
      8000,
      '忽略成功',
    );
    await waitFor(() => wrapper.find('[data-testid="pool-empty"]').exists(), 8000, '空态');
  });

  it('候选池：留空关键词也能纳入，但会提示该题不计分', async () => {
    getState().candidates.length = 0;
    getState().candidates.unshift({
      id: 'cand-c',
      question: '库里有几本期刊？',
      source: 'feedback',
      status: 'pending',
      createdAt: Date.now(),
    });

    const { wrapper } = await mountPage('candidates');
    await waitFor(
      () => wrapper.find('[data-testid="candidate-accept-cand-c"]').exists(),
      8000,
      '候选卡片',
    );

    await wrapper.get('[data-testid="candidate-accept-cand-c"]').trigger('click');
    await flushPromises();
    // 输入框留空，直接确认
    await wrapper.get('[data-testid="candidate-confirm-cand-c"]').trigger('click');
    await waitFor(
      () => getState().candidates.find((c) => c.id === 'cand-c')?.status === 'accepted',
      8000,
      '留空也纳入',
    );
    const saved = getState().candidates.find((c) => c.id === 'cand-c');
    expect(saved?.keywords ?? '').toBe('');
  });

  it('候选池：空池显示引导文案', async () => {
    getState().candidates.length = 0;
    const { wrapper } = await mountPage('candidates');
    await waitFor(() => wrapper.find('[data-testid="pool-empty"]').exists(), 8000, '空态');
    expect(wrapper.get('[data-testid="pool-empty"]').text()).toContain('👎');
  });

  it('参数实验：2 组 → 进度 0% → 跑完 → 对比表最优行高亮 → 可导出', async () => {
    // 把实验时长压到 120ms：既真的走一遍进度，又不把测试拖到 4 秒
    getState().experimentDuration = 120;

    const { wrapper } = await mountPage('experiment');
    await waitFor(
      () => wrapper.find('[data-testid="experiment-matrix"]').exists(),
      8000,
      '实验面板',
    );

    // 默认单组 → 勾上 k=4 变 2 组（直接驱动子组件，避免依赖 el-checkbox 的 DOM 细节）
    const matrix = wrapper.findComponent(ExperimentMatrix);
    matrix.vm.$emit('toggle', 'k', 4);
    await flushPromises();
    await waitFor(
      () => wrapper.get('[data-testid="exp-group-count"]').text().includes('2'),
      4000,
      '2 组',
    );

    await wrapper.get('[data-testid="exp-create"]').trigger('click');
    await waitFor(() => wrapper.find('[data-testid="exp-progress"]').exists(), 8000, '进度条出现');

    // 进度条出现时还没跑完，百分比从 0 起
    expect(wrapper.get('[data-testid="exp-progress-meta"]').text()).toMatch(/0 \/ 2 组/);

    await waitFor(
      () => wrapper.findAll('[data-testid^="exp-row-"]').length === 2,
      10000,
      '对比表 2 行',
    );

    const best = wrapper.get('[data-best="true"]');
    expect(best.attributes('data-testid')).toBe('exp-row-' + getState().experiments[Object.keys(getState().experiments)[0]!]!.id + '-g2');
    expect(best.text()).toContain('★');
    expect(wrapper.get('[data-testid="exp-best"]').text()).toContain('推荐参数');

    const createSpy = vi.spyOn(URL, 'createObjectURL');
    await wrapper.get('[data-testid="exp-export"]').trigger('click');
    expect(createSpy).toHaveBeenCalledTimes(1);
    const text = await (createSpy.mock.calls[0]?.[0] as Blob).text();
    expect(text).toContain('参数组,片段长度,重叠');
    expect(text).toContain('是');
  });

  it('实验互斥：409 走 conflict 提示而不是红字错误，且不广播「实验进行中」', async () => {
    getState().experimentRunning = true;

    const { wrapper } = await mountPage('experiment');
    await waitFor(() => wrapper.find('[data-testid="experiment-matrix"]').exists(), 8000, '面板');

    await wrapper.get('[data-testid="exp-create"]').trigger('click');
    await waitFor(() => wrapper.find('[data-testid="exp-conflict"]').exists(), 8000, '409 提示');

    expect(wrapper.get('[data-testid="exp-conflict"]').text()).toContain('已有实验在执行');
    expect(wrapper.find('[data-testid="exp-error"]').exists()).toBe(false);
    expect(useSystemStatusStore().experimentRunning).toBe(false);
  });

  it('实验开跑时广播 experiment:running，全局状态与横幅同步；跑完自动恢复', async () => {
    getState().experimentDuration = 120;
    const store = useSystemStatusStore();

    // 生产环境里「事件总线 → Pinia」的桥接点在 AppShell，这里没挂 AppShell，
    // 所以显式补一行同样的桥接，才能验证 useExperiment 真的广播了、横幅真的消费了。
    const offBridge = on('experiment:running', (running) => store.setExperimentRunning(running));

    // 横幅必须挂到同一个 pinia 实例上，否则它读的是另一个 store，永远看不到开关变化
    const banner = mount(ExperimentBanner, { global: { plugins: [pinia] } });
    expect(banner.find('[data-testid="experiment-banner"]').exists()).toBe(false);

    const { wrapper } = await mountPage('experiment');
    await waitFor(() => wrapper.find('[data-testid="experiment-matrix"]').exists(), 8000, '面板');
    await wrapper.get('[data-testid="exp-create"]').trigger('click');

    await waitFor(() => store.experimentRunning === true, 8000, '广播进行中');
    await banner.vm.$nextTick();
    expect(banner.find('[data-testid="experiment-banner"]').exists()).toBe(true);
    expect(banner.get('[data-testid="experiment-banner"]').text()).toContain('409');

    await waitFor(() => store.experimentRunning === false, 12000, '跑完恢复');
    await banner.vm.$nextTick();
    expect(banner.find('[data-testid="experiment-banner"]').exists()).toBe(false);

    offBridge();
    banner.unmount();
  });

  it('切换页签会换组件，且切走时停掉批量轮询', async () => {
    const { wrapper, router } = await mountPage();
    await waitFor(
      () => wrapper.findAll('[data-testid^="pick-"]').length === QUESTION_COUNT,
      8000,
      '题目',
    );
    expect(wrapper.findComponent(BatchRunner).exists()).toBe(true);

    await router.push({ name: 'eval', query: { tab: 'candidates' } });
    await flushPromises();
    await waitFor(() => wrapper.findComponent(CandidatePool).exists(), 8000, '候选池');

    expect(wrapper.findComponent(BatchRunner).exists()).toBe(false);
  });
});
