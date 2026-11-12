<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage, type FormInstance, type FormRules } from 'element-plus';
import { ApiError, adminApi } from '@/api';
import type { AdminUserItem } from '@/types/api';

/**
 * 新建 / 编辑共用的弹窗。
 *
 * 两种模式共用一个组件（而不是两个弹窗）：字段几乎一样，分开写会出现
 * 「编辑能填密码但提交被忽略」这类不一致。模式差异集中在三处：
 *   - 编辑时 username 只读（它是登录标识与审计锚点，改了就串号）；
 *   - 编辑时不显示密码字段（改密码走独立的「重置密码」弹窗，独立审计）；
 *   - 提交调不同接口。
 */
const props = defineProps<{
  modelValue: boolean;
  /** null = 新建；有值 = 编辑该行 */
  target: AdminUserItem | null;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  saved: [];
}>();

const formRef = ref<FormInstance>();
const submitting = ref(false);

const isEdit = computed(() => props.target !== null);

const form = reactive({
  username: '',
  displayName: '',
  password: '',
});

/**
 * 校验规则与服务端一一对应：
 *   - username 形状（1–64 字母数字下划线）在服务端也校验，这里提前拦掉省一次往返；
 *   - 密码按 **UTF-8 字节** 判 12–72 —— 与后端 requirePasswordBytes 同口径，
 *     用字符数判会让「25 个中文」（75 字节）在表单里通过、到服务端才被拒。
 */
const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      pattern: /^[a-zA-Z0-9_]{1,64}$/,
      message: '1-64 位字母、数字或下划线',
      trigger: 'blur',
    },
  ],
  displayName: [{ max: 64, message: '显示名不能超过 64 个字符', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        const bytes = new TextEncoder().encode(value ?? '').length;
        if (bytes < 12 || bytes > 72) {
          callback(new Error('密码需为 12-72 个字节（中文 1 字按 3 字节计）'));
          return;
        }
        callback();
      },
      trigger: 'blur',
    },
  ],
};

/** 打开时按模式回填。编辑态不碰 password（那个字段在编辑态根本不渲染）。 */
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    const target = props.target;
    form.username = target?.username ?? '';
    form.displayName = target?.displayName ?? '';
    form.password = '';
    formRef.value?.clearValidate();
  },
);

function close(): void {
  emit('update:modelValue', false);
}

async function onSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || submitting.value) return;

  submitting.value = true;
  try {
    if (isEdit.value && props.target) {
      await adminApi.updateUser(props.target.id, {
        displayName: form.displayName.trim(),
      });
      ElMessage.success('已保存');
    } else {
      await adminApi.createUser({
        username: form.username.trim(),
        password: form.password,
        displayName: form.displayName.trim() || undefined,
      });
      ElMessage.success('用户已创建');
    }
    emit('saved');
    close();
  } catch (e) {
    // 40905「用户名已存在」挂到字段上，其余（403/网络）用 toast ——
    // 字段级错误定位到输入框，比一句笼统的 toast 有用。
    const apiError = e instanceof ApiError ? e : null;
    if (apiError?.code === 40905) {
      formRef.value?.validateField('username').catch(() => undefined);
      ElMessage.error('用户名已存在');
    } else {
      ElMessage.error(apiError?.message ?? '保存失败');
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="isEdit ? '编辑用户' : '新建用户'"
    width="440px"
    data-testid="admin-user-dialog"
    @update:model-value="close"
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="80px"
      data-testid="admin-user-form"
      @submit.prevent="onSubmit"
    >
      <el-form-item label="用户名" prop="username">
        <el-input
          v-model="form.username"
          :disabled="isEdit"
          placeholder="登录名，创建后不可修改"
          data-testid="admin-user-username"
        />
      </el-form-item>
      <el-form-item label="显示名" prop="displayName">
        <el-input
          v-model="form.displayName"
          placeholder="留空则显示用户名"
          data-testid="admin-user-displayname"
        />
      </el-form-item>
      <el-form-item v-if="!isEdit" label="密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          show-password
          placeholder="12-72 字节，建议含字母、数字、符号"
          data-testid="admin-user-password"
        />
      </el-form-item>
      <p v-if="isEdit" class="admin-form__hint">改密码请用列表里的「重置密码」，便于单独留审计记录。</p>
    </el-form>

    <template #footer>
      <el-button data-testid="admin-user-cancel" @click="close">取消</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        data-testid="admin-user-submit"
        @click="onSubmit"
      >
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.admin-form__hint {
  margin: 0 0 0 80px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
}
</style>
