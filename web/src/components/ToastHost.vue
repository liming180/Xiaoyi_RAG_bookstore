<script setup>
import { toastState } from '../composables/useToast.js';
</script>

<template>
  <div class="toast" :class="{ show: toastState.visible }">{{ toastState.text }}</div>
</template>
