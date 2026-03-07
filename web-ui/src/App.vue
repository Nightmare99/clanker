<script setup lang="ts">
import { ref } from 'vue'
import {
  NConfigProvider,
  NMessageProvider,
  darkTheme,
} from 'naive-ui'
import ConfigPanel from './components/ConfigPanel.vue'
</script>

<template>
  <NConfigProvider :theme="darkTheme">
    <NMessageProvider>
      <ConfigPanel />
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
:root {
  color-scheme: dark;
}

body {
  margin: 0;
  padding: 0;
  background: #1a1a1a;
}
</style>
