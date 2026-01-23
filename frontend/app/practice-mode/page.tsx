"use client"

import { useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ArrowLeft, Upload, Youtube, LinkIcon, Settings, Target, Loader2, Eye, Download, Scissors, Play } from "lucide-react"

export default function PracticeModePage() {
  const [videoFile, setVideoFile] = useState<File | null>(null)
  const [youtubeUrl, setYoutubeUrl] = useState("")
  const [practiceType, setPracticeType] = useState("batting")
  const [videoLength, setVideoLength] = useState("")
  const [desiredClipLength, setDesiredClipLength] = useState("")
  const [movementThreshold, setMovementThreshold] = useState("0.02")
  const [minMovementDuration, setMinMovementDuration] = useState("0.5")
  const [paddingBefore, setPaddingBefore] = useState("1.0")
  const [paddingAfter, setPaddingAfter] = useState("4.0")
  const [outputMode, setOutputMode] = useState("highlights")
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const [processingStage, setProcessingStage] = useState("")
  const [results, setResults] = useState<any>(null)

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
    setVideoFile(null)
    setYoutubeUrl("")
    setPracticeType("batting")
    setVideoLength("")
    setDesiredClipLength("")
    setMovementThreshold("0.02")
    setMinMovementDuration("0.5")
    setPaddingBefore("1.0")
    setPaddingAfter("4.0")
    setOutputMode("clips")
    setResults(null)
    setMessage("")
    setProcessingStage("")
  }

  const startPracticeAnalysis = async () => {
    if ((!videoFile && !youtubeUrl)) {
      alert("Please upload a video or paste a YouTube link.")
      return
    }

    setLoading(true)
    setMessage("⏳ Starting practice mode analysis...")
    
    // Estimate processing time based on video length
    let estimatedTime = "5-10 minutes"
    if (videoLength === "10-20") {
      estimatedTime = "10-20 minutes"
    } else if (videoLength === "20+") {
      estimatedTime = "20-40 minutes"
    }
    
    if (youtubeUrl) {
      setProcessingStage("🔄 Downloading YouTube video...")
      setMessage(`⏱️ YouTube download in progress. Estimated processing time: ${estimatedTime}`)
    } else {
      setProcessingStage("Uploading practice video...")
      setMessage(`⏱️ Video upload complete. Estimated processing time: ${estimatedTime}`)
    }

    try {
      const formData = new FormData()
      if (videoFile) {
        formData.append("video", videoFile)
      }
      if (youtubeUrl) {
        formData.append("youtube_url", youtubeUrl)
      }
      
      // formData.append("mode", outputMode)
      formData.append("practice_type", practiceType)
      formData.append("video_length", videoLength)
      formData.append("desired_clip_length", desiredClipLength)
      formData.append("movement_threshold", movementThreshold)
      formData.append("min_movement_duration", minMovementDuration)
      formData.append("padding_before", paddingBefore)
      formData.append("padding_after", paddingAfter)
      formData.append("output_mode", outputMode)

      setProcessingStage("🔍 Detecting movement in practice video...")
      setMessage(`🔍 Analyzing video for movement patterns... This may take ${estimatedTime} for longer videos.`)

      const res = await fetch("http://127.0.0.1:8000/practice-mode", {
        method: "POST",
        body: formData,
      })

      setProcessingStage("✂️ Extracting practice clips...")
      setMessage("✂️ Extracting detected movement segments...")

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.message || `HTTP error! Status: ${res.status}`)
      }

      const data = await res.json()
      console.log("Practice mode response:", data)

      if (data.status === "success") {
        setResults(data)
        setMessage(`✅ Practice analysis complete! Found ${data.total_segments} movement segments. Efficiency: ${data.efficiency_percentage.toFixed(1)}%`)
        setProcessingStage("")
      } else {
        throw new Error(data.message || "Practice analysis failed")
      }
    } catch (error) {
      console.error(error)
      
      // Handle specific timeout errors
      if (error instanceof Error && error.message && error.message.includes("timeout")) {
        setMessage(`⏰ Processing timed out. For videos longer than 25 minutes, consider:
        • Using shorter video segments
        • Splitting the video into parts
        • Using the timestamp feature to select specific sections`)
      } else {
        setMessage(`❌ Error: ${error instanceof Error ? error.message : 'Practice analysis failed'}`)
      }
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
              <h1 className="text-2xl font-bold text-powerplay-primary">Practice Mode</h1>
              <p className="text-powerplay-secondary text-sm">AI-Powered Movement Detection & Clip Extraction</p>
            </div>
          </div>
          
          {/* Regular Mode Link */}
          <Link 
            href="/upload" 
            className="bg-powerplay-button hover:bg-powerplay-button-hover text-powerplay-primary px-4 py-2 rounded-lg font-medium transition-colors duration-200 flex items-center space-x-2"
          >
            <span>🎯</span>
            <span>Switch to Regular Mode</span>
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-6xl mx-auto">
          {/* Page Title */}
          <div className="text-center mb-8">
            <h1 className="text-4xl font-bold text-powerplay-primary mb-4">
              Practice Mode Analysis
            </h1>
            <p className="text-xl text-powerplay-secondary">
              Automatically detect movement and extract practice clips with smart padding
            </p>
          </div>

          {/* Practice Mode Form */}
          <Card className="bg-powerplay-card border-powerplay backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-powerplay-primary text-2xl flex items-center space-x-2">
                <Scissors className="w-6 h-6" />
                <span>Practice Session Configuration</span>
              </CardTitle>
              <CardDescription className="text-powerplay-secondary">
                Configure movement detection parameters for optimal practice clip extraction
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              
              {/* Practice Type Selection */}
              <div className="space-y-3">
                <label className="block text-powerplay-primary font-medium">Practice Type</label>
                <div className="grid grid-cols-2 gap-4">
                  <Button
                    type="button"
                    variant={practiceType === "batting" ? "default" : "outline"}
                    onClick={() => setPracticeType("batting")}
                    className={`${
                      practiceType === "batting" 
                        ? "bg-powerplay-button text-powerplay-primary" 
                        : "border-powerplay text-powerplay-primary bg-powerplay-card hover:bg-powerplay-hover"
                    }`}
                  >
                    🏏 Batting Practice
                  </Button>

                  <Button
                    type="button"
                    variant={practiceType === "bowling" ? "default" : "outline"}
                    onClick={() => setPracticeType("bowling")}
                    className={`${
                      practiceType === "bowling" 
                        ? "bg-powerplay-button text-powerplay-primary" 
                        : "border-powerplay text-powerplay-primary bg-powerplay-card hover:bg-powerplay-card"
                    }`}
                  >
                    🎯 Bowling Practice
                  </Button>
                </div>
              </div>
              
              {/* Video Input Section */}
              <div className="space-y-4">
                <label className="block text-powerplay-primary font-medium flex items-center space-x-2">
                  <Upload className="w-5 h-5" />
                  <span>Upload Practice Video:</span>
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

              {/* Advanced Settings */}
              <div className="space-y-4">
                <label className="block text-powerplay-primary font-medium flex items-center space-x-2">
                  <Settings className="w-5 h-5" />
                  <span>Advanced Movement Detection Settings</span>
                </label>
                
                {/* Long Video Tips */}
                {videoLength === "20+" && (
                  <div className="mb-6 p-4 bg-amber-500/20 border border-amber-500/30 rounded-lg">
                    <h4 className="text-amber-300 font-medium mb-2">💡 Tips for Long Videos (20+ minutes)</h4>
                    <ul className="text-amber-200 text-sm space-y-1">
                      <li>• Use <strong>Movement Sensitivity: 0.01-0.02</strong> for better detection</li>
                      <li>• Set <strong>Min Action Duration: 0.2-0.3s</strong> to avoid missing quick actions</li>
                      <li>• Reduce <strong>Time After Action: 2.0-3.0s</strong> to keep clips manageable</li>
                      <li>• Expected processing time: <strong>20-40 minutes</strong></li>
                      <li>• Consider splitting very long videos into segments for faster processing</li>
                    </ul>
                  </div>
                )}
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Movement Threshold */}
                  <div>
                    <label className="block text-powerplay-secondary mb-1 text-sm">
                      Movement Sensitivity
                    </label>
                    <select
                      value={movementThreshold}
                      onChange={(e) => setMovementThreshold(e.target.value)}
                      className="w-full p-2 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary focus:border-amber-400 focus:outline-none transition-colors"
                    >
                      <option value="0.01">Very Sensitive (0.01)</option>
                      <option value="0.02">Sensitive (0.02) - Recommended</option>
                      <option value="0.05">Moderate (0.05)</option>
                      <option value="0.1">Less Sensitive (0.1)</option>
                    </select>
                    <p className="text-xs text-powerplay-secondary mt-1">
                      Lower = detects smaller movements
                    </p>
                  </div>
                  
                  {/* Min Movement Duration */}
                  <div>
                    <label className="block text-powerplay-secondary mb-1 text-sm">
                      Minimum Action Duration
                    </label>
                    <select
                      value={minMovementDuration}
                      onChange={(e) => setMinMovementDuration(e.target.value)}
                      className="w-full p-2 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary focus:border-amber-400 focus:outline-none transition-colors"
                    >
                      <option value="0.3">0.3 seconds</option>
                      <option value="0.5">0.5 seconds - Recommended</option>
                      <option value="1.0">1.0 second</option>
                      <option value="2.0">2.0 seconds</option>
                    </select>
                    <p className="text-xs text-powerplay-secondary mt-1">
                      Minimum time for valid action
                    </p>
                  </div>
                  
                  {/* Padding Before */}
                  <div>
                    <label className="block text-powerplay-secondary mb-1 text-sm">
                      Time Before Action
                    </label>
                    <select
                      value={paddingBefore}
                      onChange={(e) => setPaddingBefore(e.target.value)}
                      className="w-full p-2 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary focus:border-amber-400 focus:outline-none transition-colors"
                    >
                      <option value="0.5">0.5 seconds</option>
                      <option value="1.0">1.0 second - Recommended</option>
                      <option value="1.5">1.5 seconds</option>
                      <option value="2.0">2.0 seconds</option>
                    </select>
                    <p className="text-xs text-powerplay-secondary mt-1">
                      Captures setup/preparation
                    </p>
                  </div>
                  
                  {/* Padding After */}
                  <div>
                    <label className="block text-powerplay-secondary mb-1 text-sm">
                      Time After Action
                    </label>
                    <select
                      value={paddingAfter}
                      onChange={(e) => setPaddingAfter(e.target.value)}
                      className="w-full p-2 rounded-lg bg-powerplay-card border border-powerplay text-powerplay-primary focus:border-amber-400 focus:outline-none transition-colors"
                    >
                      <option value="2.0">2.0 seconds</option>
                      <option value="3.0">3.0 seconds</option>
                      <option value="4.0">4.0 seconds - Recommended</option>
                      <option value="6.0">6.0 seconds</option>
                    </select>
                    <p className="text-xs text-powerplay-secondary mt-1">
                      Captures follow-through
                    </p>
                  </div>
                </div>
              </div>

              {/* Output Mode */}
              <div className="space-y-3">
                <label className="block text-powerplay-primary font-medium">Output Format</label>
                <div className="grid grid-cols-2 gap-4">
                  <Button
                    type="button"
                    variant={outputMode === "clips" ? "default" : "outline"}
                    onClick={() => setOutputMode("clips")}
                    className={`${
                      outputMode === "clips" 
                        ? "bg-powerplay-button text-powerplay-primary" 
                        : "border-powerplay text-powerplay-primary bg-powerplay-card hover:bg-powerplay-card"
                    }`}
                  >
                    <Scissors className="w-4 h-4 mr-2" />
                    Individual Clips
                  </Button>
                  <Button
                    type="button"
                    variant={outputMode === "highlights" ? "default" : "outline"}
                    onClick={() => setOutputMode("highlights")}
                    className={`${
                      outputMode === "highlights" 
                        ? "bg-powerplay-button text-powerplay-primary" 
                        : "border-powerplay text-powerplay-primary bg-powerplay-card hover:bg-powerplay-card"
                    }`}
                  >
                    <Play className="w-4 h-4 mr-2" />
                    Compiled Highlights
                  </Button>
                </div>
                <p className="text-sm text-powerplay-secondary">
                  {outputMode === "clips" 
                    ? "Creates separate MP4 files for each action" 
                    : "Combines all actions into a single highlight video"
                  }
                </p>
              </div>
              
              {/* Action Buttons */}
              <div className="flex justify-between pt-4">
                {results && (
                  <Button 
                    onClick={resetForm} 
                    variant="outline" 
                    className="border-powerplay text-powerplay-primary hover:bg-powerplay-card"
                  >
                    Start New Analysis
                  </Button>
                )}
                <Button 
                  onClick={startPracticeAnalysis} 
                  disabled={loading || (!videoFile && !youtubeUrl)} 
                  className="bg-powerplay-button hover:bg-powerplay-button-hover disabled:opacity-50 disabled:cursor-not-allowed flex-1 ml-2"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                      Analyzing Practice Session...
                    </>
                  ) : (
                    <>
                      <Target className="w-5 h-5 mr-2" />
                      Start Practice Analysis
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
                      <p>⏱️ YouTube downloads can take 5-15 minutes depending on video length.</p>
                      <p>💡 Practice mode will automatically detect movement and extract relevant clips!</p>
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

              {/* Results Display */}
              {results && (
                <div className="mt-6 space-y-4">
                  <h3 className="text-xl font-semibold text-powerplay-primary">Practice Analysis Results</h3>
                  
                  {/* Statistics */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="p-4 bg-powerplay-card border border-powerplay rounded-lg">
                      <h4 className="text-powerplay-primary font-medium mb-2">Segments Found</h4>
                      <p className="text-2xl font-bold text-powerplay-secondary">{results.total_segments}</p>
                    </div>
                    <div className="p-4 bg-powerplay-card border border-powerplay rounded-lg">
                      <h4 className="text-powerplay-primary font-medium mb-2">Efficiency</h4>
                      <p className="text-2xl font-bold text-powerplay-secondary">{results.efficiency_percentage.toFixed(1)}%</p>
                    </div>
                    <div className="p-4 bg-powerplay-card border border-powerplay rounded-lg">
                      <h4 className="text-powerplay-primary font-medium mb-2">Duration Saved</h4>
                      <p className="text-2xl font-bold text-powerplay-secondary">
                        {((results.original_duration - results.total_highlight_duration) / 60).toFixed(1)} min
                      </p>
                    </div>
                  </div>
                  
                  {/* Segments Info */}
                  <div className="p-4 bg-powerplay-card border border-powerplay rounded-lg">
                    <h4 className="text-powerplay-primary font-medium mb-2">Detected Movement Segments:</h4>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      {results.segments.map((segment: [number, number], index: number) => (
                        <div key={index} className="text-sm text-powerplay-secondary">
                          {segment[0].toFixed(1)}s - {segment[1].toFixed(1)}s
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Output Files */}
                  <div className="p-4 bg-powerplay-card border border-powerplay rounded-lg">
                    <h4 className="text-powerplay-primary font-medium mb-2">Generated Files:</h4>
                    <div className="space-y-2">
                      {results.output_urls.map((url: string, index: number) => (
                        <div key={index} className="flex items-center justify-between p-2 bg-powerplay-gradient-subtle rounded">
                          <span className="text-powerplay-secondary">{url.split('/').pop()}</span>
                          <div className="flex space-x-2">
                            <Button 
                              onClick={() => window.open(`http://127.0.0.1:8000${url}`, '_blank')}
                              size="sm"
                              className="bg-powerplay-accent hover:bg-powerplay-accent-hover"
                            >
                              <Eye className="w-4 h-4 mr-1" />
                              View
                            </Button>
                            <Button 
                              onClick={() => {
                                const link = document.createElement('a')
                                link.href = `http://127.0.0.1:8000${url}`
                                link.download = url.split('/').pop() || 'practice_clip.mp4'
                                link.click()
                              }}
                              size="sm"
                              variant="outline"
                              className="border-powerplay text-powerplay-primary hover:bg-powerplay-card"
                            >
                              <Download className="w-4 h-4 mr-1" />
                              Download
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
} 