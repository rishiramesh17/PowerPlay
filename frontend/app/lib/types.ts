// Form data types
export interface FormData {
  team: string
  opponent: string
  date: string
  duration: string
  quality: string
  // Sport-specific fields
  fieldType: string
  gameType: string
  league: string
  season: string
  tournament: string
  venue: string
  weather: string
  surface: string
  format: string
  innings: string
  overs: string
  period: string
  quarter: string
  half: string
  set: string
  match: string
}

// Detection settings types
export interface DetectionSettings {
  useYOLO: boolean
  useMediaPipe: boolean
  useDeepFace: boolean
  useOSNet: boolean
  confidenceThreshold: number
  trackingMethod: string
  highlightTypes: string[]
}

// Sport field configuration types
export interface SportField {
  name: string
  label: string
  type: "select" | "input"
  options?: string[]
  placeholder?: string
}

// AI Model configuration types
export interface AIModelConfig {
  yolo: {
    model: string
    confidence: number
    classes: number[]
    tracking: boolean
  }
  mediapipe: {
    pose: boolean
    face: boolean
    hands: boolean
    holistic: boolean
  }
  deepface: {
    model: string
    distance_metric: string
    enforce_detection: boolean
  }
  osnet: {
    model: string
    max_dist: number
    min_confidence: number
  }
}

// Upload step types
export type UploadStep = "upload" | "players" | "processing" | "complete"

// Player images type
export type PlayerImages = { [key: string]: File[] } 