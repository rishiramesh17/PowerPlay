// Shared types for PowerPlay API

export interface UploadResponse {
  success: boolean
  message: string
  uploadId: string
  filename?: string
  size?: number
  type?: string
}

export interface AnalysisRequest {
  uploadId: string
  detectionSettings: DetectionSettings
  playerImages?: Record<string, string[]>
}

export interface DetectionSettings {
  useYOLO: boolean
  useMediaPipe: boolean
  useDeepFace: boolean
  useOSNet: boolean
  confidenceThreshold: number
}

export interface AnalysisResponse {
  success: boolean
  message: string
  analysisId: string
  status: 'processing' | 'completed' | 'failed'
  estimatedTime?: string
  uploadId: string
  detectionSettings: DetectionSettings
}

export interface AnalysisStatus {
  analysisId: string
  status: 'processing' | 'completed' | 'failed'
  progress: number
  currentStage: string
  stages: ProcessingStage[]
  estimatedTimeRemaining?: string
}

export interface ProcessingStage {
  name: string
  status: 'waiting' | 'processing' | 'completed' | 'failed'
  progress: number
}

export interface PlayerImage {
  playerId: string
  imageUrls: string[]
  uploadedAt: Date
}

export interface VideoMetadata {
  id: string
  title: string
  description?: string
  sport: string
  filename: string
  size: number
  duration?: number
  uploadedAt: Date
  status: 'uploading' | 'uploaded' | 'processing' | 'completed' | 'failed'
}

export interface HighlightRequest {
  analysisId: string
  playerIds: string[]
  highlightType: 'goals' | 'assists' | 'defensive' | 'all'
  duration: 'short' | 'medium' | 'long'
}

export interface HighlightResponse {
  success: boolean
  message: string
  highlightId: string
  analysisId: string
  status: 'generating' | 'completed' | 'failed'
  estimatedTime?: string
}

export interface User {
  id: string
  email: string
  name: string
  createdAt: Date
  subscription?: Subscription
}

export interface Subscription {
  id: string
  plan: 'free' | 'pro' | 'enterprise'
  status: 'active' | 'cancelled' | 'expired'
  currentPeriodEnd: Date
  features: string[]
}

// Error types
export interface ApiError {
  error: string
  details?: any
  code?: string
}

// Database types (for Prisma)
export interface DatabaseVideo {
  id: string
  userId: string
  title: string
  description?: string
  sport: string
  filename: string
  fileSize: number
  fileUrl: string
  duration?: number
  status: 'uploading' | 'uploaded' | 'processing' | 'completed' | 'failed'
  createdAt: Date
  updatedAt: Date
}

export interface DatabaseAnalysis {
  id: string
  videoId: string
  userId: string
  detectionSettings: DetectionSettings
  status: 'processing' | 'completed' | 'failed'
  progress: number
  currentStage: string
  results?: any
  createdAt: Date
  updatedAt: Date
  completedAt?: Date
}

// External service types
export interface S3UploadResult {
  key: string
  url: string
  bucket: string
  etag: string
}

export interface AIProcessingResult {
  detections: any[]
  poses: any[]
  faces: any[]
  tracks: any[]
  metadata: {
    frameCount: number
    duration: number
    resolution: string
  }
} 