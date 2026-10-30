import { defineStore } from 'pinia';
import { ref } from 'vue';
import { STORAGE_KEYS } from '@/constants/app';
import { readStorage, writeStorage } from '@/utils/storage';

export type ThemeMode = 'light' | 'dark';

/**
 * 界面偏好：主题。P6 会接上切换按钮，这里先把状态与持久化打通。
 * 注意：mode / k 属于「提问参数」，按规格存在 localStorage 但不需要跨组件响应式共享时
 * 就走 useQueryPrefs 组合式函数；主题是全局 UI 状态，放 Pinia 合适。
 */
export const useUiPrefsStore = defineStore('uiPrefs', () => {
  const initial = (readStorage(STORAGE_KEYS.theme) as ThemeMode | null) ?? 'light';
  const theme = ref<ThemeMode>(initial === 'dark' ? 'dark' : 'light');

  function apply(): void {
    document.documentElement.dataset.theme = theme.value;
  }

  function setTheme(next: ThemeMode): void {
    theme.value = next;
    writeStorage(STORAGE_KEYS.theme, next);
    apply();
  }

  function toggle(): void {
    setTheme(theme.value === 'light' ? 'dark' : 'light');
  }

  function init(): void {
    apply();
  }

  return { theme, setTheme, toggle, init };
});
