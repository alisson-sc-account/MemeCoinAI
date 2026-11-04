import type { components } from './schema'

export type Schemas = components['schemas']
export type User = Schemas['UserOut']
export type TokenRef = Schemas['TokenRef']
export type Token = Schemas['TokenListItem']
export type TokenDetail = Schemas['TokenDetail']
export type Alert = Schemas['AlertOut']
export type Prediction = Schemas['PredictionOut']
export type Freshness = Schemas['Freshness']
export type Meta = Schemas['MetaOut']
export type Dashboard = Schemas['DashboardSummary']
export type History = Schemas['HistoryOut']
export type ExitEstimate = Schemas['ExitEstimateOut']
export type SystemSources = Schemas['SystemSourcesOut']
export type Health = Schemas['HealthOut']
export type PredictionMetrics = Schemas['PredictionMetricsOut']
export type Signal = Schemas['SignalOut']
export type HorizonEstimate = Schemas['HorizonEstimateOut']
export type Position = Schemas['PositionOut']
export type Advice = Schemas['AdviceOut']
export type SignalPerformance = Schemas['SignalPerformanceOut']
export type AccountSettings = Schemas['AccountSettings']
export type Allocation = Schemas['AllocationOut']
export type Opportunity = Schemas['OpportunityOut']
export type OpportunityPage = Schemas['OpportunityPage']
export type SourceRegistryEntry = Schemas['SourceRegistryOut']
export type Page<T> = { items: T[]; total: number; page: number; page_size: number }
export type ApiErrorBody = { error?: { code?: string; message?: string; details?: unknown } }
export type AccuracyPage = Schemas['AccuracyPage']
export type Favorite = Schemas['FavoriteOut']
export type Phone = Schemas['PhoneOut']
export type AgentStatus = Schemas['AgentStatusOut']
export type Security = Schemas['SecurityOut']
export type BuySimulation = Schemas['BuySimulationOut']
export type FavoritePage = Schemas['FavoritePage']
export type FavoriteReport = Schemas['FavoriteReport']
export type AccuracyItem = Schemas['AccuracyItem']
export type ExitPlan = Schemas['ExitPlanOut']

export type PhonePriority = 'min' | 'low' | 'default' | 'high' | 'urgent'
export type PhoneSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical'
export type PhoneKind = 'burst' | 'buy_strong' | 'buy' | 'sell' | 'risk'
export interface PhoneRule { enabled: boolean; priority: PhonePriority; tags: string; title: string; min_severity: PhoneSeverity }
export interface PhonePrefs {
  enabled: boolean
  server: string
  topic: string
  rules: Record<PhoneKind, PhoneRule>
  body: string
  min_opportunity_score: number
  max_risk_score: number
  min_liquidity_usd: number
  token_cooldown_minutes: number
  max_per_hour: number
  daily_cap: number
  quiet: { enabled: boolean; start: string; end: string; allow_urgent: boolean }
  muted: string[]
  favorites_only: boolean
  favorites_bypass_filters: boolean
}
