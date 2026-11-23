import { request } from '@/utils/request'

export interface PermissionItem {
  code: string
  label: string
  description: string
}

export interface PermissionGroup {
  group: string
  label: string
  items: PermissionItem[]
}

export interface RbacRoleItem {
  id: number
  code: string
  name: string
  description: string
  permissions: string[]
  is_system: boolean
  is_admin_portal: boolean
  is_enabled: boolean
  sort_order: number
  user_count: number
  updated_at: string | null
}

export function fetchRbacPermissions() {
  return request<{ groups: PermissionGroup[] }>({
    url: '/admin/rbac/permissions',
    method: 'get',
  })
}

export function fetchRbacRoles(onlyEnabled = false) {
  return request<{ items: RbacRoleItem[] }>({
    url: '/admin/rbac/roles',
    method: 'get',
    params: onlyEnabled ? { only_enabled: true } : undefined,
  })
}

export function createRbacRole(data: {
  code: string
  name: string
  description: string
  permissions: string[]
  is_admin_portal: boolean
  is_enabled: boolean
  sort_order: number
}) {
  return request<RbacRoleItem>({
    url: '/admin/rbac/roles',
    method: 'post',
    data,
  })
}

export function updateRbacRole(
  roleId: number,
  data: {
    name?: string
    description?: string
    permissions?: string[]
    is_admin_portal?: boolean
    is_enabled?: boolean
    sort_order?: number
  },
) {
  return request<RbacRoleItem>({
    url: `/admin/rbac/roles/${roleId}`,
    method: 'put',
    data,
  })
}

export function deleteRbacRole(roleId: number) {
  return request<{ id: number; deleted: boolean }>({
    url: `/admin/rbac/roles/${roleId}`,
    method: 'delete',
  })
}
