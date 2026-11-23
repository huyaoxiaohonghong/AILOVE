<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchWechatUsers,
  updateWechatUserStatus,
  type WechatUserItem,
} from '@/api/users'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('miniapp_user:manage'))

const loading = ref(false)
const dbConnected = ref(true)
const tableData = ref<WechatUserItem[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  status: '' as number | '',
})

async function loadUsers() {
  loading.value = true
  try {
    const res = await fetchWechatUsers(query)
    tableData.value = res.items
    total.value = res.total
    dbConnected.value = res.db_connected
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  query.page = 1
  void loadUsers()
}

function handleReset() {
  query.keyword = ''
  query.status = ''
  query.page = 1
  void loadUsers()
}

async function handleToggleStatus(row: WechatUserItem) {
  const nextStatus = row.status === 1 ? 0 : 1
  await updateWechatUserStatus(row.id, nextStatus)
  row.status = nextStatus
  ElMessage.success(nextStatus === 1 ? '已启用该用户' : '已禁用该用户')
}

onMounted(() => {
  void loadUsers()
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2 class="page-title">小程序用户管理</h2>
        <p class="page-subtitle">管理通过微信小程序授权登录的用户列表与账号状态</p>
      </div>
    </div>

    <el-alert
      v-if="!dbConnected"
      title="MySQL 暂未连接，当前展示空列表。连接数据库并从小程序端登录后即可在此查看记录。"
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-alert
      v-if="!canManage"
      title="当前账号仅拥有「小程序用户查看」权限，启停操作按钮已隐藏。"
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <div class="page-card">
      <el-form :inline="true" :model="query" class="search-bar">
        <el-form-item label="关键字">
          <el-input
            v-model="query.keyword"
            placeholder="昵称 / OpenID / 手机号"
            clearable
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 130px">
            <el-option label="正常" :value="1" />
            <el-option label="禁用" :value="0" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="tableData" stripe border>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="nickname" label="昵称" min-width="140" />
        <el-table-column prop="openid" label="OpenID" min-width="200" show-overflow-tooltip />
        <el-table-column prop="phone" label="手机号" width="140">
          <template #default="{ row }">{{ row.phone || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'">
              {{ row.status === 1 ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" label="最后登录时间" width="180">
          <template #default="{ row }">{{ row.last_login_at || '-' }}</template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              :type="row.status === 1 ? 'danger' : 'success'"
              @click="handleToggleStatus(row)"
            >
              {{ row.status === 1 ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          layout="total, sizes, prev, pager, next"
          :page-sizes="[10, 20, 50]"
          @current-change="loadUsers"
          @size-change="loadUsers"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-bar {
  margin-bottom: 12px;
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
