import { onUnmounted, ref } from 'vue';

/**
 * 递归 setTimeout 轮询。
 * 旧版用 setInterval（web/legacy/app.js:500、:461），视图切走或组件卸载时不清就会持续打后端。
 * 这里统一返回 {start, stop}，并在 onUnmounted 时自动 stop。
 *
 * @param {Function} task     每次轮询执行的异步函数，返回 true 表示「继续轮询」
 * @param {number}   interval 间隔毫秒
 */
export function usePolling(task, interval = 300) {
  const active = ref(false);
  let handle = null;
  let stopped = false;

  function stop() {
    stopped = true;
    active.value = false;
    if (handle) {
      clearTimeout(handle);
      handle = null;
    }
  }

  async function tick() {
    if (stopped) return;
    let go = false;
    try {
      go = await task();
    } catch (err) {
      stop();
      throw err;
    }
    if (stopped) return;
    if (go) {
      handle = setTimeout(tick, interval);
    } else {
      active.value = false;
      handle = null;
    }
  }

  function start() {
    stop();
    stopped = false;
    active.value = true;
    handle = setTimeout(tick, interval);
  }

  onUnmounted(stop);

  return { active, start, stop };
}
