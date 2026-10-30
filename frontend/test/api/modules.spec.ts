import { describe, expect, it } from 'vitest';
import { chatApi, knowledgeApi } from '@/api';

describe('api/chat 模块（走 MSW）', () => {
  it('会话列表返回种子会话', async () => {
    const list = await chatApi.listConversations();
    expect(list.length).toBeGreaterThan(0);
    expect(list[0]).toHaveProperty('id');
    expect(list[0]).toHaveProperty('title');
  });

  it('消息列表归一化出 citations 与 trace', async () => {
    const list = await chatApi.listMessages('c-demo');
    expect(list.length).toBeGreaterThan(0);
    const assistant = list.find((m) => m.role === 'assistant');
    expect(assistant?.citations.length).toBeGreaterThan(0);
    expect(assistant?.citations[0]?.chunkId).toMatch(/^D\d{2}-C\d{3}$/);
    expect(assistant?.trace?.rows.length).toBeGreaterThan(3);
  });

  it('流式对话产出 status → retrieval → token → done', async () => {
    const events: string[] = [];
    let text = '';
    for await (const ev of chatApi.streamAnswer({
      conversationId: 'c-demo',
      question: '普通图书最多能借几本？',
      mode: 'rag',
      k: 3,
    })) {
      events.push(ev.event);
      if (ev.event === 'token') {
        text += (ev.data as { content: string }).content;
      }
    }
    expect(events).toContain('status');
    expect(events).toContain('retrieval');
    expect(events).toContain('token');
    expect(events[events.length - 1]).toBe('done');
    expect(text).toContain('4 本');
  });

  it('清空对话后消息列表为空', async () => {
    await chatApi.clearMessages('c-demo');
    const list = await chatApi.listMessages('c-demo');
    expect(list).toEqual([]);
  });
});

describe('api/knowledge 模块（走 MSW）', () => {
  it('资料列表 6 份且 06 未核实', async () => {
    const docs = await knowledgeApi.listDocuments();
    expect(docs).toHaveLength(6);
    const unverified = docs.find((d) => d.name === '06_成员留言摘录.md');
    expect(unverified?.verified).toBe(false);
  });

  it('索引状态默认 ready', async () => {
    const status = await knowledgeApi.fetchIndexStatus();
    expect(status.status).toBe('ready');
    expect(status.chunkSize).toBe(180);
    expect(status.overlap).toBe(30);
  });

  it('重建索引后任务能推进到 SUCCEEDED', async () => {
    const task = await knowledgeApi.rebuildIndex({ chunkSize: 120, overlap: 20 });
    expect(task.id).toBeTruthy();
    await new Promise((r) => setTimeout(r, 1000));
    const done = await knowledgeApi.fetchIndexTask(task.id);
    expect(done.status).toBe('SUCCEEDED');
    expect(done.stage).toBe('done');
    expect(done.chunkCount).toBeGreaterThan(0);
    const status = await knowledgeApi.fetchIndexStatus();
    expect(status.status).toBe('ready');
    expect(status.chunkSize).toBe(120);
  });

  it('片段查询可按文档过滤', async () => {
    const all = await knowledgeApi.listChunks();
    expect(all.length).toBeGreaterThan(10);
    const filtered = await knowledgeApi.listChunks({ docId: 'D02' });
    expect(filtered.every((c) => c.docId === 'D02')).toBe(true);
  });

  it('删除资料后索引转为 needs_rebuild', async () => {
    await knowledgeApi.deleteDocument('D06');
    const status = await knowledgeApi.fetchIndexStatus();
    expect(status.status).toBe('needs_rebuild');
  });
});
