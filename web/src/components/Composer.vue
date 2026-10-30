<script setup>
import { computed, nextTick, ref } from 'vue';
import { actions, fail, state } from '../store.js';

const draft = ref('');
const box = ref(null);

const examples = computed(() => (state.status && state.status.examples) || []);

function autoGrow() {
  const el = box.value;
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
}

function useExample(text) {
  draft.value = text;
  nextTick(() => {
    autoGrow();
    if (box.value) box.value.focus();
  });
}

async function send() {
  const text = draft.value.trim();
  if (!text || state.busy) return;
  draft.value = '';
  nextTick(autoGrow);
  try {
    await actions.send(text);
  } catch (err) {
    /* 错误已写进气泡，这里不重复 toast */
    if (!state.turns.length) fail(err);
  }
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    send();
  }
}
</script>

<template>
  <div class="composer">
    <div class="composer-inner">
      <div v-if="examples.length" class="examples">
        <button
          v-for="q in examples"
          :key="q"
          class="chip"
          :data-q="q"
          @click="useExample(q)"
        >{{ q }}</button>
      </div>
      <div class="input-row">
        <textarea
          ref="box"
          v-model="draft"
          class="question"
          rows="1"
          placeholder="问一个资料里的问题，Enter 发送，Shift+Enter 换行"
          @input="autoGrow"
          @keydown="onKeydown"
        />
        <button class="btn primary" :disabled="state.busy || !draft.trim()" @click="send">
          {{ state.busy ? '正在回答…' : '发送' }}
        </button>
      </div>
    </div>
  </div>
</template>
