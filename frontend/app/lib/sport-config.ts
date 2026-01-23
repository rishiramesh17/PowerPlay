import { SportField, AIModelConfig } from './types'

// Sport-specific field configurations
export const getSportFields = (sport: string): SportField[] => {
  switch (sport) {
    case "cricket":
      return [
        { name: "format", label: "Format", type: "select", options: ["Test", "ODI", "T20", "T10"] },
        { name: "innings", label: "Innings", type: "select", options: ["1st Innings", "2nd Innings", "Both"] },
        { name: "tournament", label: "Tournament", type: "input", placeholder: "ex: World Cup" },
        { name: "venue", label: "Action", type: "select", options: ["Batting", "Bowling"] },      ]
    default:
      return []
  }
}

// AI Model Configuration
export const getAIModelConfig = (confidenceThreshold: number): AIModelConfig => {
  return {
    yolo: {
      model: "yolov8x.pt",
      confidence: confidenceThreshold,
      classes: [0], // person class
      tracking: true
    },
    mediapipe: {
      pose: true,
      face: true,
      hands: false,
      holistic: false
    },
    deepface: {
      model: "FaceNet",
      distance_metric: "cosine",
      enforce_detection: false
    },
    osnet: {
      model: "osnet_x1_0",
      max_dist: 0.6,
      min_confidence: 0.3
    }
  }
}

// Default detection settings
export const defaultDetectionSettings = {
  useYOLO: true,
  useMediaPipe: true,
  useDeepFace: true,
  useOSNet: true,
  confidenceThreshold: 0.7,
  trackingMethod: "reid",
  highlightTypes: ["scoring", "defensive", "teamwork", "individual"],
} 