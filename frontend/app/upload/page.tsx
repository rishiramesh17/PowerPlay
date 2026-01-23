"use client"

import { useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ArrowLeft, Upload, Youtube, LinkIcon, Clock, Target, Loader2, Eye, Download } from "lucide-react"
import { API_BASE } from "@/lib.gpu/api"

export default function UploadPage() {
  const [playerName, setPlayerName] = useState("")
  const [jerseyNumber, setJerseyNumber] = useState("")
  const [jerseyColor, setJerseyColor] = useState("")
  const [videoFile, setVideoFile] = useState<File | null>(null)
  const [youtubeUrl, setYoutubeUrl] = useState("")
  const [action, setAction] = useState("batting")
  const [helmetColor, setHelmetColor] = useState("")
  const [padColor, setPadColor] = useState("")
  const [gloveColor, setGloveColor] = useState("")
  const [startTime, setStartTime] = useState("")
  const [endTime, setEndTime] = useState("")
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const [highlightUrl, setHighlightUrl] = useState("")
  const [processingStage, setProcessingStage] = useState("")
  const [scope, setScope] = useState<"player" | "team">("player")
  const [segments, setSegments] = useState<[number, number][]>([])
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"

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
    setHelmetColor("")
    setPadColor("")
    setGloveColor("")
    setStartTime("")
    setEndTime("")
    setHighlightUrl("")
    setSegments([])
    setMessage("")
    setProcessingStage("")
  }

  const startAnalysis = async () => {
    const jerseyRaw = jerseyNumber.trim().toLowerCase()
    const jerseyIsMissing = !jerseyRaw || jerseyRaw === "na" || jerseyRaw === "none" || jerseyRaw === "null"

    const jerseyIsProvided = jerseyNumber.trim().length > 0
    const jerseyIsNA = ["na", "none", "n/a"].includes(jerseyNumber.trim().toLowerCase())
    const hasSomeIdentity = (jerseyIsProvided && !jerseyIsNA) || jerseyColor.trim().length > 0

    if (!videoFile && !youtubeUrl) {
      alert("Please upload a video or paste a YouTube link.")
      return
    }

    if (scope === "player" && !jerseyNumber) {
      alert("Please enter jersey number (or switch to Team Mode).")
      return
    }

    setLoading(true)
    setMessage("⏳ Starting video processing...")
    
    if (youtubeUrl) {
      setProcessingStage("🔄 Downloading YouTube video (this may take several minutes)...")
    } else {
      setProcessingStage("Uploading video...")
    }

    try {
      const formData = new FormData()
      if (videoFile) {
        formData.append("video", videoFile)
      }
      if (youtubeUrl) {
        formData.append("youtube_url", youtubeUrl)
      }
      const jersey_number = jerseyIsMissing ? null : jerseyNumber

      formData.append(
        "playerData",
        JSON.stringify({
          name: playerName || (scope === "team" ? "Team Mode" : ""),
          jersey_number: scope === "team" ? "na" : jerseyNumber,
        })
      )
      formData.append("scope", scope)
      formData.append("action", action)
      if (startTime) formData.append("start_time", startTime)
      if (endTime) formData.append("end_time", endTime)

      setProcessingStage("🔍 Detecting player segments...")

      const res = await fetch(`${API_BASE}/process-video`, {
        method: "POST",
        body: formData,
      })

      setProcessingStage("🎬 Compiling highlight video...")

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
        setMessage(`✅ Processing complete! Found ${data.segments?.length || 0} highlight segments. Your video is ready.`)
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
            <Link href="/" className="text-powerplay-primary hover:text-powerplay-secondary transition-colors">
              <ArrowLeft className="w-6 h-6" />
            </Link>
            <div>
              <h1 className="text-2xl font-bold text-powerplay-primary">PowerPlay</h1>
              <p className="text-powerplay-secondary text-sm">AI-Powered Sports Highlights</p>
            </div>
          </div>
          
          <Link 
            href="/practice-mode" 
            className="bg-powerplay-button hover:bg-powerplay-button-hover text-powerplay-primary px-4 py-2 rounded-lg font-medium transition-colors duration-200 flex items-center space-x-2"
          >
            <span>🏏</span>
            <span>Switch to Practice Mode</span>
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-4xl mx-auto">
          {/* Page Title */}
          <div className="text-center mb-8">
            <h1 className="text-4xl font-bold text-powerplay-primary mb-4">
              Generate Player Highlights
            </h1>
            <p className="text-xl text-powerplay-secondary">
              Upload a video or paste a YouTube link to generate highlights
            </p>
          </div>

          <Card className="bg-powerplay-card border-powerplay backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-powerplay-primary text-2xl">Video Analysis</CardTitle>
              <CardDescription className="text-powerplay-secondary">
                Upload a video or paste a YouTube link to generate highlights
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Player Information */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-powerplay-primary font-medium mb-2">Player Name</label>
                  <input
                    type="text"
                    value={playerName}
                    onChange={(e) => setPlayerName(e.target.value)}
                    className="w-full p-3 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary placeholder-powerplay-secondary focus:border-amber-400 focus:outline-none transition-colors"
                    placeholder="ex: AB de Villiers"
                  />
                </div>
                <div>
                  <label className="block text-powerplay-primary font-medium mb-2">Jersey Number</label>
                  <input
                    type="text"
                    value={jerseyNumber}
                    onChange={(e) => setJerseyNumber(e.target.value)}
                    className="w-full p-3 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary placeholder-powerplay-secondary focus:border-amber-400 focus:outline-none transition-colors"
                    placeholder="ex: 17"
                  />
                </div>
                <div>
                  <label className="block text-white mb-2 font-medium">
                    Jersey Color: <span className="text-white/50 text-sm font-normal">(recommended)</span>
                  </label>
                  <input
                    type="text"
                    value={jerseyColor}
                    onChange={(e) => setJerseyColor(e.target.value)}
                    className="w-full p-3 rounded-lg bg-white/10 text-white border border-white/20 placeholder-white/50 focus:border-powerplay-button focus:outline-none transition-colors"
                    placeholder='ex: "blue" or "#1e40af"'
                  />
                  <p className="text-xs text-white/50 mt-1">
                    Tip: use a simple color name (blue, red, black) or a hex code.
                  </p>
                </div>
                <div>
                  <label className="block text-powerplay-primary font-medium mb-2">Action Type</label>
                  <select
                    value={action}
                    onChange={(e) => setAction(e.target.value)}
                    className="w-full p-3 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary focus:border-amber-400 focus:outline-none transition-colors"
                  >
                    <option value="batting">Batting</option>
                    <option value="bowling">Bowling</option>
                  </select>
                </div>
              </div>

              {/* New Player Appearance Info */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-powerplay-primary font-medium mb-2">Helmet Color</label>
                  <input
                    type="text"
                    value={helmetColor}
                    onChange={(e) => setHelmetColor(e.target.value)}
                    className="w-full p-3 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary placeholder-powerplay-secondary focus:border-amber-400 focus:outline-none transition-colors"
                    placeholder="ex: blue"
                  />
                </div>
                <div>
                  <label className="block text-powerplay-primary font-medium mb-2">Pad Color</label>
                  <input
                    type="text"
                    value={padColor}
                    onChange={(e) => setPadColor(e.target.value)}
                    className="w-full p-3 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary placeholder-powerplay-secondary focus:border-amber-400 focus:outline-none transition-colors"
                    placeholder="ex: white"
                  />
                </div>
                <div>
                  <label className="block text-powerplay-primary font-medium mb-2">Glove Color</label>
                  <input
                    type="text"
                    value={gloveColor}
                    onChange={(e) => setGloveColor(e.target.value)}
                    className="w-full p-3 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary placeholder-powerplay-secondary focus:border-amber-400 focus:outline-none transition-colors"
                    placeholder="ex: red"
                  />
                </div>
              </div>

              {/* Mode: Player vs Team */}
               <div>
                <label className="block text-white mb-2 font-medium">
                  Mode <span className="text-white/50 text-sm font-normal">(Player or Team)</span>
                </label>
                <select
                  value={scope}
                  onChange={(e) => setScope(e.target.value as "player" | "team")}
                  className="w-full p-3 rounded-lg bg-white/10 text-white border border-white/20 focus:border-powerplay-button focus:outline-none transition-colors cursor-pointer"
                >
                  <option value="player">👤 Player Mode (track one player)</option>
                  <option value="team">👥 Team Mode (collect more clips)</option>
                </select>

                {scope === "team" && (
                  <p className="text-xs text-white/60 mt-2">
                    Team Mode ignores jersey # (we send jersey_number="na") and focuses on collecting more candidate clips.
                  </p>
                )}
              </div>

              {/* Video Upload Section */}
              <div className="space-y-4">
                <label className="block text-powerplay-primary font-medium flex items-center space-x-2">
                  <Upload className="w-5 h-5" />
                  <span>Upload Video File:</span>
                </label>
                <div className="flex items-center space-x-2">
                  <input
                    type="file"
                    accept="video/*"
                    onChange={handleVideoSelect}
                    className="flex-1 p-3 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-powerplay-button file:text-powerplay-primary hover:file:bg-powerplay-button-hover transition-colors"
                  />
                </div>
                {videoFile && (
                  <p className="text-sm text-green-400">
                    ✓ Video file selected: {videoFile.name}
                  </p>
                )}

                {/* OR Divider */}
                <div className="flex items-center space-x-4">
                  <div className="flex-1 h-px bg-powerplay-secondary"></div>
                  <span className="text-powerplay-secondary text-sm font-medium">OR</span>
                  <div className="flex-1 h-px bg-powerplay-secondary"></div>
                </div>

                {/* YouTube Link Section */}
                <div className="space-y-2">
                  <label className="block text-powerplay-primary font-medium flex items-center space-x-2">
                    <Youtube className="w-5 h-5" />
                    <span>Paste YouTube Link:</span>
                  </label>
                  <div className="flex items-center space-x-2">
                    <LinkIcon className="w-5 h-5 text-powerplay-secondary" />
                    <input
                      type="text"
                      value={youtubeUrl}
                      onChange={(e) => handleYoutubeInput(e.target.value)}
                      className="w-full p-3 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary placeholder-powerplay-secondary focus:border-amber-400 focus:outline-none transition-colors"
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
                <label className="block text-powerplay-primary font-medium">
                  Time Range <span className="text-powerplay-secondary text-sm">(Optional)</span>
                </label>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-powerplay-secondary mb-1 text-sm flex items-center space-x-1">
                      <Clock className="w-4 h-4" /> <span>Start Time</span>
                    </label>
                    <input
                      type="text"
                      value={startTime}
                      onChange={(e) => setStartTime(e.target.value)}
                      className="w-full p-2 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary placeholder-powerplay-secondary focus:border-amber-400 focus:outline-none transition-colors"
                      placeholder="00:30:00"
                    />
                  </div>
                  <div>
                    <label className="block text-powerplay-secondary mb-1 text-sm flex items-center space-x-1">
                      <Clock className="w-4 h-4" /> <span>End Time</span>
                    </label>
                    <input
                      type="text"
                      value={endTime}
                      onChange={(e) => setEndTime(e.target.value)}
                      className="w-full p-2 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary placeholder-powerplay-secondary focus:border-amber-400 focus:outline-none transition-colors"
                      placeholder="02:00:00"
                    />
                  </div>
                </div>
                <p className="text-xs text-powerplay-secondary mt-1">Format: hh:mm:ss</p>
                <p className="text-xs text-amber-300 mt-1">
                  💡 Setting a timeframe can significantly speed up processing time!
                </p>
              </div>

              {/* Action Buttons */}
              <div className="flex justify-between pt-4">
                {highlightUrl && (
                  <Button 
                    onClick={resetForm} 
                    variant="outline" 
                    className="border-powerplay text-powerplay-primary hover:bg-powerplay-card"
                  >
                    Start New
                  </Button>
                )}
                <Button 
                  onClick={startAnalysis}
                  disabled={loading || (!videoFile && !youtubeUrl) || !jerseyNumber} 
                  className="bg-powerplay-button hover:bg-powerplay-button-hover disabled:opacity-50 disabled:cursor-not-allowed flex-1 ml-2"
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
                    <span className="text-amber-300">{processingStage}</span>
                  </div>
                  {youtubeUrl && processingStage.includes("Downloading") && (
                    <div className="mt-2 text-amber-200 text-sm">
                      <p>⏱️ YouTube downloads can take 5-15 minutes depending on video length and internet speed.</p>
                      <p>💡 Tip: For faster processing, try shorter videos or use the timestamp feature to select specific sections.</p>
                      <p>🚀 Live streams: Use timestamps to extract only the section you need - this can reduce processing time from hours to minutes!</p>
                      <p>⚠️ Live streams may have format restrictions - the system will automatically try multiple download methods.</p>
                    </div>
                  )}
                </div>
              )}

              {/* Status Message */}
              {message && (
                <div className={`mt-4 p-4 rounded-lg ${
                  message.includes('✅') 
                    ? 'bg-green-500/20 border border-green-500/30 text-green-300' 
                    : message.includes('❌') 
                    ? 'bg-red-500/20 border border-red-500/30 text-red-300'
                    : 'bg-blue-500/20 border border-blue-500/30 text-blue-300'
                }`}>
                  {message}
                </div>
              )}

              {/* Highlight Video Display */}
              {highlightUrl && (
                <div className="mt-6 space-y-4">
                  <h3 className="text-xl font-semibold text-powerplay-primary">Generated Highlight</h3>
                  
                  {/* Video Player */}
                  <div className="relative">
                    <video 
                      controls 
                      className="w-full rounded-lg bg-black"
                      src={highlightUrl}
                    >
                      Your browser does not support the video tag.
                    </video>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex space-x-4">
                    <Button 
                      onClick={() => window.open(highlightUrl, '_blank')}
                      className="bg-powerplay-accent hover:bg-powerplay-accent-hover"
                    >
                      <Eye className="w-4 h-4 mr-2" />
                      View
                    </Button>
                    <Button 
                      onClick={() => {
                        const link = document.createElement('a')
                        link.href = highlightUrl
                        link.download = 'highlight.mp4'
                        link.click()
                      }}
                      variant="outline"
                      className="border-powerplay text-powerplay-primary hover:bg-powerplay-card"
                    >
                      <Download className="w-4 h-4 mr-2" />
                      Download
                    </Button>
                  </div>

                  {/* Segments Info */}
                  {segments.length > 0 && (
                    <div className="mt-4 p-4 bg-powerplay-card border border-powerplay rounded-lg">
                      <h4 className="text-powerplay-primary font-medium mb-2">Detected Segments:</h4>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        {segments.map((segment, index) => (
                          <div key={index} className="text-sm text-powerplay-secondary">
                            {segment[0].toFixed(1)}s - {segment[1].toFixed(1)}s
                          </div>
                        ))}
                      </div>
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
