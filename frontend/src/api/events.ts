/**
 * 极简事件总线：用于 API 层向 UI 层广播跨切面事件。
 *
 * 存在的理由：401 过期与 503 降级不能靠「每个调用点自己处理」，
 * 否则 20 个调用点就有 20 套不一致的行为。这里只做一件事：广播。
 */
export interface ApiEvents {
  'auth:expired': void;
  'system:degraded': { code: number; message: string };
  'system:restored': void;
}

type Handler<T> = (payload: T) => void;

const listeners = new Map<keyof ApiEvents, Set<Handler<never>>>();

export function on<K extends keyof ApiEvents>(event: K, handler: Handler<ApiEvents[K]>): () => void {
  const set = listeners.get(event) ?? new Set<Handler<never>>();
  set.add(handler as Handler<never>);
  listeners.set(event, set);
  return () => {
    set.delete(handler as Handler<never>);
  };
}

export function emit<K extends keyof ApiEvents>(event: K, payload: ApiEvents[K]): void {
  const set = listeners.get(event);
  if (!set) return;
  for (const handler of set) {
    (handler as Handler<ApiEvents[K]>)(payload);
  }
}

/** 测试用：清空所有订阅 */
export function clearAllListeners(): void {
  listeners.clear();
}
