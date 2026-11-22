<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchHealth, type HealthData } from '@/api/system'

const loading = ref(false)
const health = ref<HealthData | null>(null)
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const appTitle = import.meta.env.VITE_APP_TITLE || 'AILOVE 管理后台'

async function loadHealth() {
  loading.value = true
  try {
    health.value = await fetchHealth()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadHealth()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <h2 class="page-title">系统配置与运行信息</h2>
        <p class="page-subtitle">查看前后端环境参数与服务端接入配置指引</p>
      </div>
      <el-button icon="Refresh" @click="loadHealth">重新检测</el-button>
    </div>

    <div class="page-card">
      <el-descriptions title="环境参数" :column="2" border>
        <el-descriptions-item label="前端应用名">{{ appTitle }}</el-descriptions-item>
        <el-descriptions-item label="API Base URL">{{ apiBaseUrl }}</el-descriptions-item>
        <el-descriptions-item label="后端服务名">{{ health?.app || '-' }}</el-descriptions-item>
        <el-descriptions-item label="后端运行环境">{{ health?.env || '-' }}</el-descriptions-item>
        <el-descriptions-item label="综合健康状态">
          <el-tag :type="health?.status === 'ok' ? 'success' : 'warning'">
            {{ health?.status || '-' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="最近探测时间">{{ health?.timestamp || '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-divider />

      <el-alert
        title="配置修改提示"
        description="数据库、Redis、LangChain 模型 API Key 以及微信小程序 AppID/AppSecret 均在 backend/.env 中统一管理，修改后重启 FastAPI 服务即可生效。"
        type="info"
        show-icon
        :closable="false"
      />
    </div>
  </div>
</template>
