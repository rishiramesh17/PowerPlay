import { useState } from 'react'
import { UploadStep, FormData, DetectionSettings, PlayerImages } from '@/app/lib/types'
import { defaultDetectionSettings } from '@/app/lib/sport-config'

export const useUpload = () => {
  const [uploadStep, setUploadStep] = useState<UploadStep>("upload")
  const [uploadProgress, setUploadProgress] = useState(0)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedSport, setSelectedSport] = useState<string>("")
  const [playerImages, setPlayerImages] = useState<PlayerImages>({})
  const [detectionSettings, setDetectionSettings] = useState<DetectionSettings>(defaultDetectionSettings)
  const [formData, setFormData] = useState<FormData>({
    team: "",
    opponent: "",
    date: "",
    duration: "",
    quality: "",
    fieldType: "",
    gameType: "",
    league: "",
    season: "",
    tournament: "",
    venue: "",
    weather: "",
    surface: "",
    format: "",
    innings: "",
    overs: "",
    period: "",
    quarter: "",
    half: "",
    set: "",
    match: "",
  })

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      setSelectedFile(file)
    }
  }

  const handleSportChange = (sport: string) => {
    setSelectedSport(sport)
    // Reset sport-specific fields when sport changes
    setFormData(prev => ({
      ...prev,
      fieldType: "",
      gameType: "",
      league: "",
      season: "",
      tournament: "",
      venue: "",
      weather: "",
      surface: "",
      format: "",
      innings: "",
      overs: "",
      period: "",
      quarter: "",
      half: "",
      set: "",
      match: "",
    }))
  }

  const handleInputChange = (field: string, value: string) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }))
  }

  const handlePlayerImageUpload = (playerId: string, files: FileList | null) => {
    if (!files) return
    const fileArray = Array.from(files)
    setPlayerImages(prev => ({
      ...prev,
      [playerId]: [...(prev[playerId] || []), ...fileArray]
    }))
  }

  const removePlayerImage = (playerId: string, index: number) => {
    setPlayerImages(prev => ({
      ...prev,
      [playerId]: prev[playerId]?.filter((_, i) => i !== index) || []
    }))
  }

  const handleUpload = () => {
    if (!selectedFile) return
    setUploadStep("players")
  }

  const startAnalysis = async () => {
    setUploadStep("processing")
    
    // Simulate AI processing with different stages
    const stages = [
      { name: "Video Upload", duration: 1000 },
      { name: "YOLO Detection", duration: 2000 },
      { name: "MediaPipe Pose", duration: 1500 },
      { name: "DeepFace Recognition", duration: 2000 },
      { name: "OSNet Tracking", duration: 2500 },
      { name: "Highlight Generation", duration: 3000 }
    ]

    let currentProgress = 0
    for (const stage of stages) {
      await new Promise(resolve => {
        const interval = setInterval(() => {
          currentProgress += 100 / stages.length / (stage.duration / 100)
          setUploadProgress(Math.min(currentProgress, 100))
          if (currentProgress >= 100) {
            clearInterval(interval)
            resolve(true)
          }
        }, 100)
      })
    }
    
    setTimeout(() => setUploadStep("complete"), 1000)
  }

  return {
    // State
    uploadStep,
    uploadProgress,
    selectedFile,
    selectedSport,
    playerImages,
    detectionSettings,
    formData,
    
    // Actions
    setUploadStep,
    setDetectionSettings,
    handleFileSelect,
    handleSportChange,
    handleInputChange,
    handlePlayerImageUpload,
    removePlayerImage,
    handleUpload,
    startAnalysis,
  }
} 