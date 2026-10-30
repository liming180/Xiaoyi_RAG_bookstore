<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { ChatDotRound, Lock, User } from '@element-plus/icons-vue';
import { ApiError, authApi } from '@/api';
import { APP_TITLE } from '@/constants/app';
import { safeRedirect } from '@/app/router/guard';
import { useUiPrefsStore } from '@/stores/uiPrefs';

/**
 * 登录页（P6）。
 *
 * 阶段 1 是演示模式：后端放行任意账密，所以主路径就是「一键进入演示」。
 * 账密表单仍然保留并真的提交 —— 一方面验证 `POST /api/v1/auth/login` 的
 * 完整链路，另一方面等后端接入真实鉴权时不需要改前端结构。
 *
 * 演示模式说明写死在页面上而不是靠 README：验收时评委会直接打开这个页面。
 */
const route = useRoute();
const router = useRouter();
const uiPrefs = useUiPrefsStore();

const username = ref('');
const password = ref('');
const submitting = ref(false);
const demoing = ref(false);
const error = ref<string | null>(null);

const busy = computed(() => submitting.value || demoing.value);
const canSubmit = computed(() => username.value.trim().length > 0 && password.value.length > 0);

const target = computed(() => safeRedirect(route.query.redirect));

function onTheme(): void {
  uiPrefs.toggle();
}

async function afterLogin(): Promise<void> {
  await router.replace(target.value);
}

async function onDemo(): Promise<void> {
  if (busy.value) return;
  demoing.value = true;
  error.value = null;
  try {
    await authApi.loginAsDemo();
    ElMessage.success('已进入演示模式');
    await afterLogin();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '进入演示模式失败，请重试';
  } finally {
    demoing.value = false;
  }
}

async function onSubmit(): Promise<void> {
  if (!canSubmit.value || busy.value) return;
  submitting.value = true;
  error.value = null;
  try {
    await authApi.login({ username: username.value.trim(), password: password.value });
    ElMessage.success('登录成功');
    await afterLogin();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '登录失败，请检查账号密码';
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  uiPrefs.init();
});
</script>

<template>
  <div class="login" data-testid="page-login">
    <button type="button" class="login__theme" data-testid="login-theme" @click="onTheme">
      {{ uiPrefs.theme === 'dark' ? '☀ 浅色' : '🌙 深色' }}
    </button>

    <section class="login__card">
      <header class="login__head">
        <el-icon class="login__logo"><ChatDotRound /></el-icon>
        <h1 class="login__title">{{ APP_TITLE }}</h1>
        <p class="login__sub">把读书会的资料变成可以追问的答案</p>
      </header>

      <div class="login__demo" data-testid="login-demo-note">
        <strong>演示模式</strong>
        <span>当前为课程演示版，未接入真实账号体系：点下面的按钮即可进入，无需注册。</span>
      </div>

      <el-button
        class="login__demo-btn"
        type="primary"
        size="large"
        :loading="demoing"
        data-testid="login-demo"
        @click="onDemo"
      >
        一键进入演示
      </el-button>

      <div class="login__divider"><span>或使用账号密码</span></div>

      <form class="login__form" data-testid="login-form" @submit.prevent="onSubmit">
        <el-input
          v-model="username"
          size="large"
          placeholder="用户名"
          :prefix-icon="User"
          data-testid="login-username"
          autocomplete="username"
        />
        <el-input
          v-model="password"
          size="large"
          type="password"
          placeholder="密码"
          :prefix-icon="Lock"
          show-password
          data-testid="login-password"
          autocomplete="current-password"
        />
        <el-button
          class="login__submit"
          size="large"
          native-type="submit"
          :disabled="!canSubmit"
          :loading="submitting"
          data-testid="login-submit"
        >
          登录
        </el-button>
      </form>

      <p v-if="error" class="login__error" data-testid="login-error">{{ error }}</p>

      <p class="login__foot">
        阶段 1 演示版：知识库问答全部基于本地示例资料，回答会带引用编号，可点开核对原文。
      </p>
    </section>
  </div>
</template>

<style scoped>
.login {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 32px 16px;
  background:
    radial-gradient(circle at 12% 18%, var(--soft), transparent 55%),
    radial-gradient(circle at 88% 82%, var(--amber-soft), transparent 50%), var(--bg);
}

.login__theme {
  position: absolute;
  top: 20px;
  right: 24px;
  padding: 6px 12px;
  font-size: 12px;
  color: var(--muted);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 999px;
  cursor: pointer;
}

.login__theme:hover {
  color: var(--ink);
}

.login__card {
  width: 100%;
  max-width: 420px;
  padding: 32px 28px 26px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.login__head {
  text-align: center;
}

.login__logo {
  font-size: 30px;
  color: var(--teal);
}

.login__title {
  margin: 8px 0 4px;
  font-size: 20px;
  font-weight: 650;
  color: var(--ink);
}

.login__sub {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
}

.login__demo {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 22px 0 14px;
  padding: 12px 14px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text);
  background: var(--soft);
  border-left: 3px solid var(--teal);
  border-radius: var(--radius-sm);
}

.login__demo strong {
  color: var(--teal-dark);
  font-weight: 600;
}

.login__demo-btn {
  width: 100%;
}

.login__divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 18px 0;
  font-size: 12px;
  color: var(--muted);
}

.login__divider::before,
.login__divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--line);
}

.login__form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.login__submit {
  width: 100%;
  margin-top: 2px;
}

.login__error {
  margin: 12px 0 0;
  font-size: 12.5px;
  color: var(--red);
}

.login__foot {
  margin: 20px 0 0;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--muted);
}
</style>
