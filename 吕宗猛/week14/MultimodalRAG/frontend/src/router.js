import { createRouter, createWebHistory } from 'vue-router'
import UploadView from './views/UploadView.vue'
import ChatView from './views/ChatView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/upload' },
    { path: '/upload', name: 'upload', component: UploadView },
    { path: '/chat', name: 'chat', component: ChatView },
  ],
})

export default router
