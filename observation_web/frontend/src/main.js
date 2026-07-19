import { createApp } from 'vue'
import { createPinia } from 'pinia'

// On-demand Element Plus:
// - Components and icons used in templates are auto-imported (with their styles)
//   by unplugin-vue-components (see vite.config.js).
// - The zhCn locale is applied via <el-config-provider> in App.vue.
// The programmatic APIs (ElMessage / ElMessageBox) are imported per-file but
// their styles are side-effect-free, so we register those styles once here.
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
