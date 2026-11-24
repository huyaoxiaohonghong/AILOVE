<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from '@/plugins/element-plus'
import {
  createRbacRole,
  deleteRbacRole,
  fetchRbacPermissions,
  fetchRbacRoles,
  updateRbacRole,
  type PermissionGroup,
  type RbacRoleItem,
} from '@/api/rbac'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('rbac:role:manage'))

const loading = ref(false)
const roles = ref<RbacRoleItem[]>([])
const permissionGroups = ref<PermissionGroup[]>([])
const selectedRole = ref<RbacRoleItem | null>(null)

const dialogVisible = ref(false)
const saving = ref(false)
const editingRole = ref<RbacRoleItem | null>(null)
const formRef = ref<FormInstance>()

const form = reactive({
  code: '',
  name: '',
  description: '',
  is_admin_portal: true,
  is_enabled: true,
  sort_order: 50,
  permissions: [] as string[],
})

const rules: FormRules = {
  code: [
    { required: true, message: '请输入角色编码', trigger: 'blur' },
    {
      pattern: /^[a-z][a-z0-9_]{1,31}$/,
      message: '须以小写字母开头，仅含小写字母/数字/下划线（2~32位）',
      trigger: 'blur',
    },
  ],
  name: [{ required: true, message: '请输入角色展示名称', trigger: 'blur' }],
}

const allPermissionCount = computed(() =>
  permissionGroups.value.reduce((acc, g) => acc + g.items.length, 0),
)

const isEditingSuperAdmin = computed(() => editingRole.value?.code === 'super_admin')

async function loadAll() {
  loading.value = true
  try {
    const [permRes, roleRes] = await Promise.all([fetchRbacPermissions(), fetchRbacRoles()])
    permissionGroups.value = permRes.groups
    roles.value = roleRes.items
    if (roleRes.items.length > 0) {
      const currentId = selectedRole.value?.id
      selectedRole.value =
        roleRes.items.find((r) => r.id === currentId) ?? roleRes.items[0] ?? null
    } else {
      selectedRole.value = null
    }
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  editingRole.value = null
  form.code = ''
  form.name = ''
  form.description = ''
  form.is_admin_portal = true
  form.is_enabled = true
  form.sort_order = 50
  form.permissions = ['dashboard:view', 'ai:chat']
  dialogVisible.value = true
}

function openEditDialog(role: RbacRoleItem) {
  editingRole.value = role
  form.code = role.code
  form.name = role.name
  form.description = role.description
  form.is_admin_portal = role.is_admin_portal
  form.is_enabled = role.is_enabled
  form.sort_order = role.sort_order
  form.permissions = [...role.permissions]
  dialogVisible.value = true
}

function isGroupAllSelected(group: PermissionGroup): boolean {
  return group.items.every((item) => form.permissions.includes(item.code))
}

function toggleGroup(group: PermissionGroup, checked: boolean) {
  const codes = group.items.map((i) => i.code)
  if (checked) {
    const next = new Set([...form.permissions, ...codes])
    form.permissions = Array.from(next)
  } else {
    form.permissions = form.permissions.filter((c) => !codes.includes(c))
  }
}

function roleHasPerm(role: RbacRoleItem, permCode: string): boolean {
  return role.permissions.includes('*') || role.permissions.includes(permCode)
}

async function handleSave() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    if (editingRole.value === null) {
      const created = await createRbacRole({
        code: form.code.trim().toLowerCase(),
        name: form.name.trim(),
        description: form.description.trim(),
        permissions: form.permissions,
        is_admin_portal: form.is_admin_portal,
        is_enabled: form.is_enabled,
        sort_order: form.sort_order,
      })
      ElMessage.success(`自定义角色「${created.name}」创建成功`)
      selectedRole.value = created
    } else {
      const updated = await updateRbacRole(editingRole.value.id, {
        name: form.name.trim(),
        description: form.description.trim(),
        permissions: form.permissions,
        is_admin_portal: form.is_admin_portal,
        is_enabled: form.is_enabled,
        sort_order: form.sort_order,
      })
      ElMessage.success(`角色「${updated.name}」权限已更新并热生效`)
      selectedRole.value = updated
    }
    dialogVisible.value = false
    await loadAll()
  } finally {
    saving.value = false
  }
}

async function handleDelete(role: RbacRoleItem) {
  try {
    await ElMessageBox.confirm(`确认删除自定义角色「${role.name} (${role.code})」？`, '删除确认', {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteRbacRole(role.id)
    ElMessage.success('自定义角色已删除')
    await loadAll()
  } catch {
    // 取消
  }
}

onMounted(() => {
  void loadAll()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <h2 class="page-title">RBAC 角色与权限中心</h2>
        <p class="page-subtitle">
          精细化分配管理端角色与 API 权限点，支持自定义角色热创建，授权变更经 Redis 秒级同步全集群
        </p>
      </div>
      <div class="header-actions">
        <el-button icon="Refresh" @click="loadAll">刷新</el-button>
        <el-button v-if="canManage" type="primary" icon="Plus" @click="openCreateDialog">
          新建自定义角色
        </el-button>
      </div>
    </div>

    <el-row :gutter="18">
      <!-- 左侧角色列表 -->
      <el-col :xs="24" :lg="13">
        <div class="page-card">
          <div class="card-head">
            <h3>系统角色列表（{{ roles.length }}）</h3>
            <span class="sub-hint mono-num">全站共 {{ allPermissionCount }} 个细粒度权限点</span>
          </div>

          <el-table
            :data="roles"
            highlight-current-row
            border
            @row-click="(row: RbacRoleItem) => (selectedRole = row)"
          >
            <el-table-column label="角色名称" min-width="155">
              <template #default="{ row }">
                <div class="role-title-cell">
                  <strong>{{ row.name }}</strong>
                  <div class="role-tags">
                    <el-tag v-if="row.is_system" size="small" type="info" effect="plain">
                      内置
                    </el-tag>
                    <el-tag v-if="row.is_admin_portal" size="small" type="warning" effect="light">
                      管理后台
                    </el-tag>
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column prop="code" label="角色编码" width="120">
              <template #default="{ row }">
                <code class="mono-num code-pill">{{ row.code }}</code>
              </template>
            </el-table-column>

            <el-table-column label="权限数" width="85" align="center">
              <template #default="{ row }">
                <span class="mono-num">
                  {{ row.permissions.includes('*') ? '全部 (*)' : row.permissions.length }}
                </span>
              </template>
            </el-table-column>

            <el-table-column label="绑定账号" width="85" align="center">
              <template #default="{ row }">
                <span class="mono-num">{{ row.user_count }}</span>
              </template>
            </el-table-column>

            <el-table-column label="状态" width="76" align="center">
              <template #default="{ row }">
                <el-tag :type="row.is_enabled ? 'success' : 'danger'" size="small">
                  {{ row.is_enabled ? '启用' : '禁用' }}
                </el-tag>
              </template>
            </el-table-column>

            <el-table-column v-if="canManage" label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click.stop="openEditDialog(row)">配置权限</el-button>
                <el-button
                  v-if="!row.is_system"
                  link
                  type="danger"
                  @click.stop="handleDelete(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>

      <!-- 右侧权限矩阵详情预览 -->
      <el-col :xs="24" :lg="11">
        <div class="page-card matrix-card">
          <template v-if="selectedRole">
            <div class="matrix-head">
              <div>
                <div class="matrix-title-row">
                  <h3>{{ selectedRole.name }}</h3>
                  <code class="mono-num code-pill">{{ selectedRole.code }}</code>
                </div>
                <p class="matrix-desc">{{ selectedRole.description || '暂无职责描述' }}</p>
              </div>
              <el-button
                v-if="canManage"
                size="small"
                type="primary"
                plain
                @click="openEditDialog(selectedRole)"
              >
                编辑授权
              </el-button>
            </div>

            <el-alert
              v-if="selectedRole.permissions.includes('*')"
              title="超级通配符 (*) 已激活：该角色自动拥有系统当前及未来新增的所有权限点。"
              type="warning"
              show-icon
              :closable="false"
              style="margin-bottom: 14px"
            />

            <div class="perm-matrix">
              <div v-for="group in permissionGroups" :key="group.group" class="perm-group-box">
                <div class="perm-group-title">{{ group.label }}</div>
                <div class="perm-chip-grid">
                  <div
                    v-for="perm in group.items"
                    :key="perm.code"
                    class="perm-chip"
                    :class="roleHasPerm(selectedRole, perm.code) ? 'is-granted' : 'is-none'"
                    :title="perm.description"
                  >
                    <span class="perm-dot" />
                    <div class="perm-info">
                      <span class="perm-name">{{ perm.label }}</span>
                      <span class="perm-code mono-num">{{ perm.code }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </el-col>
    </el-row>

    <!-- 新建 / 编辑角色与权限勾选矩阵弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingRole === null ? '新建自定义角色' : `编辑角色与权限 · ${editingRole.name}`"
      width="680px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="105px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="角色编码" prop="code">
              <el-input
                v-model="form.code"
                :disabled="editingRole !== null"
                placeholder="例如：auditor_ro"
                maxlength="32"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="角色名称" prop="name">
              <el-input v-model="form.name" placeholder="例如：安全巡检专员" maxlength="64" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="职责描述">
          <el-input v-model="form.description" placeholder="说明该角色适用人群与边界" maxlength="255" />
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="管理后台入口">
              <el-switch v-model="form.is_admin_portal" :disabled="isEditingSuperAdmin" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="启用状态">
              <el-switch
                v-model="form.is_enabled"
                :disabled="editingRole?.code === 'super_admin' || editingRole?.code === 'user'"
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="排序权重">
              <el-input-number v-model="form.sort_order" :min="1" :max="999" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="权限勾选矩阵">
          <el-alert
            v-if="isEditingSuperAdmin"
            title="超级管理员默认保有通配符权限 (*)，不可取消。"
            type="warning"
            show-icon
            :closable="false"
            style="width: 100%"
          />
          <div v-else class="dialog-perm-matrix">
            <div v-for="group in permissionGroups" :key="group.group" class="dialog-group">
              <div class="dialog-group-head">
                <el-checkbox
                  :model-value="isGroupAllSelected(group)"
                  @change="(val: string | number | boolean) => toggleGroup(group, Boolean(val))"
                >
                  <strong>{{ group.label }}</strong>
                </el-checkbox>
              </div>
              <el-checkbox-group v-model="form.permissions" class="dialog-perm-list">
                <el-checkbox v-for="perm in group.items" :key="perm.code" :value="perm.code">
                  <span>{{ perm.label }}</span>
                  <span class="perm-mini-code mono-num">({{ perm.code }})</span>
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存并热生效</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.header-actions {
  display: flex;
  gap: 10px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.card-head h3 {
  margin: 0;
  font-family: var(--ailove-font-display);
  font-size: 16px;
  font-weight: 600;
}

.sub-hint {
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.role-title-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.role-tags {
  display: flex;
  gap: 6px;
}

.code-pill {
  background: rgba(26, 22, 29, 0.05);
  padding: 2px 7px;
  border-radius: 5px;
  font-size: 12px;
}

.matrix-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.matrix-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.matrix-title-row h3 {
  margin: 0;
  font-family: var(--ailove-font-display);
  font-size: 17px;
}

.matrix-desc {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
}

.perm-matrix {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.perm-group-box {
  padding: 12px;
  border-radius: 10px;
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
}

.perm-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--ailove-ink-muted);
  margin-bottom: 8px;
}

.perm-chip-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.perm-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid var(--ailove-border);
  background: #ffffff;
}

.perm-chip.is-granted {
  border-color: var(--ailove-brand-200);
  background: #fff9fa;
}

.perm-chip.is-none {
  opacity: 0.52;
}

.perm-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--ailove-ink-muted);
}

.perm-chip.is-granted .perm-dot {
  background: var(--ailove-success);
}

.perm-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.perm-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--ailove-ink-primary);
}

.perm-code {
  font-size: 10.5px;
  color: var(--ailove-ink-muted);
}

.dialog-perm-matrix {
  width: 100%;
  max-height: 310px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px;
}

.dialog-group {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
}

.dialog-group-head {
  margin-bottom: 6px;
}

.dialog-perm-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}

.perm-mini-code {
  font-size: 11px;
  color: var(--ailove-ink-muted);
  margin-left: 3px;
}

@media (max-width: 640px) {
  .perm-chip-grid {
    grid-template-columns: 1fr;
  }
}
</style>
