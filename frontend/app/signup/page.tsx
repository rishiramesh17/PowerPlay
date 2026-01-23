"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import Link from "next/link"

export default function SignupPage() {
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    confirm: "",
    terms: false,
  })
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target
    setForm((prev) => ({
      ...prev,
      [name]: type === "checkbox" ? checked : value,
    }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    if (!form.name || !form.email || !form.password || !form.confirm) {
      setError("All fields are required.")
      return
    }
    if (form.password !== form.confirm) {
      setError("Passwords do not match.")
      return
    }
    if (!form.terms) {
      setError("You must agree to the terms.")
      return
    }
    setLoading(true)
    setTimeout(() => {
      setLoading(false)
      alert("Signed up! (Demo only)")
    }, 1200)
  }

  return (
    <div className="min-h-screen bg-powerplay-gradient flex flex-col">
      {/* Header */}
      <header className="border-b border-powerplay bg-black/20 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 bg-powerplay-button rounded-lg flex items-center justify-center">
              <svg className="w-4 h-4 text-white fill-white" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z" />
              </svg>
            </div>
            <span className="text-xl font-heading text-powerplay-primary">PowerPlay</span>
          </div>
          <div className="flex items-center space-x-3">
            <Button asChild variant="ghost" className="text-powerplay-primary hover:bg-white/10">
              <Link href="/">Home</Link>
            </Button>
          </div>
        </div>
      </header>

      {/* Signup Form */}
      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <Card className="w-full max-w-md bg-powerplay-gradient-card border-powerplay backdrop-blur-sm">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl font-heading text-powerplay-primary">
              Create your account
            </CardTitle>
            <CardDescription className="text-powerplay-secondary">
              Sign up to start creating highlight reels
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-6" onSubmit={handleSubmit}>
              <div>
                <Label htmlFor="name" className="text-powerplay-primary">
                  Name
                </Label>
                <Input
                  id="name"
                  name="name"
                  type="text"
                  autoComplete="name"
                  placeholder="Your Name"
                  className="bg-white/10 border-white/20 text-white placeholder:text-white/50 focus:border-powerplay-button focus:outline-none"
                  value={form.name}
                  onChange={handleChange}
                />
              </div>
              <div>
                <Label htmlFor="email" className="text-powerplay-primary">
                  Email
                </Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@email.com"
                  className="bg-white/10 border-white/20 text-white placeholder:text-white/50 focus:border-powerplay-button focus:outline-none"
                  value={form.email}
                  onChange={handleChange}
                />
              </div>
              <div>
                <Label htmlFor="password" className="text-powerplay-primary">
                  Password
                </Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Password"
                  className="bg-white/10 border-white/20 text-white placeholder:text-white/50 focus:border-powerplay-button focus:outline-none"
                  value={form.password}
                  onChange={handleChange}
                />
              </div>
              <div>
                <Label htmlFor="confirm" className="text-powerplay-primary">
                  Confirm Password
                </Label>
                <Input
                  id="confirm"
                  name="confirm"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Confirm Password"
                  className="bg-white/10 border-white/20 text-white placeholder:text-white/50 focus:border-powerplay-button focus:outline-none"
                  value={form.confirm}
                  onChange={handleChange}
                />
              </div>

              <div className="flex items-center space-x-2">
                <input
                  id="terms"
                  name="terms"
                  type="checkbox"
                  checked={form.terms}
                  onChange={handleChange}
                  className="accent-pink-500 w-4 h-4"
                />
                <Label htmlFor="terms" className="text-powerplay-secondary text-sm">
                  I agree to the{" "}
                  <a href="#" className="underline text-powerplay-primary">
                    terms and conditions
                  </a>
                </Label>
              </div>

              {error && (
                <div className="text-red-400 text-sm text-center bg-red-500/10 border border-red-500/30 rounded-md py-2">
                  {error}
                </div>
              )}

              <Button
                type="submit"
                className="w-full bg-powerplay-button hover:bg-powerplay-button-hover text-lg py-4"
                disabled={loading}
              >
                {loading ? "Signing up..." : "Sign Up"}
              </Button>
            </form>

            <div className="text-center mt-6">
              <span className="text-powerplay-secondary text-sm">
                Already have an account?{" "}
              </span>
              <Link href="/login" className="text-powerplay-primary underline text-sm">
                Sign in
              </Link>
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  )
}