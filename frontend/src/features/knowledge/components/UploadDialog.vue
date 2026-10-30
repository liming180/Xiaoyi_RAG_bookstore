<script setup lang="ts">
import { computed, ref } from 'vue';
import { ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES } from '@/constants/app';
import { formatBytes, splitFiles } from '../composables/uploadRules';

/**
 * UploadDialog —— 资料上传对话框（F01）。
 *
 * 支持点击选择 + 拖拽；前端先校验扩展名与大小，被挡的当场给原因，
 * 不让用户「传完一轮才知道不行」。
 */
const props = defineProps<{
  modelValue: boolean;
  uploading?: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [boolean];
  submit: [File[]];
}>();

const picked = ref<File[]>([]);
const rejected = ref<Array<{ name: string; reason: string }>>([]);
const dragOver = ref(false);
const inputRef = ref<HTMLInputElement | null>(null);

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
});

const canSubmit = computed(() => picked.value.length > 0 && !props.uploading);

const accept = ALLOWED_EXTENSIONS.join(',');
const maxHint = `单份 ≤ ${formatBytes(MAX_UPLOAD_BYTES)}，仅 ${ALLOWED_EXTENSIONS.join(' / ')}`;

function addFiles(files: File[]): void {
  const { accepted, rejected: bad } = splitFiles(files);
  const exists = new Set(picked.value.map((f) => `${f.name}:${f.size}`));
  for (const file of accepted) {
    const key = `${file.name}:${file.size}`;
    if (!exists.has(key)) {
      picked.value.push(file);
      exists.add(key);
    }
  }
  rejected.value = bad;
}

function onPick(e: Event): void {
  const input = e.target as HTMLInputElement;
  if (input.files && input.files.length > 0) addFiles(Array.from(input.files));
  input.value = '';
}

function onDrop(e: DragEvent): void {
  dragOver.value = false;
  const list = e.dataTransfer?.files;
  if (list && list.length > 0) addFiles(Array.from(list));
}

function openPicker(): void {
  inputRef.value?.click();
}

function removeAt(i: number): void {
  picked.value.splice(i, 1);
}

function reset(): void {
  picked.value = [];
  rejected.value = [];
  dragOver.value = false;
}

function onClose(): void {
  reset();
  visible.value = false;
}

function onSubmit(): void {
  if (!canSubmit.value) return;
  emit('submit', [...picked.value]);
}

defineExpose({ addFiles, reset, picked });
</script>

<template>
  <el-dialog
    v-model="visible"
    title="上传资料"
    width="520px"
    :close-on-click-modal="false"
    data-testid="upload-dialog"
    @close="reset"
  >
    <div
      class="upload"
      :class="{ 'upload__drop--over': dragOver }"
      data-testid="upload-dropzone"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
      @click="openPicker"
    >
      <p class="upload__hint">把文件拖到这里，或点击选择</p>
      <p class="upload__sub">{{ maxHint }}</p>
      <input
        ref="inputRef"
        type="file"
        class="visually-hidden"
        :accept="accept"
        multiple
        data-testid="upload-input"
        @change="onPick"
      />
    </div>

    <ul v-if="picked.length > 0" class="upload__list" data-testid="upload-picked">
      <li v-for="(file, i) in picked" :key="`${file.name}-${i}`" class="upload__item">
        <span class="upload__name">{{ file.name }}</span>
        <span class="upload__size">{{ formatBytes(file.size) }}</span>
        <button type="button" class="upload__remove" @click="removeAt(i)">移除</button>
      </li>
    </ul>

    <ul v-if="rejected.length > 0" class="upload__skipped" data-testid="upload-rejected">
      <li v-for="(item, i) in rejected" :key="i">
        <strong>{{ item.name }}</strong> — {{ item.reason }}
      </li>
    </ul>

    <template #footer>
      <el-button size="small" @click="onClose">取消</el-button>
      <el-button
        size="small"
        type="primary"
        :loading="uploading"
        :disabled="!canSubmit"
        data-testid="upload-submit"
        @click="onSubmit"
      >
        上传 {{ picked.length > 0 ? `(${picked.length})` : '' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.upload {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 28px 16px;
  text-align: center;
  border: 1.5px dashed var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
}

.upload:hover,
.upload__drop--over {
  border-color: var(--teal);
  background: var(--soft);
}

.upload__hint {
  margin: 0;
  font-size: 13px;
  color: var(--text);
}

.upload__sub {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
}

.upload__list {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
  max-height: 180px;
  overflow: auto;
}

.upload__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  font-size: 12px;
  border-bottom: 1px solid var(--line);
}

.upload__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink);
}

.upload__size {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
}

.upload__remove {
  padding: 0 6px;
  font-size: 11px;
  color: var(--red);
  background: transparent;
  border: 0;
  cursor: pointer;
}

.upload__skipped {
  margin: 10px 0 0;
  padding: 8px 10px;
  list-style: none;
  font-size: 12px;
  color: var(--amber);
  background: var(--amber-soft);
  border-radius: 8px;
}
</style>
