
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Play, Upload, Target, Zap, BarChart3, Users, Share2, Trophy, Check } from "lucide-react"

export default function HomePage() {
  return (
    <div className="min-h-screen bg-powerplay-gradient">
      {/* Header */}
      <header className="border-b border-powerplay bg-black/20 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <div className="w-12 h-12 bg-powerplay-button rounded-xl flex items-center justify-center">
              <Play className="w-6 h-6 text-white fill-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-powerplay-primary">PowerPlay</h1>
              <p className="text-powerplay-secondary text-sm">AI-Powered Video Editing</p>
            </div>
          </div>
          
          <nav className="hidden md:flex items-center space-x-8">
            <Link
              href="#features"
              className="text-powerplay-secondary hover:text-powerplay-primary transition-colors text-sm md:text-base font-medium tracking-wide"
            >
              Features
            </Link>
            <Link
              href="/how-it-works"
              className="text-powerplay-secondary hover:text-powerplay-primary transition-colors text-sm md:text-base font-medium tracking-wide"
            >
              How it Works
            </Link>
            <Link
              href="#pricing"
              className="text-powerplay-secondary hover:text-powerplay-primary transition-colors text-sm md:text-base font-medium tracking-wide"
            >
              Pricing
            </Link>
            <Link
              href="#contact"
              className="text-powerplay-secondary hover:text-powerplay-primary transition-colors text-sm md:text-base font-medium tracking-wide"
            >
              Contact
            </Link>
          </nav>
            
          <div className="flex items-center space-x-3">
            {/*
            <Link 
              href="/practice-mode" 
              className="bg-powerplay-accent hover:bg-powerplay-accent-hover text-powerplay-primary px-4 py-2 rounded-lg font-medium transition-colors duration-200 flex items-center space-x-2 mr-2"
            >
              <span>🏏</span>
              <span className="hidden sm:inline">Practice Mode</span>
            </Link>
              Header */}

            <Button asChild variant="ghost" className="text-powerplay-primary hover:bg-white/10">
              <Link href="/signup">Sign Up</Link>
            </Button>
            <Button
              asChild
              className="bg-powerplay-button hover:bg-powerplay-button-hover"
            >
              <Link href="/upload">Get Started</Link>
            </Button>
          </div>
        </div>
      </header>

        {/* Hero Section */}
      <section className="relative flex items-center justify-center py-20 md:py-24 lg:py-28">
        <div className="container mx-auto text-center space-y-6 md:space-y-7">
          {/* Small pill moved slightly up & closer */}
          <div className="inline-flex items-center justify-center px-4 py-1 rounded-full bg-white/5 border border-white/10 text-xs md:text-sm tracking-[0.18em] uppercase text-powerplay-secondary mb-1">
            AI-Powered Video Intelligence
          </div>

          {/* Main heading */}
          <h1 className="font-heading text-[2.8rem] md:text-[3.6rem] lg:text-[4.1rem] font-semibold tracking-[0.25em] md:tracking-[0.3em] text-powerplay-primary leading-tight">
            <span className="block">SAVE TIME</span>
            <span className="block mt-3 bg-gradient-to-r from-rose-500 via-fuchsia-500 to-purple-500 bg-clip-text text-transparent">
              RESTORE QUALITY
            </span>
          </h1>

          {/* Subcopy */}
          <p className="text-sm md:text-base text-powerplay-secondary max-w-xl mx-auto">
            Hours of footage. Highlights in minutes.
          </p>

          {/* CTA buttons */}
          <div className="mt-4 flex flex-col sm:flex-row gap-3 justify-center">
            <Button
              asChild
              size="lg"
              className="bg-powerplay-button hover:bg-powerplay-button-hover text-sm md:text-base px-8"
            >
              <Link href="/upload">
                <Upload className="w-5 h-5 mr-2" />
                Upload Your Game
              </Link>
            </Button>
            <Button
              variant="outline"
              size="lg"
              className="border-powerplay text-powerplay-primary hover:bg-white/5 text-sm md:text-base px-8 bg-transparent"
            >
              <Play className="w-5 h-5 mr-2" />
              Watch Demo
            </Button>
          </div>
        </div>
      </section>

        {/* Features Section */}
      <section id="features" className="pt-14 pb-20 px-4 bg-black/20">
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="font-heading text-4xl font-bold text-powerplay-primary mb-4">
              Intelligent Player Tracking
            </h2>
            <p className="text-powerplay-secondary text-lg max-w-2xl mx-auto">
              Our AI goes beyond simple moment detection to understand player context and capture their complete game
              story.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
            {/* your existing feature cards stay here unchanged */}
            <Card className="bg-powerplay-gradient-card">
              <CardHeader>
                <Target className="w-10 h-10 text-purple-400 mb-2" />
                <CardTitle className="text-powerplay-primary">Smart Player Detection</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  AI automatically identifies and tracks individual players throughout the entire match
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="bg-powerplay-gradient-card">
              <CardHeader>
                <Zap className="w-10 h-10 text-fuchsia-600 mb-2" />
                <CardTitle className="text-powerplay-primary">Context-Aware Highlights</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  Captures not just scoring moments but build-up plays, defensive actions, and team interactions
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="bg-powerplay-gradient-card">
              <CardHeader>
                <BarChart3 className="w-10 h-10 text-purple-500 mb-2" />
                <CardTitle className="text-powerplay-primary">Performance Analytics</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  {/* you can fill this later */}
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="bg-powerplay-gradient-card">
              <CardHeader>
                <Users className="w-10 h-10 text-fuchsia-500 mb-2" />
                <CardTitle className="text-powerplay-primary">Cricket Specialized</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  Specialized for cricket analysis and highlight generation
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="bg-powerplay-gradient-card">
              <CardHeader>
                <Share2 className="w-10 h-10 text-purple-600 mb-2" />
                <CardTitle className="text-powerplay-primary">Instant Sharing</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  Export highlights in multiple formats optimized for social media and recruitment
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="bg-powerplay-gradient-card">
              <CardHeader>
                <Trophy className="w-10 h-10 text-fuchsia-400 mb-2" />
                <CardTitle className="text-powerplay-primary">Professional Quality</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  Broadcast-quality output suitable for recruitment packages and professional analysis
                </CardDescription>
              </CardHeader>
            </Card>
          </div>
        </div>
      </section>

          {/* Pricing Section */}
          <section
          id="pricing"
          className="py-24 lg:py-28 px-4 bg-gradient-to-b from-black/30 via-black/40 to-black/50"
        >
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="font-heading text-4xl font-bold text-powerplay-primary mb-4">
              Simple, flexible pricing
            </h2>
            <p className="text-powerplay-secondary text-lg max-w-2xl mx-auto">
              Choose the plan that fits your role
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {/* Solo */}
            <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl px-8 py-8 min-h-[320px] flex flex-col justify-between">
              <CardHeader>
                <CardTitle className="text-powerplay-primary text-2xl">Solo</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  For individual players who want quick, personal highlight reels.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-between">
                <div className="mb-6">
                  <div className="flex items-baseline gap-2 mb-4">
                    <span className="text-3xl font-bold text-powerplay-primary">$11</span>
                    <span className="text-powerplay-secondary">/ month</span>
                  </div>
                  <p className="text-sm text-powerplay-secondary mb-4">1 user • basic access</p>
                  <ul className="space-y-2 text-sm text-powerplay-secondary">
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Limited highlight reel generation each month
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Access to practice mode
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Save videos locally to your device
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Single user account
                    </li>
                  </ul>
                </div>
                <Button
                  asChild
                  className="w-full bg-powerplay-button hover:bg-powerplay-button-hover"
                >
                  <Link href="/signup">Get Solo</Link>
                </Button>
              </CardContent>
            </Card>

            {/* Pro */}
            <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl px-8 py-8 min-h-[340px] flex flex-col justify-between shadow-[0_0_40px_rgba(168,85,247,0.35)]">
              <CardHeader>
                <div className="inline-flex items-center px-3 py-1 mb-3 rounded-full bg-fuchsia-500/20 border border-fuchsia-500/60 text-xs font-medium text-fuchsia-200">
                  Most popular
                </div>
                <CardTitle className="text-powerplay-primary text-2xl">Pro</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  For serious players and creators who want full power and storage.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-between">
                <div className="mb-6">
                  <div className="flex items-baseline gap-2 mb-4">
                    <span className="text-3xl font-bold text-powerplay-primary">$16</span>
                    <span className="text-powerplay-secondary">/ month</span>
                  </div>
                  <p className="text-sm text-powerplay-secondary mb-4">1 user • full access</p>
                  <ul className="space-y-2 text-sm text-powerplay-secondary">
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Unlimited highlight reel generation
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Unlimited practice mode usage
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Store all videos on PowerPlay
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Single user account
                    </li>
                  </ul>
                </div>
                <Button
                  asChild
                  className="w-full bg-powerplay-button hover:bg-powerplay-button-hover"
                >
                  <Link href="/signup">Get Pro</Link>
                </Button>
              </CardContent>
            </Card>

            {/* Group */}
            <Card className="bg-powerplay-gradient-card border-powerplay rounded-2xl px-8 py-8 min-h-[320px] flex flex-col justify-between">
              <CardHeader>
                <CardTitle className="text-powerplay-primary text-2xl">Group</CardTitle>
                <CardDescription className="text-powerplay-secondary">
                  Built for clubs and teams who want shared access to every match.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-between">
                <div className="mb-6">
                  <div className="flex items-baseline gap-2 mb-2">
                    <span className="text-3xl font-bold text-powerplay-primary">$30</span>
                    <span className="text-powerplay-secondary">/ month</span>
                  </div>
                  <p className="text-sm text-powerplay-secondary mb-2">
                    includes 2 users &bull; up to 11 total
                  </p>
                  <p className="text-sm text-powerplay-secondary mb-4">
                    + $10 / month for each additional user
                  </p>
                  <ul className="space-y-2 text-sm text-powerplay-secondary">
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Unlimited highlight reels for the whole squad
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Unlimited practice mode for every user
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Centralized storage on PowerPlay
                    </li>
                    <li className="flex items-center">
                      <Check className="w-4 h-4 mr-2 text-fuchsia-400" />
                      Up to 11 users per team workspace
                    </li>
                  </ul>
                </div>
                <Button
                  asChild
                  className="w-full bg-powerplay-button hover:bg-powerplay-button-hover"
                >
                  <Link href="/signup">Get Group</Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

            {/* Use Cases Section */}
            <section className="py-24 lg:py-28 px-4 bg-gradient-to-b from-black/50 via-black/60 to-black/70">
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-powerplay-primary mb-4">Built for Every Level</h2>
            <p className="text-powerplay-secondary text-lg max-w-2xl mx-auto">
              From amateur leagues to professional organizations, PowerPlay adapts to your needs.
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-12 items-center">
            <div className="space-y-8">
              <div className="flex items-start space-x-4">
                <div className="w-12 h-12 bg-pink-500/20 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Users className="w-6 h-6 text-pink-700" />
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-powerplay-primary mb-2">Player Development</h3>
                  <p className="text-powerplay-secondary">
                    Coaches analyze individual performance patterns across multiple games to identify strengths and
                    areas for improvement.
                  </p>
                </div>
              </div>
              
              <div className="flex items-start space-x-4">
                <div className="w-12 h-12 bg-pink-600/20 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Trophy className="w-6 h-6 text-pink-600"/>
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-powerplay-primary mb-2">Recruitment Packages</h3>
                  <p className="text-powerplay-secondary">
                    Athletes create professional highlight reels for scouts and scholarship opportunities with
                    comprehensive skill showcases.
                  </p>
                </div>
              </div>
              
              <div className="flex items-start space-x-4">
                <div className="w-12 h-12 bg-pink-700/20 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Share2 className="w-6 h-6 text-pink-500" />
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-powerplay-primary mb-2">Content Creation</h3>
                  <p className="text-powerplay-secondary">
                    Sports content creators produce engaging player-specific content for social media and fan
                    engagement.
                  </p>
                </div>
              </div>
            </div>

            <div className="relative">
              <div className="aspect-video bg-gradient-to-br from-blue-300/20 to-red-400/20 rounded-xl border border-powerplay flex items-center justify-center">
                <div className="text-center">
                  <Play className="w-16 h-16 text-powerplay-secondary mx-auto mb-4" />
                  <p className="text-powerplay-secondary">Demo Video Coming Soon</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

        {/* CTA Section */}
            <section className="py-18 md:py-20 px-4 bg-powerplay-cta">
        <div className="container mx-auto text-center space-y-4 md:space-y-5">
          <h2 className="text-3xl md:text-4xl font-semibold text-powerplay-primary">
            Ready to Transform Your Game Footage?
          </h2>
          <p className="text-base md:text-xl text-powerplay-secondary max-w-2xl mx-auto leading-relaxed">
            Join teams and athletes already using PowerPlay to create professional highlight reels
            in minutes, not hours.
          </p>
          <Button
            asChild
            size="lg"
            className="bg-powerplay-button hover:bg-powerplay-button-hover text-base md:text-lg px-8"
          >
            <Link href="/upload">
              <Upload className="w-5 h-5 mr-2" />
              Start Creating Highlights
            </Link>
          </Button>
        </div>
      </section>

      {/* Contact Section */}
      <section
      id="contact"
      className="py-24 lg:py-28 px-4 bg-gradient-to-b bg-black/20"
    >
        <div className="container mx-auto grid md:grid-cols-2 gap-10 items-start">
          <div>
            <h2 className="font-heading text-4xl font-bold text-powerplay-primary mb-4">
              Talk to the PowerPlay team
            </h2>
            <p className="text-powerplay-secondary text-lg mb-6 max-w-xl">
              Have questions about pricing, team onboarding, or even suggestions for us? Drop us a message and we&apos;ll get
              back within 1–2 business days.
            </p>
            <div className="space-y-2 text-powerplay-secondary text-sm">
              <p>
                📧 Email: <span className="text-powerplay-primary">support@powerplay.app</span>
              </p>
              <p>🏏 Perfect for clubs, academies, creators, and coaches who want to level up their video pipeline.</p>
            </div>
          </div>

          <div>
            <div className="bg-powerplay-gradient-card border-powerplay rounded-xl p-6">
              <form className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-powerplay-primary mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    className="w-full rounded-lg bg-white/10 text-white border border-white/20 px-3 py-2 placeholder:text-white/40 focus:outline-none focus:border-powerplay-button transition-colors"
                    placeholder="Your name"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-powerplay-primary mb-1">
                    Country / State
                  </label>
                  <input
                    type="State"
                    className="w-full rounded-lg bg-white/10 text-white border border-white/20 px-3 py-2 placeholder:text-white/40 focus:outline-none focus:border-powerplay-button transition-colors"
                    placeholder="Texas"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-powerplay-primary mb-1">
                    Email
                  </label>
                  <input
                    type="email"
                    className="w-full rounded-lg bg-white/10 text-white border border-white/20 px-3 py-2 placeholder:text-white/40 focus:outline-none focus:border-powerplay-button transition-colors"
                    placeholder="you@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-powerplay-primary mb-1">
                    Message
                  </label>
                  <textarea
                    className="w-full rounded-lg bg-white/10 text-white border border-white/20 px-3 py-2 h-28 resize-none placeholder:text-white/40 focus:outline-none focus:border-powerplay-button transition-colors"
                    placeholder="Tell us about your team, use case, or question..."
                  />
                </div>
                <Button
                  type="submit"
                  className="w-full bg-powerplay-button hover:bg-powerplay-button-hover"
                >
                  Send message
                </Button>
                <p className="text-xs text-powerplay-secondary mt-1">
                </p>
              </form>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-powerplay bg-black/20 py-12 px-4">
        <div className="container mx-auto">
          <div className="flex flex-col md:flex-row justify-between items-center">
            <div className="flex items-center space-x-2 mb-4 md:mb-0">
              <div className="w-8 h-8 bg-powerplay-button rounded-lg flex items-center justify-center">
                <Play className="w-4 h-4 text-white fill-white" />
              </div>
              <span className="text-xl font-bold text-powerplay-primary">PowerPlay</span>
            </div>
            <div className="text-powerplay-secondary text-sm">© 2025 PowerPlay. All rights reserved.</div>
          </div>
        </div>
      </footer>
    </div>
  )
}
