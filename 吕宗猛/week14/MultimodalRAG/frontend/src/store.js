import { reactive } from 'vue'
import { listSessions } from './api'

export const chatStore = reactive({
  sessions: [],
  activeSessionId: null,
})

export async function refreshSessions() {
  try {
    chatStore.sessions = await listSessions()
    return chatStore.sessions
  } catch {
    return chatStore.sessions
  }
}
