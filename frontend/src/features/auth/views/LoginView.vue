<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { ChatDotRound, Lock, User } from '@element-plus/icons-vue';
import { ApiError, authApi } from '@/api';
import { APP_TITLE } from '@/constants/app';
import { safeRedirect } from '@/app/router/guard';
import { setRole } from '@/app/router/role';
import { useUiPrefsStore } from '@/stores/uiPrefs';

/**
 * 登录页（P6）。
 *
 * 当前登录必须使用部署或测试初始化创建的账号。JWT 保存于公共请求层，
 * 后续请求统一携带 Bearer token；页面不再提供固定 demo 身份或任意用户名认领。
 */
const route = useRoute();
const router = useRouter();
const uiPrefs = useUiPrefsStore();

const username = ref('');
const password = ref('');
const submitting = ref(false);
const error = ref<string | null>(null);

const busy = computed(() => submitting.value);
const canSubmit = computed(() => username.value.trim().length > 0 && password.value.length > 0);

const target = computed(() => safeRedirect(route.query.redirect));

function onTheme(): void {
  uiPrefs.toggle();
}

/**
 * 登录成功后落哪一页。
 *
 * 有 redirect 就直达（例如被守卫弹回来时保留的原目标）；否则按角色分流：
 * 管理员进用户管理，普通用户进对话页。这是「管理端/用户端」的第一道分流，
 * 路由守卫是第二道（手输 /admin 会被弹回来）。
 */
function landingFor(role: string, fallback: string): string {
  const hasRedirect = typeof route.query.redirect === 'string' && route.query.redirect !== '';
  if (hasRedirect) return fallback;
  return role === 'ADMIN' ? '/admin/users' : '/chat';
}

async function afterLogin(role: string): Promise<void> {
  await router.replace(landingFor(role, target.value));
}

async function onSubmit(): Promise<void> {
  if (!canSubmit.value || busy.value) return;
  submitting.value = true;
  error.value = null;
  try {
    const result = await authApi.login({
      username: username.value.trim(),
      password: password.value,
    });
    // 角色随登录态一起落盘：路由守卫每次导航都要读它，不能每次都发请求。
    setRole(result?.user?.role ?? 'USER');
    ElMessage.success('登录成功');
    await afterLogin(result?.user?.role ?? 'USER');
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

      <div class="login__demo" data-testid="login-auth-note">
        <strong>账号登录</strong>
        <span>请输入部署或测试初始化创建的用户名和密码。</span>
      </div>


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
        登录后将按当前账号访问资料、建库任务、会话和问答数据。
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
