import { reactive } from 'vue';

/** 全局唯一的 toast 队列状态（由 ToastHost.vue 渲染） */
export const toastState = reactive({ text: '', visible: false });

let timer = null;

export function toast(text) {
  toastState.text = String(text == null ? '' : text);
  toastState.visible = true;
  clearTimeout(timer);
  timer = setTimeout(() => { toastState.visible = false; }, 2600);
}

export function useToast() {
  return { toastState, toast };
}
