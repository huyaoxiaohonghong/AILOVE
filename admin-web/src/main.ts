import { createApp } from 'vue'

import App from './App.vue'
import { setupElementPlus } from './plugins/element-plus'
import router from './router'
import { pinia } from './stores'
import './styles/index.css'

const app = createApp(App)

setupElementPlus(app)
app.use(pinia)
app.use(router)

app.mount('#app')
