import { request } from '@/utils/request'
import type { MascotGesture, MascotMood } from '@/utils/mascotBrain'
import type { UserLoveProfile } from '@/api/ai'

export interface MascotMemoryItem {
  id: number
  category: string
  summary: string
  keywords: string[]
  importance: number
  valence: number
  recall_count: number
  retention: number
  created_at: string
}

export interface MoodHistoryItem {
  date: string
  score: number
  label: string
  note?: string
}

export interface MascotBackendState {
  valence: number
  arousal: number
  mood: MascotMood
  circadian_phase: string
  interaction_count: number
  pet_count: number
  need_mood_checkin: boolean
  today_mood_score: number
  mood_history: MoodHistoryItem[]
  away_hours: number
  reunion_greeting: string
  memories: MascotMemoryItem[]
  memory_count: number
  affinity: number
  bond_level: number
  bond_title: string
  bond_style: string
  next_level_affinity: number | null
}

export interface MascotInteractResponse {
  gesture: MascotGesture
  reaction_mood: MascotMood
  haptic: string
  bubble: string
  affinity_delta: number
  state: MascotBackendState
}

export interface MascotCheckinResponse {
  score: number
  label: string
  reaction_mood: MascotMood
  reply: string
  state: MascotBackendState
}

export function fetchMascotState() {
  return request<MascotBackendState>({
    url: '/mascot/state',
    method: 'get',
  })
}

export function sendMascotInteract(payload: {
  gesture: MascotGesture
  dv?: number
  da?: number
}) {
  return request<MascotInteractResponse>({
    url: '/mascot/interact',
    method: 'post',
    data: payload,
  })
}

export function submitMascotMoodCheckin(payload: { score: number; note?: string }) {
  return request<MascotCheckinResponse>({
    url: '/mascot/mood-checkin',
    method: 'post',
    data: payload,
  })
}

export function applyMascotProfilePatch(patch: {
  relationship_stage?: string
  partner_nickname?: string
  partner_traits?: string[]
  my_traits?: string[]
  relationship_goal?: string
  communication_taboos?: string
  background_notes?: string
}) {
  return request<{ profile: UserLoveProfile }>({
    url: '/mascot/profile-patch',
    method: 'post',
    data: patch,
  })
}

export function fetchMascotMemories() {
  return request<{ items: MascotMemoryItem[]; total: number }>({
    url: '/mascot/memories',
    method: 'get',
  })
}

export function deleteMascotMemory(memoryId: number) {
  return request<{ deleted_id: number }>({
    url: `/mascot/memories/${memoryId}`,
    method: 'delete',
  })
}
