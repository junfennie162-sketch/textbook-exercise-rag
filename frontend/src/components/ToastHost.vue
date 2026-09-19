<script setup>
import { dismissToast, toasts } from '../composables/useToast'
</script>

<template>
  <div class="toast-host" role="status" aria-live="polite">
    <div v-for="item in toasts" :key="item.id" class="toast" :class="`is-${item.kind}`">
      <span aria-hidden="true">{{ item.icon }}</span>
      <span>{{ item.message }}</span>
      <button class="btn btn-ghost btn-sm" type="button" aria-label="关闭提示" @click="dismissToast(item.id)">
        ✕
      </button>
    </div>
  </div>
</template>
