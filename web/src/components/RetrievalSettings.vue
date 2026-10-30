<script setup>
import { computed } from 'vue';
import { actions, fail, state } from '../store.js';

const sessionId = computed(() => (state.status && state.status.session ? state.status.session.session_id : '—'));
const kRange = computed(() => (state.status && state.status.k_range ? state.status.k_range : [1, 5]));

async function onK(event) {
  try { await actions.setK(event.target.value); } catch (err) { fail(err); }
}

async function onMode(event) {
  try { await actions.setMode(event.target.value); } catch (err) { fail(err); }
}

async function clearSession() {
  try { await actions.newSession(); } catch (err) { fail(err); }
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2>检索设置</h2>
      <span class="badge">k = {{ state.k }}</span>
    </div>

    <div class="field">
      <label for="kRange">每次取回</label>
      <input
        id="kRange"
        :value="state.k"
        type="range"
        :min="kRange[0]"
        :max="kRange[1]"
        step="1"
        @input="onK"
      >
    </div>

    <div class="field">
      <label for="modeSelect">回答模式</label>
      <select id="modeSelect" :value="state.mode" @change="onMode">
        <option value="rag">查资料</option>
        <option value="direct">不查资料</option>
        <option value="both">两者对照</option>
      </select>
    </div>

    <button class="btn block mt8" @click="clearSession">清空对话</button>
    <p class="hint">会话 {{ sessionId }}</p>
  </section>
</template>
