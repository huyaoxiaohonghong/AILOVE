import { request } from '@/utils/request'

export type CaptchaScene = 'login' | 'register' | 'reset_password'

export interface SliderChallenge {
  captcha_id: string
  scene: CaptchaScene
  bg_image: string
  piece_image: string
  piece_y: number
  canvas_width: number
  canvas_height: number
  piece_size: number
  expires_in: number
}

export interface TrailPoint {
  x: number
  y: number
  t: number
}

export interface SliderVerifyResult {
  passed: boolean
  human_score: number
  captcha_token: string | null
  reason: string
  metrics: Record<string, unknown>
}

export interface EmailAnalysisResult {
  email: string
  canonical_email: string
  allowed: boolean
  trust_score: number
  category: string
  provider: string
  mx_hosts: string[]
  reasons: string[]
  summary: string
}

export interface SessionMeta {
  session_id: string
  expires_at: string
  remaining_seconds: number
  online_count: number
  max_sessions: number
  ttl_hours: number
}

export interface SessionItem {
  session_id: string
  ip: string
  device_label: string
  login_at: string
  last_active_at: string
  expires_at: string
  remaining_seconds: number
  is_current: boolean
}

export interface SessionListResult {
  items: SessionItem[]
  online_count: number
  max_sessions: number
  ttl_hours: number
}

export interface LoginLogItem {
  id: number
  account: string
  ip: string
  device_label: string
  status: string
  fail_reason: string
  created_at: string
}

export interface UserProfile {
  id: number
  username: string | null
  email: string
  nickname: string
  role: string
  role_name?: string
  is_admin_portal?: boolean
  permissions?: string[]
  register_source: string
  email_provider: string
  email_trust_score: number
  auth_mode: string
  session?: SessionMeta
}

export interface AuthTokenResult {
  access_token: string
  token_type: string
  expires_in: number
  session_id: string
  expires_at: string
  user: UserProfile
}

export function createSliderCaptcha(scene: CaptchaScene) {
  return request<SliderChallenge>({
    url: '/captcha/slider/create',
    method: 'post',
    data: { scene },
  })
}

export function verifySliderCaptcha(data: {
  captcha_id: string
  scene: CaptchaScene
  final_x: number
  duration_ms: number
  trail: TrailPoint[]
}) {
  return request<SliderVerifyResult>({
    url: '/captcha/slider/verify',
    method: 'post',
    data,
  })
}

export function checkEmailPolicy(email: string) {
  return request<EmailAnalysisResult>({
    url: '/auth/check-email',
    method: 'post',
    data: { email },
  })
}

export function sendEmailCode(data: {
  email: string
  scene: 'register' | 'reset_password'
  captcha_token: string
}) {
  return request<{
    sent: boolean
    email: string
    scene: 'register' | 'reset_password'
    expire_minutes: number
    cooldown_seconds: number
  }>({
    url: '/auth/email-code/send',
    method: 'post',
    data,
  })
}

export function registerByEmail(data: {
  email: string
  password: string
  nickname?: string
  captcha_token: string
  email_code?: string
  invite_code?: string
}) {
  return request<AuthTokenResult>({
    url: '/auth/register',
    method: 'post',
    data,
  })
}

export function resetPasswordByEmail(data: {
  email: string
  email_code: string
  new_password: string
}) {
  return request<{
    reset: boolean
    email: string
    revoked_sessions: number
  }>({
    url: '/auth/reset-password',
    method: 'post',
    data,
  })
}

export function loginAccount(data: {
  account: string
  password: string
  captcha_token: string
}) {
  return request<AuthTokenResult>({
    url: '/auth/login',
    method: 'post',
    data,
  })
}

export function fetchCurrentUser() {
  return request<UserProfile>({
    url: '/auth/me',
    method: 'get',
  })
}

export function logoutAccount() {
  return request<{ logged_out: boolean }>({
    url: '/auth/logout',
    method: 'post',
  })
}

export function updateMyProfile(nickname: string) {
  return request<UserProfile>({
    url: '/auth/profile',
    method: 'patch',
    data: { nickname },
  })
}

export function changeMyPassword(data: {
  current_password: string
  new_password: string
  logout_other_devices: boolean
}) {
  return request<{ changed: boolean; revoked_other_devices: number }>({
    url: '/auth/change-password',
    method: 'post',
    data,
  })
}

export function fetchMySessions() {
  return request<SessionListResult>({
    url: '/auth/sessions',
    method: 'get',
  })
}

export function revokeMySession(sessionId: string) {
  return request<{ session_id: string; revoked: boolean }>({
    url: `/auth/sessions/${encodeURIComponent(sessionId)}`,
    method: 'delete',
  })
}

export function revokeOtherSessions() {
  return request<{ revoked_count: number }>({
    url: '/auth/sessions/revoke-others',
    method: 'post',
  })
}

export function fetchMyLoginLogs() {
  return request<{ items: LoginLogItem[] }>({
    url: '/auth/login-logs',
    method: 'get',
  })
}
