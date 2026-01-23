"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ArrowLeft, Target, Play, Download, Eye, Loader2, LinkIcon, Clock, Upload, Youtube } from "lucide-react"
import Link from "next/link"
import { API_BASE } from "@/lib.gpu/api"

export default function UploadPage() {
    const [playerName, setPlayerName] = useState("")
  const [jerseyNumber, setJerseyNumber] = useState("")
  const [videoFile, setVideoFile] = useState<File | null>(null)
  const [youtubeUrl, setYoutubeUrl] = useState("")
  const [action, setAction] = useState("batting")
  const [startTime, setStartTime] = useState("")
  const [endTime, setEndTime] = useState("")
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const [highlightUrl, setHighlightUrl] = useState("")
  const [processingStage, setProcessingStage] = useState("")
  const [segments, setSegments] = useState<[number, number][]>([])

  // NEW: processing mode and stats from backend
  const [processingMode, setProcessingMode] = useState<"fast" | "balanced" | "high_quality">("balanced")
  const [processingStats, setProcessingStats] = useState<{
    total_time: number
    video_duration: number
    segments_found: number
  } | null>(null)

  const handleVideoSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setVideoFile(e.target.files[0])
      setYoutubeUrl("") // clear youtube url if file chosen
    }
  }

  const handleYoutubeInput = (url: string) => {
    setYoutubeUrl(url)
    setVideoFile(null) // clear file if youtube url entered
  }

  const resetForm = () => {
    setPlayerName("")
    setJerseyNumber("")
    setVideoFile(null)
    setYoutubeUrl("")
    setAction("batting")
    setStartTime("")
    setEndTime("")
    setHighlightUrl("")
    setSegments([])
    setMessage("")
    setProcessingStage("")
    setProcessingMode("balanced")
    setProcessingStats(null)
  }

  const startAnalysis = async () => {
    if ((!videoFile && !youtubeUrl) || !jerseyNumber) {
      alert("Please upload a video or paste a YouTube link, and enter jersey number.")
      return
    }

    setLoading(true)
    setMessage("⏳ Starting video processing...")
    setProcessingStage("Uploading video or fetching link...")

    try {
      // Map processing mode to backend params
      let frameSkip: number
      let detectEvery: number
      let resizeScale: number

      if (processingMode === "fast") {
        frameSkip = 18
        detectEvery = 3
        resizeScale = 0.5
      } else if (processingMode === "high_quality") {
        frameSkip = 6
        detectEvery = 1
        resizeScale = 0.7
      } else {
        // balanced
        frameSkip = 12
        detectEvery = 2
        resizeScale = 0.6
      }

      const formData = new FormData()
      if (videoFile) {
        formData.append("video", videoFile)
      }
      if (youtubeUrl) {
        formData.append("youtube_url", youtubeUrl)
      }
      formData.append(
        "playerData",
        JSON.stringify({
          name: playerName,
          jersey_number: jerseyNumber,
        })
      )
      formData.append("action", action)
      if (startTime) formData.append("start_time", startTime)
      if (endTime) formData.append("end_time", endTime)

      // NEW: send processing parameters to backend
      formData.append("frame_skip", String(frameSkip))
      formData.append("detect_every_n_frames", String(detectEvery))
      formData.append("resize_scale", String(resizeScale))

      setProcessingStage("Detecting player segments...")

      const res = await fetch(`${API_BASE}/process-video`, {
        method: "POST",
        body: formData,
      })

      setProcessingStage("Compiling highlight video...")

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.message || `HTTP error! Status: ${res.status}`)
      }

      const data = await res.json()
      console.log("Backend response:", data)

      if (data.status === "success") {
        const fullUrl = `${API_BASE}${data.highlight_url}`
        setHighlightUrl(fullUrl)
        setSegments(data.segments || [])
        setProcessingStats(data.processing_stats || null)

        setMessage(
          `✅ Processing complete! Found ${data.segments?.length || 0} highlight segments. Your video is ready.`
        )
        setProcessingStage("")
      } else {
        throw new Error(data.message || "Processing failed")
      }
    } catch (error) {
      console.error(error)
      setMessage(`❌ Error: ${error instanceof Error ? error.message : 'Processing failed'}`)
      setProcessingStage("")
    }

    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-powerplay-gradient">
      {/* Header */}
      <header className="border-b border-powerplay bg-black/20 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <Button variant="ghost" size="sm" asChild className="text-white hover:bg-white/10">
              <Link href="/">
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back
              </Link>
            </Button>
            <div className="flex items-center space-x-2">
              <div className="w-8 h-8 bg-powerplay-button rounded-lg flex items-center justify-center">
                <Play className="w-4 h-4 text-white fill-white" />
              </div>
              <span className="text-xl font-bold text-powerplay-primary">PowerPlay</span>
            </div>
          </div>
        </div>
      </header>

      {/* Form Section */}
      <div className="container mx-auto px-4 py-12">
        <div className="max-w-xl mx-auto">
          <Card className="bg-powerplay-gradient-card">
            <CardHeader className="text-center">
              <CardTitle className="text-2xl text-powerplay-primary">Create Player Highlights</CardTitle>
              <CardDescription className="text-powerplay-secondary">
                Upload a video or paste a YouTube link to generate highlights
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              
              {/* Player Info */}
              <div>
                <label className="block text-white mb-2 font-medium">Player Name:</label>
                <input
                  type="text"
                  value={playerName}
                  onChange={(e) => setPlayerName(e.target.value)}
                  className="w-full p-3 rounded-lg bg-white/10 text-white border border-white/20 placeholder-white/50 focus:border-powerplay-button focus:outline-none transition-colors"
                  placeholder="ex: Ab De Villiers"
                />
              </div>
              <div>
                <label className="block text-white mb-2 font-medium">
                  Jersey Number: <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={jerseyNumber}
                  onChange={(e) => setJerseyNumber(e.target.value)}
                  className="w-full p-3 rounded-lg bg-white/10 text-white border border-white/20 placeholder-white/50 focus:border-powerplay-button focus:outline-none transition-colors"
                  placeholder="ex: 17"
                  required
                />
              </div>

              {/* Action Type */}
              <div>
                <label className="block text-white mb-2 font-medium">Action Type:</label>
                <select
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                  className="w-full p-3 rounded-lg bg-white/10 text-white border border-white/20 focus:border-powerplay-button focus:outline-none transition-colors cursor-pointer"
                >
                  <option value="batting">Batting</option>
                  <option value="bowling">Bowling</option>
                </select>
              </div>

               {/* Processing Mode */}
                            <div>
                <label className="block text-white mb-2 font-medium">
                  Processing Mode{" "}
                  <span className="text-white/50 text-sm font-normal">(speed vs quality)</span>
                </label>
                <select
                  value={processingMode}
                  onChange={(e) =>
                    setProcessingMode(e.target.value as "fast" | "balanced" | "high_quality")
                  }
                  className="w-full p-3 rounded-lg bg-white/10 text-white border border-white/20 focus:border-powerplay-button focus:outline-none transition-colors cursor-pointer"
                >
                  <option value="fast">⚡ Fast (shorter processing, may miss some plays)</option>
                  <option value="balanced">⚖️ Balanced (recommended)</option>
                  <option value="high_quality">
                    🎯 High Quality (slower, more detailed detection)
                  </option>
                </select>
              </div>

              {/* Video Source Section - Always show both options */}
              <div className="space-y-4">
                <label className="block text-white font-medium">
                  Upload Video: <span className="text-red-400">*</span>
                </label>
                
                {/* File Upload Section */}
                <div className="p-4 bg-white/5 rounded-lg border-2 border-dashed border-white/20 hover:border-white/30 transition-colors">
                  <div className="text-center">
                    <Upload className="w-8 h-8 mx-auto mb-2 text-white/60" />
                    <label className="block cursor-pointer">
                      <span className="text-white/80 text-sm">Click to select video file</span>
                      <input 
                        type="file" 
                        accept="video/*" 
                        onChange={handleVideoSelect}
                        className="hidden"
                      />
                    </label>
                    <p className="text-xs text-white/50 mt-1">MP4, AVI, MOV files supported</p>
                    {videoFile && (
                      <p className="mt-2 text-sm text-green-400">
                        ✓ Selected: {videoFile.name}
                      </p>
                    )}
                  </div>
                </div>

                {/* OR Divider */}
                <div className="flex items-center space-x-4">
                  <div className="flex-1 h-px bg-white/20"></div>
                  <span className="text-white/60 text-sm font-medium">OR</span>
                  <div className="flex-1 h-px bg-white/20"></div>
                </div>

                {/* YouTube Link Section */}
                <div className="space-y-2">
                  <label className="block text-white font-medium flex items-center space-x-2">
                    <Youtube className="w-5 h-5" />
                    <span>Paste YouTube Link:</span>
                  </label>
                  <div className="flex items-center space-x-2">
                    <LinkIcon className="w-5 h-5 text-white/60" />
                    <input
                      type="text"
                      value={youtubeUrl}
                      onChange={(e) => handleYoutubeInput(e.target.value)}
                      className="w-full p-3 rounded-lg bg-white/10 text-white border border-white/20 placeholder-white/50 focus:border-powerplay-button focus:outline-none transition-colors"
                      placeholder="https://youtube.com/watch?v=..."
                    />
                  </div>
                  {youtubeUrl && (
                    <p className="text-sm text-green-400">
                      ✓ YouTube URL added
                    </p>
                  )}
                </div>
              </div>

              {/* Start/End Timestamps - Optional */}
              <div className="space-y-2">
                <label className="block text-white font-medium">
                  Time Range <span className="text-white/50 text-sm">(Optional)</span>
                </label>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-white/70 mb-1 text-sm flex items-center space-x-1">
                      <Clock className="w-4 h-4" /> <span>Start Time</span>
                    </label>
                    <input
                      type="text"
                      value={startTime}
                      onChange={(e) => setStartTime(e.target.value)}
                      className="w-full p-2 rounded-lg bg-white/10 text-white border border-white/20 placeholder-white/50 focus:border-powerplay-button focus:outline-none transition-colors"
                      placeholder="00:30:00"
                    />
                  </div>
                  <div>
                    <label className="block text-white/70 mb-1 text-sm flex items-center space-x-1">
                      <Clock className="w-4 h-4" /> <span>End Time</span>
                    </label>
                    <input
                      type="text"
                      value={endTime}
                      onChange={(e) => setEndTime(e.target.value)}
                      className="w-full p-2 rounded-lg bg-white/10 text-white border border-white/20 placeholder-white/50 focus:border-powerplay-button focus:outline-none transition-colors"
                      placeholder="02:00:00"
                    />
                  </div>
                </div>
                <p className="text-xs text-white/50 mt-1">Format: hh:mm:ss</p>
              </div>

              {/* Action Buttons */}
              <div className="flex justify-between pt-4">
                {highlightUrl && (
                  <Button 
                    onClick={resetForm} 
                    variant="outline" 
                    className="border-white/20 text-white hover:bg-white/10"
                  >
                    Start New
                  </Button>
                )}
                <Button 
                  onClick={startAnalysis} 
                  disabled={loading || (!videoFile && !youtubeUrl) || !jerseyNumber} 
                  className="bg-powerplay-button hover:bg-powerplay-button/80 disabled:opacity-50 disabled:cursor-not-allowed flex-1 ml-2"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      <Target className="w-5 h-5 mr-2" />
                      Generate Highlights
                    </>
                  )}
                </Button>
              </div>

              {/* Processing Stage */}
              {processingStage && (
                <div className="mt-4 p-4 bg-amber-500/20 border border-amber-500/30 rounded-lg">
                  <div className="flex items-center space-x-2">
                    <Loader2 className="w-4 h-4 animate-spin text-amber-300" />
                    <p className="text-amber-300 text-sm">{processingStage}</p>
                  </div>
                </div>
              )}

              {/* Final Message + Result */}
              {message && (
                <div className={`mt-4 p-4 rounded-lg ${
                  message.includes("✅") 
                    ? "bg-green-500/20 border border-green-500/30 text-green-300" 
                    : "bg-red-500/20 border border-red-500/30 text-red-300"
                }`}>
                  <p className="text-sm">{message}</p>
                </div>
              )}
              
              {highlightUrl && (
                <div className="space-y-4">
                  <video
                    src={highlightUrl}
                    controls
                    className="w-full rounded-lg border border-powerplay bg-black"
                  />
                  <Button asChild className="w-full bg-green-600 hover:bg-green-700">
                    <a href={highlightUrl} download>
                      <Download className="w-4 h-4 mr-2" />
                      Download Highlights
                    </a>
                  </Button>

                  {/* NEW: processing stats + segments info */}
                  {processingStats && (
                    <div className="mt-2 p-3 rounded-lg bg-white/5 border border-white/10 text-white/80 text-sm space-y-1">
                      <p>
                        <span className="font-semibold">Processing time:</span>{" "}
                        {processingStats.total_time}s
                      </p>
                      <p>
                        <span className="font-semibold">Video duration processed:</span>{" "}
                        {processingStats.video_duration}s
                      </p>
                      <p>
                        <span className="font-semibold">Segments found:</span>{" "}
                        {processingStats.segments_found}
                      </p>
                    </div>
                  )}

                  {segments && segments.length > 0 && (
                    <div className="mt-2 p-3 rounded-lg bg-white/5 border border-white/10 text-white/80 text-xs">
                      <p className="font-semibold mb-1">Segments (start → end seconds):</p>
                      <ul className="space-y-1">
                        {segments.slice(0, 6).map(([s, e], idx) => (
                          <li key={idx}>
                            #{idx + 1}: {s.toFixed(1)}s → {e.toFixed(1)}s
                          </li>
                        ))}
                        {segments.length > 6 && (
                          <li className="text-white/60">
                            …and {segments.length - 6} more
                          </li>
                        )}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}