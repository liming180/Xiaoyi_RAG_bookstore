import { describe, expect, it } from 'vitest';
import {
  DEFAULT_BUILD_PARAMS,
  formatBuildSummary,
  isParamsDirty,
  isTerminal,
  progressPercent,
  stageLabel,
  validateBuildParams,
} from '@/features/knowledge/composables/buildParams';
import {
  checkFile,
  extensionOf,
  formatBytes,
  splitFiles,
} from '@/features/knowledge/composables/uploadRules';
import type { IndexTask } from '@/types/api';

function makeTask(over: Partial<IndexTask> = {}): IndexTask {
  return {
    id: 'task-1',
    status: 'RUNNING',
    stage: 'parsing',
    progress: 0,
    chunkSize: 180,
    overlap: 30,
    docCount: 6,
    chunkCount: 0,
    error: null,
    startedAt: 0,
    finishedAt: null,
    ...over,
  };
}

describe('建库参数校验（F02）', () => {
  it('默认参数是 180 / 30', () => {
    expect(DEFAULT_BUILD_PARAMS).toEqual({ chunkSize: 180, overlap: 30 });
    expect(validateBuildParams(DEFAULT_BUILD_PARAMS)).toBeNull();
  });

  it('片段长度越界给出范围原因', () => {
    expect(validateBuildParams({ chunkSize: 49, overlap: 10 })).toBe('片段长度需在 50–1000 之间');
    expect(validateBuildParams({ chunkSize: 1001, overlap: 10 })).toBe('片段长度需在 50–1000 之间');
    expect(validateBuildParams({ chunkSize: 50, overlap: 10 })).toBeNull();
    expect(validateBuildParams({ chunkSize: 1000, overlap: 10 })).toBeNull();
  });

  it('非整数被拦下', () => {
    expect(validateBuildParams({ chunkSize: 180.5, overlap: 30 })).toBe('片段长度需为整数');
    expect(validateBuildParams({ chunkSize: 180, overlap: 30.5 })).toBe('重叠字数需为整数');
  });

  it('重叠为负给出原因', () => {
    expect(validateBuildParams({ chunkSize: 180, overlap: -1 })).toBe('重叠字数需大于等于 0');
    expect(validateBuildParams({ chunkSize: 180, overlap: 0 })).toBeNull();
  });

  it('重叠不小于片段长度被拦下', () => {
    expect(validateBuildParams({ chunkSize: 180, overlap: 180 })).toBe('重叠字数需小于片段长度');
    expect(validateBuildParams({ chunkSize: 180, overlap: 200 })).toBe('重叠字数需小于片段长度');
    expect(validateBuildParams({ chunkSize: 180, overlap: 179 })).toBeNull();
  });
});

describe('参数改动判定（F03 状态灯联动）', () => {
  it('与已建库参数不一致时判脏', () => {
    expect(isParamsDirty({ chunkSize: 120, overlap: 20 }, { chunkSize: 180, overlap: 30 })).toBe(true);
    expect(isParamsDirty({ chunkSize: 180, overlap: 30 }, { chunkSize: 180, overlap: 30 })).toBe(false);
    expect(isParamsDirty({ chunkSize: 180, overlap: 20 }, { chunkSize: 180, overlap: 30 })).toBe(true);
  });

  it('没有已建库参数时不算脏', () => {
    expect(isParamsDirty({ chunkSize: 120, overlap: 20 }, null)).toBe(false);
  });
});

describe('建库进度纯函数（F02）', () => {
  it('无任务时进度为 0、阶段为空、摘要为 null', () => {
    expect(progressPercent(null)).toBe(0);
    expect(stageLabel(null)).toBe('');
    expect(formatBuildSummary(null)).toBeNull();
    expect(isTerminal(null)).toBe(false);
  });

  it('运行中按 progress 取整并夹到 0..100', () => {
    expect(progressPercent(makeTask({ progress: 42.4 }))).toBe(42);
    expect(progressPercent(makeTask({ progress: -5 }))).toBe(0);
    expect(progressPercent(makeTask({ progress: 250 }))).toBe(100);
  });

  it('成功态直接 100 并给出摘要', () => {
    const done = makeTask({ status: 'SUCCEEDED', stage: 'done', progress: 100, chunkCount: 15 });
    expect(progressPercent(done)).toBe(100);
    expect(formatBuildSummary(done)).toBe('文档 6 份，片段 15 条');
    expect(stageLabel(done)).toBe('完成');
  });

  it('阶段文案覆盖五步', () => {
    expect(stageLabel(makeTask({ stage: 'parsing' }))).toBe('解析资料');
    expect(stageLabel(makeTask({ stage: 'splitting' }))).toBe('切分片段');
    expect(stageLabel(makeTask({ stage: 'embedding' }))).toBe('生成向量');
    expect(stageLabel(makeTask({ stage: 'summarizing' }))).toBe('生成摘要');
    expect(stageLabel(makeTask({ stage: 'done' }))).toBe('完成');
  });

  it('终态只有成功与失败', () => {
    expect(isTerminal(makeTask({ status: 'SUCCEEDED' }))).toBe(true);
    expect(isTerminal(makeTask({ status: 'FAILED' }))).toBe(true);
    expect(isTerminal(makeTask({ status: 'RUNNING' }))).toBe(false);
    expect(isTerminal(makeTask({ status: 'PENDING' }))).toBe(false);
  });
});

describe('上传前本地校验（F01）', () => {
  function fileOf(name: string, size: number): File {
    const file = new File(['x'], name, { type: 'text/markdown' });
    Object.defineProperty(file, 'size', { value: size });
    return file;
  }

  it('扩展名解析', () => {
    expect(extensionOf('01_借阅规则.md')).toBe('.md');
    expect(extensionOf('README.TXT')).toBe('.txt');
    expect(extensionOf('noext')).toBe('');
  });

  it('接受的类型通过', () => {
    expect(checkFile(fileOf('01_借阅规则.md', 1024)).ok).toBe(true);
    expect(checkFile(fileOf('02_开放时间.txt', 1024)).ok).toBe(true);
  });

  it('扩展名不对被拒', () => {
    const result = checkFile(fileOf('report.pdf', 1024));
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('只接受 .md / .txt 文件');
  });

  it('空文件被拒', () => {
    expect(checkFile(fileOf('empty.md', 0)).reason).toBe('文件没有正文');
  });

  it('超过 2MB 被拒', () => {
    expect(checkFile(fileOf('big.md', 2 * 1024 * 1024 + 1)).reason).toBe('文件超过 2MB');
  });

  it('批量校验分流并保留原因', () => {
    const { accepted, rejected } = splitFiles([
      fileOf('01_借阅规则.md', 100),
      fileOf('bad.pdf', 100),
      fileOf('big.md', 3 * 1024 * 1024),
    ]);
    expect(accepted.map((f) => f.name)).toEqual(['01_借阅规则.md']);
    expect(rejected).toEqual([
      { name: 'bad.pdf', reason: '只接受 .md / .txt 文件' },
      { name: 'big.md', reason: '文件超过 2MB' },
    ]);
  });

  it('大小格式化', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(2 * 1024 * 1024)).toBe('2.00 MB');
  });
});
