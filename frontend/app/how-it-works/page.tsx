"use client"

import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Upload, Youtube, Target, Scissors, Download } from "lucide-react"

export default function HowItWorksPage() {
  return (
    <div className="min-h-screen bg-powerplay-gradient">
      {/* Top bar spacer so it feels consistent with home */}
      <header className="border-b border-powerplay bg-black/20 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 bg-powerplay-button rounded-lg flex items-center justify-center">
              <Upload className="w-4 h-4 text-white" />
            </div>
            <div>
              <span className="text-lg font-semibold text-powerplay-primary">PowerPlay</span>
              <p className="text-xs text-powerplay-secondary">AI-Powered Video Editing</p>
            </div>
          </div>
          <Button asChild variant="ghost" className="text-powerplay-primary hover:bg-white/10 text-sm md:text-base">
            <Link href="/">Back to home</Link>
          </Button>
        </div>
      </header>

      <main className="container mx-auto px-4 py-12 md:py-16">
        {/* Hero / Intro */}
        <section className="max-w-3xl mx-auto text-center mb-12 md:mb-16">
          <h1 className="font-heading text-3xl md:text-4xl lg:text-5xl tracking-[0.2em] md:tracking-[0.25em] text-powerplay-primary mb-4">
            HOW IT WORKS
          </h1>
          <p className="text-powerplay-secondary text-sm md:text-base leading-relaxed">
            This page walks you through the exact steps to turn a full match into clean, player-focused highlights.
            You can add screenshots or short clips next to each step as your product evolves.
          </p>
        </section>

        {/* Step-by-step cards */}
        <section className="grid md:grid-cols-2 gap-6 lg:gap-8 mb-12 md:mb-16">
          {/* Step 1 */}
          <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-powerplay-primary">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-powerplay-button text-xs font-semibold">
                  1
                </span>
                Enter player details
              </CardTitle>
              <CardDescription className="text-powerplay-secondary">
                Tell PowerPlay who to follow.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-powerplay-secondary space-y-2">
              <p>On the upload page:</p>
              <ul className="list-disc list-inside space-y-1">
                <li>Type the player&apos;s <span className="font-medium text-powerplay-primary">name</span>.</li>
                <li>Enter their <span className="font-medium text-powerplay-primary">jersey number</span> exactly as it appears on screen.</li>
                <li>Select the <span className="font-medium text-powerplay-primary">action type</span> (Batting or Bowling).</li>
              </ul>
            </CardContent>
          </Card>

          {/* Step 2 */}
          <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-powerplay-primary">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-powerplay-button text-xs font-semibold">
                  2
                </span>
                Add your match footage
              </CardTitle>
              <CardDescription className="text-powerplay-secondary">
                Use either a raw file or a YouTube link.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-powerplay-secondary space-y-2">
              <ul className="list-disc list-inside space-y-1">
                <li>
                  <span className="font-medium text-powerplay-primary">Upload a video file</span> from your device, or
                </li>
                <li>
                  Paste a <span className="font-medium text-powerplay-primary">YouTube URL</span> of your streamed match.
                </li>
                <li>
                  (Optional) Use the <span className="font-medium text-powerplay-primary">Start</span> and{" "}
                  <span className="font-medium text-powerplay-primary">End</span> time fields to focus on a specific
                  innings or segment.
                </li>
              </ul>
            </CardContent>
          </Card>

          {/* Step 3 */}
          <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-powerplay-primary">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-powerplay-button text-xs font-semibold">
                  3
                </span>
                Let the AI track your player
              </CardTitle>
              <CardDescription className="text-powerplay-secondary">
                PowerPlay finds every appearance of your jersey.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-powerplay-secondary space-y-2">
              <p>
                Click <span className="font-medium text-powerplay-primary">Generate Highlights</span>. PowerPlay will:
              </p>
              <ul className="list-disc list-inside space-y-1">
                <li>Scan the match and detect your jersey number.</li>
                <li>Use tracking to follow that player through the innings.</li>
                <li>Mark potential highlight segments where they are in action.</li>
              </ul>
            </CardContent>
          </Card>

          {/* Step 4 */}
          <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-powerplay-primary">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-powerplay-button text-xs font-semibold">
                  4
                </span>
                Review, download, and share
              </CardTitle>
              <CardDescription className="text-powerplay-secondary">
                Your personal highlight reel, ready in one file.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-powerplay-secondary space-y-2">
              <ul className="list-disc list-inside space-y-1">
                <li>Watch the generated highlight reel directly in the browser.</li>
                <li>
                  Click <span className="font-medium text-powerplay-primary">Download Highlights</span> to save it to
                  your device.
                </li>
                <li>Share it on social media, send to coaches, or keep it in your personal archive.</li>
              </ul>
              <p className="text-xs text-powerplay-secondary/80 mt-2">
                Later, you can drop in example screenshots or GIFs next to each step showing exactly what the user
                should click.
              </p>
            </CardContent>
          </Card>
        </section>

                {/* HOW PRACTICE MODE WORKS */}
                <section className="mb-12 md:mb-16">
          <div className="text-center mb-8">
            <h2 className="text-2xl md:text-3xl font-semibold text-powerplay-primary tracking-[0.15em] mb-3 uppercase">
              How Practice Mode Works
            </h2>
            <p className="text-powerplay-secondary max-w-2xl mx-auto text-sm md:text-base">
              Practice sessions can run for an hour, but real action is only a few minutes. Practice Mode removes
              the grey time and keeps only the balls in play.
            </p>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            {/* Step 1 */}
            <div className="bg-powerplay-gradient-card border-powerplay rounded-2xl p-5 md:p-6">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-7 h-7 rounded-full bg-powerplay-button text-xs flex items-center justify-center text-powerplay-primary">
                  1
                </span>
                <h3 className="text-powerplay-primary font-semibold text-base md:text-lg">
                  Upload your practice session
                </h3>
              </div>
              <p className="text-powerplay-secondary text-sm md:text-[15px] leading-relaxed">
                Drag in a long practice recording or paste a YouTube link of your net session. 
                PowerPlay handles full-length videos without you needing to trim them manually.
              </p>
            </div>

            {/* Step 2 */}
            <div className="bg-powerplay-gradient-card border-powerplay rounded-2xl p-5 md:p-6">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-7 h-7 rounded-full bg-powerplay-button text-xs flex items-center justify-center text-powerplay-primary">
                  2
                </span>
                <h3 className="text-powerplay-primary font-semibold text-base md:text-lg">
                  Tune movement settings
                </h3>
              </div>
              <p className="text-powerplay-secondary text-sm md:text-[15px] leading-relaxed">
                Choose <span className="font-medium text-powerplay-primary">Batting</span> or{" "}
                <span className="font-medium text-powerplay-primary">Bowling</span>, then adjust movement sensitivity,
                minimum action duration, and padding before/after each ball to match how intense your session is.
              </p>
            </div>

            {/* Step 3 */}
            <div className="bg-powerplay-gradient-card border-powerplay rounded-2xl p-5 md:p-6">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-7 h-7 rounded-full bg-powerplay-button text-xs flex items-center justify-center text-powerplay-primary">
                  3
                </span>
                <h3 className="text-powerplay-primary font-semibold text-base md:text-lg">
                  Get only the balls that matter
                </h3>
              </div>
              <p className="text-powerplay-secondary text-sm md:text-[15px] leading-relaxed">
                PowerPlay automatically detects motion, cuts out the dead time between balls, and exports either
                individual clips or one compiled highlight video of your full practice.
              </p>
            </div>
          </div>
        </section>

        {/* Mode chooser CTA: Regular Highlights vs Practice Mode */}
        <section className="mb-12 md:mb-16">
          <div className="max-w-4xl mx-auto grid gap-6 md:grid-cols-2">
            {/* Regular highlight flow */}
            <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl flex flex-col">
              <CardHeader>
                <CardTitle className="text-powerplay-primary flex items-center gap-2 text-lg md:text-xl">
                  <Target className="w-5 h-5" />
                  <span>Match Highlights</span>
                </CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  For full matches or innings where you want a clean, player-focused highlight reel.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-between space-y-3 text-sm text-powerplay-secondary">
                <ul className="list-disc list-inside space-y-1">
                  <li>Enter player name and jersey number.</li>
                  <li>Upload a match video or paste a YouTube link.</li>
                  <li>Optionally set start / end timestamps.</li>
                  <li>PowerPlay tracks that player and cuts a single highlight video.</li>
                </ul>
                <Button
                  asChild
                  size="sm"
                  className="mt-4 bg-powerplay-button hover:bg-powerplay-button-hover text-xs md:text-sm px-6"
                >
                  <Link href="/upload">
                    Go to Highlight Mode
                  </Link>
                </Button>
              </CardContent>
            </Card>

            {/* Practice mode flow */}
            <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl flex flex-col">
              <CardHeader>
                <CardTitle className="text-powerplay-primary flex items-center gap-2 text-lg md:text-xl">
                  <Scissors className="w-5 h-5" />
                  <span>Practice Mode</span>
                </CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  For long practice sessions where you only care about the balls and drills, not the waiting.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-between space-y-3 text-sm text-powerplay-secondary">
                <ul className="list-disc list-inside space-y-1">
                  <li>Upload a full practice recording or paste a YouTube practice stream.</li>
                  <li>Select batting or bowling and tune movement sensitivity.</li>
                  <li>Set padding before/after each ball to keep context.</li>
                  <li>PowerPlay removes grey time and keeps only live actions.</li>
                </ul>
                <Button
                  asChild
                  size="sm"
                  className="mt-4 bg-powerplay-button hover:bg-powerplay-button-hover text-xs md:text-sm px-6"
                >
                  <Link href="/practice-mode">
                    Go to Practice Mode
                  </Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        </section>

        {/* Placeholder section for future screenshots */}
        <section className="max-w-4xl mx-auto mb-16">
          <div className="bg-powerplay-gradient-card border-powerplay rounded-2xl p-6 md:p-8 text-center">
            <h2 className="text-xl md:text-2xl font-semibold text-powerplay-primary mb-3">
              Coming Soon
            </h2>
            <p className="text-sm md:text-base text-powerplay-secondary max-w-2xl mx-auto">
              ...
            </p>
          </div>
        </section>
      </main>
    </div>
  )
}