// Utility functions for PowerPlay API

import { NextResponse } from 'next/server'
import { ApiError } from './types'

// Error response helper
export function createErrorResponse(error: string, status: number = 500, details?: any): NextResponse {
  const errorResponse: ApiError = {
    error,
    details,
    code: status.toString()
  }
  
  return NextResponse.json(errorResponse, { status })
}

// Success response helper
export function createSuccessResponse(data: any, status: number = 200): NextResponse {
  return NextResponse.json(data, { status })
}

// File validation helpers
export function validateVideoFile(file: File): { valid: boolean; error?: string } {
  const allowedTypes = ['video/mp4', 'video/avi', 'video/mov', 'video/mkv', 'video/webm']
  const maxSize = 500 * 1024 * 1024 // 500MB

  if (!file) {
    return { valid: false, error: 'No file provided' }
  }

  if (!allowedTypes.includes(file.type)) {
    return { 
      valid: false, 
      error: `Invalid file type. Allowed types: ${allowedTypes.join(', ')}` 
    }
  }

  if (file.size > maxSize) {
    return { 
      valid: false, 
      error: `File too large. Maximum size is ${maxSize / (1024 * 1024)}MB` 
    }
  }

  return { valid: true }
}

export function validateImageFile(file: File): { valid: boolean; error?: string } {
  const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
  const maxSize = 10 * 1024 * 1024 // 10MB

  if (!file) {
    return { valid: false, error: 'No file provided' }
  }

  if (!allowedTypes.includes(file.type)) {
    return { 
      valid: false, 
      error: `Invalid file type. Allowed types: ${allowedTypes.join(', ')}` 
    }
  }

  if (file.size > maxSize) {
    return { 
      valid: false, 
      error: `File too large. Maximum size is ${maxSize / (1024 * 1024)}MB` 
    }
  }

  return { valid: true }
}

// ID generation helpers
export function generateUploadId(): string {
  return `upload-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

export function generateAnalysisId(): string {
  return `analysis-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

export function generateHighlightId(): string {
  return `highlight-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

// File size formatting
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'
  
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// Time formatting
export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`
}

// Progress calculation
export function calculateProgress(completed: number, total: number): number {
  if (total === 0) return 0
  return Math.round((completed / total) * 100)
}

// Rate limiting helper (simple in-memory implementation)
const rateLimitMap = new Map<string, { count: number; resetTime: number }>()

export function checkRateLimit(identifier: string, limit: number, windowMs: number): boolean {
  const now = Date.now()
  const record = rateLimitMap.get(identifier)
  
  if (!record || now > record.resetTime) {
    rateLimitMap.set(identifier, { count: 1, resetTime: now + windowMs })
    return true
  }
  
  if (record.count >= limit) {
    return false
  }
  
  record.count++
  return true
}

// Authentication helper (placeholder - implement with your auth solution)
export async function getCurrentUser(request: Request): Promise<any | null> {
  // TODO: Implement authentication logic
  // This could use JWT tokens, session cookies, etc.
  const authHeader = request.headers.get('authorization')
  
  if (!authHeader) {
    return null
  }
  
  // TODO: Validate token and return user
  return null
}

// CORS helper
export function setCorsHeaders(response: NextResponse): NextResponse {
  response.headers.set('Access-Control-Allow-Origin', '*')
  response.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
  response.headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization')
  
  return response
}

// Logging helper
export function logApiRequest(method: string, path: string, status: number, duration: number) {
  const timestamp = new Date().toISOString()
  console.log(`[${timestamp}] ${method} ${path} - ${status} (${duration}ms)`)
}

// Validation helper for common fields
export function validateRequiredFields(data: any, fields: string[]): { valid: boolean; missing: string[] } {
  const missing: string[] = []
  
  for (const field of fields) {
    if (!data[field] || (typeof data[field] === 'string' && data[field].trim() === '')) {
      missing.push(field)
    }
  }
  
  return {
    valid: missing.length === 0,
    missing
  }
}

// Sanitize filename
export function sanitizeFilename(filename: string): string {
  return filename
    .replace(/[^a-zA-Z0-9.-]/g, '_')
    .replace(/_+/g, '_')
    .toLowerCase()
}

// Generate presigned URL (placeholder for S3)
export async function generatePresignedUrl(key: string, operation: 'get' | 'put'): Promise<string> {
  // TODO: Implement S3 presigned URL generation
  return `https://example.com/${key}`
} 