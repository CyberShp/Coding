<template>
  <nav v-if="section?.pages.length" class="section-navigation" :aria-label="section.label">
    <router-link v-for="page in section.pages" :key="page.path" :to="page.path"
      :class="{ selected: route.path === page.path || route.path.startsWith(page.path + '/') }"
      :aria-current="route.path === page.path ? 'page' : undefined">{{ page.label }}</router-link>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { sectionForPath } from '../navigation'
const route = useRoute()
const section = computed(() => sectionForPath(route.path))
</script>

<style scoped>
.section-navigation { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; border-bottom: 1px solid #dcdfe6; }
a { padding: 10px 15px; color: #606266; text-decoration: none; border-bottom: 2px solid transparent; }
a.selected { color: #337ecc; border-bottom-color: #409eff; }
a:hover { background: #ecf5ff; }
</style>
