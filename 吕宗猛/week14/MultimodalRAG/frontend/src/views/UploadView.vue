<template>
  <section class="page">
    <div class="page-heading">
      <div>
        <h1>文档解析</h1>
        <p>上传多个 PDF，经 Kafka 投递到 MinerU 解析，图片会作为独立资源保存。</p>
      </div>
      <el-tag type="info" effect="plain">SSE 实时状态</el-tag>
    </div>

    <el-card class="upload-card" shadow="never">
      <el-upload
        v-model:file-list="fileList"
        drag
        multiple
        accept=".pdf"
        :auto-upload="false"
        :on-change="onChange"
        :on-remove="onRemove"
      >
        <el-icon class="upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">把 PDF 拖到这里，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持多选，单文件不超过 100 MB；只接受 PDF。</div>
        </template>
      </el-upload>
      <div class="upload-actions">
        <el-button type="primary" :loading="uploading" @click="startUpload">开始上传</el-button>
        <el-button @click="fileList = []">清空列表</el-button>
      </div>
    </el-card>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>文档状态</span>
          <span class="muted">共 {{ documents.length }} 个文档</span>
        </div>
      </template>
      <el-table :data="documents" stripe style="width: 100%">
        <el-table-column prop="file_name" label="文件名" min-width="260" show-overflow-tooltip />
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <span class="status-pill" :class="'status-' + row.status">
              <el-icon v-if="row.status === 'parsing'" class="is-loading"><Loading /></el-icon>
              {{ statusLabel(row.status) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="image_count" label="图片" width="80" />
        <el-table-column prop="chunk_count" label="分块" width="80" />
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'failed'" type="warning" link @click="retry(row)">重试</el-button>
            <el-tooltip v-if="row.error_msg" :content="row.error_msg" placement="top">
              <el-button type="danger" link>错误</el-button>
            </el-tooltip>
            <span v-if="row.status !== 'failed' && !row.error_msg" class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, UploadFilled } from '@element-plus/icons-vue'
import { openDocumentEvents, retryDocument, uploadDocuments } from '../api'

const fileList = ref([])
const documents = ref([])
const uploading = ref(false)
let eventSource = null

function onChange(file, files) { fileList.value = files }
function onRemove(file, files) { fileList.value = files }

async function startUpload() {
  const files = fileList.value.map((item) => item.raw).filter(Boolean)
  if (!files.length) { ElMessage.warning('请先选择 PDF 文件'); return }
  uploading.value = true
  try {
    await uploadDocuments(files)
    ElMessage.success('已提交解析任务')
    fileList.value = []
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function retry(row) {
  try {
    await retryDocument(row.id)
    ElMessage.success('已重新提交')
  } catch (error) {
    ElMessage.error(error.message || '重试失败')
  }
}

function statusLabel(status) {
  return ({ pending: '待解析', parsing: '解析中', completed: '解析完成', failed: '解析失败' })[status] || status
}
function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
function formatTime(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  eventSource = openDocumentEvents()
  eventSource.addEventListener('documents', (event) => {
    try { documents.value = JSON.parse(event.data) } catch { /* ignore */ }
  })
})
onUnmounted(() => { eventSource?.close() })
</script>
