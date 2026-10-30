<script setup lang="ts">
import { computed } from 'vue';
import { DOC_STATUS_META } from '@/constants/app';
import type { DocumentStatus } from '@/types/api';

/**
 * StatusBadge —— 文档状态六态徽标（F01/F03）。
 *
 * 六态：UPLOADING / PARSING / INDEXED / FAILED / NEEDS_REBUILD / DISABLED
 * 颜色语义全部走 U04 令牌（.badge--ok/warn/error/muted/info），组件内不写死颜色。
 */
const props = defineProps<{
  status: DocumentStatus;
}>();

const meta = computed(() => DOC_STATUS_META[props.status] ?? DOC_STATUS_META.INDEXED!);
</script>

<template>
  <span
    class="badge doc-status"
    :class="`badge--${meta.tone}`"
    :data-status="status"
    :data-testid="`doc-status-${status}`"
  >
    {{ meta.label }}
  </span>
</template>

<style scoped>
.doc-status {
  font-family: inherit;
}
</style>
