<script setup>
import { computed, ref } from 'vue';
import { actions, fail, state } from '../store.js';
import { toast } from '../composables/useToast.js';

const chatKey = ref('');
const embedKey = ref('');

const isMock = computed(() => Boolean(state.status && state.status.mock));
const modelHint = computed(() => {
  if (!state.status) return '';
  if (isMock.value) return '当前为离线模拟档：回答由本地规则生成，用于课堂演示与自检。';
  const cfg = state.status.config || {};
  return `对话模型 ${cfg.model || '—'} · 嵌入 ${cfg.embedding_model || '—'}`;
});

async function applyKeys() {
  const chat = chatKey.value.trim();
  const embed = embedKey.value.trim();
  if (!chat && !embed) {
    toast('未填写密钥');
    return;
  }
  try {
    await actions.applyKeys(chat, embed);
    chatKey.value = '';
    embedKey.value = '';
    toast('密钥已加载到内存');
  } catch (err) {
    fail(err);
  }
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2>模型状态</h2>
      <span :class="isMock ? 'badge warn' : 'badge'">{{ isMock ? '离线模拟' : '真实接口' }}</span>
    </div>

    <p class="hint">{{ modelHint }}</p>

    <div class="field mt8">
      <label for="chatKey">对话 Key</label>
      <input id="chatKey" v-model="chatKey" type="password" autocomplete="off" placeholder="运行时输入">
    </div>
    <div class="field">
      <label for="embedKey">嵌入 Key</label>
      <input id="embedKey" v-model="embedKey" type="password" autocomplete="off" placeholder="同密钥可留空">
    </div>
    <button class="btn block" @click="applyKeys">应用密钥</button>
    <p class="hint">Key 只保存在本进程内存，不写入任何文件。</p>
  </section>
</template>
