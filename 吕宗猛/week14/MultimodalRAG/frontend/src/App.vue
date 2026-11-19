<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">M</span>
        <div class="brand-title">多模态RAG</div>
      </div>

      <nav class="side-nav">
        <router-link to="/upload" class="side-link">
          <el-icon><DocumentIcon /></el-icon>
          <span>文档解析</span>
        </router-link>
        <router-link to="/chat" class="side-link">
          <el-icon><ChatDotRound /></el-icon>
          <span>多模态问答</span>
        </router-link>
      </nav>

      <div class="session-block">
        <div class="session-heading">
          <span>会话记录</span>
          <el-button link type="primary" @click="newSession">＋ 新建</el-button>
        </div>
        <div class="session-list">
          <div
            v-for="session in chatStore.sessions"
            :key="session.id"
            :class="['session-item', { active: session.id === chatStore.activeSessionId }]"
            @click="openSession(session.id)"
          >
            <span class="session-title">{{ session.title || '新会话' }}</span>
            <span class="session-time">{{ formatTime(session.updated_at) }}</span>
          </div>
          <div v-if="!chatStore.sessions.length" class="session-empty">暂无会话，发一条消息开始</div>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ChatDotRound, Document as DocumentIcon } from '@element-plus/icons-vue'
import { chatStore, refreshSessions } from './store'

const router = useRouter()

function openSession(id) {
  chatStore.activeSessionId = id
  router.push({ path: '/chat', query: { session: id } })
}

function newSession() {
  router.push({ path: '/chat', query: { new: Date.now() } })
}

function formatTime(value) {
  if (!value) return ''
  return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

onMounted(refreshSessions)
</script>
