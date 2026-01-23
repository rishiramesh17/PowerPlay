import type React from "react"
import type { Metadata } from "next"
import { Lora, Tomorrow } from "next/font/google"
import "./globals.css"

const manrope = Lora({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-body",
})

const jersey10 = Tomorrow({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-heading",
})

export const metadata: Metadata = {
  title: "PowerPlay - AI-Powered Player-Centric Video Editor",
  description:
    "Transform hours of game footage into personalized highlight reels focused on individual players",
  generator: "v0.dev",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={`${manrope.variable} ${jersey10.variable}`}>
      <body>{children}</body>
    </html>
  )
}