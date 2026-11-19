<template>
  <section class="page chat-page">
    <div class="page-heading">
      <div>
        <h1>多模态问答</h1>
        <p>检索 PDF 文本与图片，一起送给 Magpie 的 workbuddy/deepseek-v4.1-flash。</p>
      </div>
      <el-button plain @click="newSession">新建会话</el-button>
    </div>

    <el-card class="chat-card" shadow="never">
      <div ref="messageBox" class="messages">
        <div v-if="!messages.length" class="empty-chat">
          <div class="empty-mark">M</div>
          <p>上传 PDF 后，在这里提问；可以直接 Ctrl+V 粘贴截图，或点击“添加图片”。</p>
        </div>
        <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
          <div class="avatar">{{ message.role === 'user' ? '你' : 'AI' }}</div>
          <div class="bubble">
            <img v-if="message.image_path" :src="message.image_path" class="user-image" alt="用户图片" />
            <div v-if="message.role === 'assistant'" class="markdown" v-html="renderMarkdown(message.content)"></div>
            <div v-else class="plain-text">{{ message.content }}</div>
            <div v-if="message.references?.length" class="references">
              <span class="muted">参考：</span>
              <span v-for="ref in message.references" :key="ref.doc_id + '-' + ref.chunk_index" class="ref-chip">
                {{ ref.file_name }} · 块 {{ ref.chunk_index }}
              </span>
            </div>
          </div>
        </div>
        <div v-if="sending" class="message assistant">
          <div class="avatar">AI</div>
          <div class="bubble typing"><span></span><span></span><span></span></div>
        </div>
      </div>

      <div class="composer">
        <div v-if="imagePreview" class="image-preview">
          <img :src="imagePreview" alt="待发送图片" />
          <el-button circle size="small" @click="clearImage">×</el-button>
        </div>
        <textarea
          ref="questionInput"
          v-model="question"
          class="question-textarea"
          rows="3"
          placeholder="输入问题，支持直接粘贴图片；Enter 发送，Shift+Enter 换行"
          @paste="handlePaste"
          @keydown.enter.exact.prevent="send"
        ></textarea>
        <div class="composer-actions">
          <input ref="fileInput" type="file" accept="image/*" hidden @change="onImageChange" />
          <el-button plain @click="fileInput?.click()">添加图片</el-button>
          <span class="paste-hint">可直接 Ctrl+V 粘贴截图</span>
          <el-button type="primary" :loading="sending" @click="send">发送</el-button>
        </div>
      </div>
    </el-card>
  </section>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { askQuestion, createSession, listMessages } from '../api'
import { chatStore, refreshSessions } from '../store'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const route = useRoute()
const router = useRouter()
const sessionId = ref(null)
const messages = ref([])
const question = ref('')
const sending = ref(false)
const imageFile = ref(null)
const imagePreview = ref('')
const fileInput = ref(null)
const messageBox = ref(null)
const questionInput = ref(null)

function renderMarkdown(text) { return md.render(text || '') }

async function loadSession(id) {
  try {
    const rows = await listMessages(id)
    sessionId.value = id
    chatStore.activeSessionId = id
    messages.value = rows.map((row) => ({
      role: row.role,
      content: row.content,
      image_path: row.image_path || null,
    }))
    await scrollToBottom()
  } catch (error) {
    ElMessage.error(error.message || '加载会话失败')
  }
}

async function createNewSession() {
  try {
    const session = await createSession()
    sessionId.value = session.id
    chatStore.activeSessionId = session.id
    messages.value = []
    await refreshSessions()
    router.replace({ path: '/chat', query: { session: session.id } })
  } catch (error) {
    ElMessage.error(error.message || '创建会话失败')
  }
}

async function newSession() {
  await createNewSession()
}

async function initFromRoute() {
  await refreshSessions()
  if (route.query.new) {
    await createNewSession()
    return
  }
  const id = Number(route.query.session)
  if (id) {
    await loadSession(id)
    return
  }
  if (chatStore.sessions.length) {
    await loadSession(chatStore.sessions[0].id)
    return
  }
  await createNewSession()
}

function setImage(file) {
  imageFile.value = file
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  imagePreview.value = URL.createObjectURL(file)
}

function onImageChange(event) {
  const file = event.target.files?.[0]
  if (file) setImage(file)
}

function handlePaste(event) {
  const items = Array.from(event.clipboardData?.items || [])
  const imageItem = items.find((item) => item.type && item.type.startsWith('image/'))
  if (!imageItem) return
  const file = imageItem.getAsFile()
  if (!file) return
  event.preventDefault()
  setImage(file)
}

function clearImage(revoke = true) {
  imageFile.value = null
  if (revoke && imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  imagePreview.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

async function send() {
  if (sending.value) return
  if (!question.value.trim() && !imageFile.value) {
    ElMessage.warning('请输入问题或添加图片')
    return
  }
  if (!sessionId.value) await createNewSession()
  const text = question.value.trim()
  const preview = imagePreview.value
  messages.value.push({ role: 'user', content: text, image_path: preview })
  question.value = ''
  const file = imageFile.value
  clearImage(false)
  sending.value = true
  await scrollToBottom()
  try {
    const response = await askQuestion(sessionId.value, text, file)
    messages.value.push({
      role: 'assistant',
      content: response.answer,
      references: response.references,
    })
    await refreshSessions()
  } catch (error) {
    ElMessage.error(error.message || '问答失败')
    messages.value.push({ role: 'assistant', content: '**出错了：** ' + (error.message || '未知错误') })
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messageBox.value) messageBox.value.scrollTop = messageBox.value.scrollHeight
}

watch(() => route.query.session, (value) => {
  const id = Number(value)
  if (id && id !== sessionId.value) loadSession(id)
})
watch(() => route.query.new, (value) => {
  if (value) createNewSession()
})

onMounted(initFromRoute)
</script>
