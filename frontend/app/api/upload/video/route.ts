import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'

// Validation schema for video upload
const uploadSchema = z.object({
  sport: z.string().min(1, 'Sport is required'),
  title: z.string().min(1, 'Title is required'),
  description: z.string().optional(),
})

export async function POST(request: NextRequest) {
  try {
    // Parse form data
    const formData = await request.formData()
    const file = formData.get('file') as File
    const sport = formData.get('sport') as string
    const title = formData.get('title') as string
    const description = formData.get('description') as string

    // Validate input
    const validation = uploadSchema.safeParse({ sport, title, description })
    if (!validation.success) {
      return NextResponse.json(
        { error: 'Invalid input', details: validation.error },
        { status: 400 }
      )
    }

    // Validate file
    if (!file) {
      return NextResponse.json(
        { error: 'No file provided' },
        { status: 400 }
      )
    }

    // Check file type
    const allowedTypes = ['video/mp4', 'video/avi', 'video/mov', 'video/mkv']
    if (!allowedTypes.includes(file.type)) {
      return NextResponse.json(
        { error: 'Invalid file type. Only MP4, AVI, MOV, and MKV are allowed' },
        { status: 400 }
      )
    }

    // Check file size (max 500MB)
    const maxSize = 500 * 1024 * 1024 // 500MB
    if (file.size > maxSize) {
      return NextResponse.json(
        { error: 'File too large. Maximum size is 500MB' },
        { status: 400 }
      )
    }

    // TODO: Upload to cloud storage (AWS S3, etc.)
    // TODO: Save metadata to database
    // TODO: Return upload ID for tracking

    return NextResponse.json({
      success: true,
      message: 'Video uploaded successfully',
      uploadId: 'temp-upload-id-' + Date.now(),
      filename: file.name,
      size: file.size,
      type: file.type
    })

  } catch (error) {
    console.error('Upload error:', error)
    return NextResponse.json(
      { error: 'Upload failed' },
      { status: 500 }
    )
  }
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const uploadId = searchParams.get('id')

    if (!uploadId) {
      return NextResponse.json(
        { error: 'Upload ID required' },
        { status: 400 }
      )
    }

    // TODO: Get upload status from database
    // TODO: Return processing status

    return NextResponse.json({
      uploadId,
      status: 'uploaded',
      progress: 100,
      message: 'Upload completed'
    })

  } catch (error) {
    console.error('Status check error:', error)
    return NextResponse.json(
      { error: 'Failed to get status' },
      { status: 500 }
    )
  }
} 