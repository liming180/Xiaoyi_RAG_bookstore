/**
 * N5 结构化回答：提示词放开 markdown 之后，前端必须真的把它渲染成结构。
 *
 * 背景（`docs/02-重构设计/05_后端开发提示词_亮点包后端.md` §7.1）：
 * 前端 `parseMarkdown` 早就支持标题 / 列表 / 表格 / 加粗 / 链接，但 `SYSTEM_PROMPT`
 * 从没要求模型产 markdown，所以这份白名单一直在空转 —— 能力在，输入不来。
 *
 * N5 给提示词加了第 6 条，要求「对比、枚举、分步骤」时用表格或有序列表，且来源编号
 * 写在对应单元格/列表项内。这条约束要成立，得两端同时到位：
 *
 * - 后端：约束写进 system 消息（`test/A2-rag/test_prompt_format.py` 钉住）；
 * - 前端：真的把 `| ... |` 渲染成 `<table>`、把 `1.` 渲染成 `<ol>`、
 *   把单元格/列表项里的 `[n]` 渲染成可点的引用徽标（本文件钉住）。
 *
 * 只做后端那一半，「提示词说了但页面还是一坨竖线」照样能发生。所以这里用模型
 * 按第 6 条产出的**典型形状**当输入，断言 DOM 结构，而不是断言解析器内部 token。
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import AnswerBody from '@/features/chat/components/AnswerBody.vue';
import type { Citation } from '@/types/api';
import { resetState } from '@/mocks/state';

function citation(over: Partial<Citation> = {}): Citation {
  return {
    ref: 1,
    chunkId: 'D02-C001',
    docId: 'D02',
    docTitle: '02_借阅规则.md',
    headingPath: '借阅数量',
    text: '已登记成员每人最多同时借阅 4 本普通图书，每本借期 21 天。',
    start: 0,
    end: 30,
    score: 0.87,
    kind: 'chunk',
    verified: true,
    ...over,
  };
}

/** 第 6 条要求的「对比用表格」形状：编号写在单元格内，不堆在末尾。 */
const COMPARISON_TABLE = `普通图书与期刊的借阅规则不同：

| 项目 | 普通图书 | 期刊 |
| --- | --- | --- |
| 同时借阅上限 | 4 本 [1] | 2 本 [2] |
| 单本借期 | 21 天 [1] | 7 天 [2] |
| 能否续借 | 可续借 1 次 [1] | 不能续借 [2] |`;

/** 第 6 条要求的「分步骤用有序列表」形状。 */
const STEP_LIST = `补办借阅证的步骤如下：

1. 到一层服务台领取补办申请表 [1]
2. 出示成员编号并登记 [1]
3. 三个工作日后凭回执领取新证 [2]`;

function mountAnswer(content: string, citations: Citation[]) {
  return mount(AnswerBody, {
    props: { content, citations },
    global: { plugins: [ElementPlus] },
  });
}

describe('结构化回答渲染（B3 / N5）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    resetState();
  });

  it('对比类内容渲染成真表格，且每个单元格的编号都能点开', async () => {
    const citations = [citation(), citation({ ref: 2, chunkId: 'D04-C001', docId: 'D04', docTitle: '04_期刊与工具书.md' })];
    const wrapper = mountAnswer(COMPARISON_TABLE, citations);

    expect(wrapper.findAll('table')).toHaveLength(1);
    // 表头 3 列（项目 / 普通图书 / 期刊），3 行数据
    expect(wrapper.findAll('th')).toHaveLength(3);
    expect(wrapper.findAll('tbody tr')).toHaveLength(3);

    // 编号在单元格内：徽标数量应与表格里出现的 [1] [2] 总数一致（3 行 × 2 列 = 6），
    // 而不是挤在末尾一行。末尾堆编号正是第 6 条要治的毛病。
    const badges = wrapper.findAll('[data-testid="cite-badge"]');
    expect(badges).toHaveLength(6);

    // 点表格里的徽标能上抛 cite 事件（引用卡由 MessageBubble 渲染，AnswerBody 只负责上抛）。
    await badges[0]!.trigger('click');
    await flushPromises();
    const emitted = wrapper.emitted('cite');
    expect(emitted).toBeTruthy();
    expect(emitted![0]![0]).toMatchObject({ docTitle: '02_借阅规则.md' });
  });

  it('分步骤内容渲染成有序列表而不是段落', () => {
    const wrapper = mountAnswer(STEP_LIST, [citation(), citation({ ref: 2 })]);

    expect(wrapper.findAll('ol')).toHaveLength(1);
    expect(wrapper.findAll('ol li')).toHaveLength(3);
    // 渲染成 <ol> 之后浏览器自己编号，正文里不该再残留「1. 」这种字面量。
    expect(wrapper.get('ol').text()).not.toMatch(/^\s*1\.\s/);
    // 列表项里的编号仍要变成徽标（前两项 [1]、第三项 [2]）。
    expect(wrapper.findAll('ol [data-testid="cite-badge"]').length).toBe(3);
  });

  it('表格与有序列表混排时各自独立成块', () => {
    const mixed = `${COMPARISON_TABLE}\n\n${STEP_LIST}`;
    const wrapper = mountAnswer(mixed, [citation(), citation({ ref: 2 })]);

    expect(wrapper.findAll('table')).toHaveLength(1);
    expect(wrapper.findAll('ol')).toHaveLength(1);
    // 中间那段「补办借阅证的步骤如下：」是段落，不能被吸进表格或列表。
    expect(wrapper.text()).toContain('补办借阅证的步骤如下');
  });

  it('模型不按格式产出（纯文本）时照样能渲染，不报错也不丢字', () => {
    const plain = '已登记成员每人最多同时借阅 4 本普通图书，每本借期 21 天 [1]。';
    const wrapper = mountAnswer(plain, [citation()]);

    expect(wrapper.findAll('table')).toHaveLength(0);
    expect(wrapper.findAll('ol')).toHaveLength(0);
    expect(wrapper.text()).toContain('4 本普通图书');
    expect(wrapper.findAll('[data-testid="cite-badge"]')).toHaveLength(1);
  });

  it('半截表格（流式输出中途）不会卡死也不吐裸露竖线以外的内容', () => {
    // 流式输出时每来一段就重新解析一次，表头刚出来、分隔行还没到的那一刻
    // 是最危险的状态：所有分支都 break 就会原地打转（parseMarkdown 里有注释
    // 记录过这次事故）。这里直接喂那个形状，确保有兜底消费。
    const partial = '| 项目 | 普通图书 |\n| 同时借阅上限 | 4 本 [1] |';
    const wrapper = mountAnswer(partial, [citation()]);

    expect(wrapper.findAll('table')).toHaveLength(0);
    expect(wrapper.text()).toContain('同时借阅上限');
    // 编号仍然被识别，只是落在段落里。
    expect(wrapper.findAll('[data-testid="cite-badge"]')).toHaveLength(1);
  });
});
