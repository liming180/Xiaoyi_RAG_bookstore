<script setup>
import { ref } from 'vue';
import { actions, fail, state } from '../store.js';
import { toast } from '../composables/useToast.js';

const hot = ref(false);
const fileInput = ref(null);
const uploading = ref(false);

function pick() {
  if (fileInput.value) fileInput.value.click();
}

async function doUpload(files) {
  const list = Array.from(files || []);
  if (!list.length) return;
  uploading.value = true;
  try {
    const data = await actions.upload(list);
    const added = data.added || [];
    const skipped = data.skipped || [];
    let msg = `已添加 ${added.length} 份`;
    if (skipped.length) msg += `，跳过 ${skipped.length} 份：${skipped.join('；')}`;
    toast(msg);
  } catch (err) {
    fail(err);
  } finally {
    uploading.value = false;
    if (fileInput.value) fileInput.value.value = '';
  }
}

function onDrop(event) {
  hot.value = false;
  doUpload(event.dataTransfer && event.dataTransfer.files);
}

function onPick(event) {
  doUpload(event.target.files);
}

async function openDoc(name) {
  try { await actions.openDoc(name); } catch (err) { fail(err); }
}

async function removeDoc(name) {
  if (!window.confirm(`删除资料「${name}」？删除后需要重新建库。`)) return;
  try {
    await actions.removeDoc(name);
    toast(`已删除 ${name}，请重新建库`);
  } catch (err) {
    fail(err);
  }
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2>我的知识库</h2>
      <span class="badge">{{ state.docs.length }} 份资料</span>
    </div>

    <div class="doc-list">
      <div v-if="!state.docs.length" class="empty">还没有资料</div>
      <div
        v-for="doc in state.docs"
        :key="doc.name"
        class="doc-item"
        :data-name="doc.name"
        @click="openDoc(doc.name)"
      >
        <div class="doc-main">
          <div class="doc-name" :title="doc.name">{{ doc.name }}</div>
          <div class="doc-meta">
            <span>{{ doc.chars }} 字</span>
            <span>·</span>
            <span>{{ doc.chunks }} 片段</span>
            <span v-if="!doc.verified" class="badge warn">未核实</span>
          </div>
        </div>
        <button class="icon-btn" title="删除" @click.stop="removeDoc(doc.name)">✕</button>
      </div>
    </div>

    <div
      class="drop mt12"
      :class="{ hot }"
      @click="pick"
      @dragover.prevent="hot = true"
      @dragleave.prevent="hot = false"
      @drop.prevent="onDrop"
    >
      {{ uploading ? '正在上传…' : '添加资料：拖入 .md / .txt（每份不超 2MB）' }}
    </div>
    <input
      ref="fileInput"
      type="file"
      accept=".md,.txt"
      multiple
      hidden
      @change="onPick"
    >
  </section>
</template>
