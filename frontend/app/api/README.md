# PowerPlay API Structure

## Overview
This directory contains all API routes for the PowerPlay application using Next.js 14 App Router.

## Directory Structure
```
app/api/
├── auth/                    # Authentication endpoints
│   ├── login/
│   ├── register/
│   └── logout/
├── upload/                  # Video upload endpoints
│   ├── video/
│   └── player-images/
├── analysis/                # AI analysis endpoints
│   ├── process/
│   ├── status/
│   └── results/
├── highlights/              # Highlight generation endpoints
│   ├── generate/
│   └── download/
├── users/                   # User management endpoints
│   ├── profile/
│   └── settings/
└── webhooks/                # External service webhooks
    └── stripe/
```

## API Route Patterns

### Authentication Routes
- `POST /api/auth/login` - User login
- `POST /api/auth/register` - User registration
- `POST /api/auth/logout` - User logout
- `GET /api/auth/me` - Get current user

### Video Upload Routes
- `POST /api/upload/video` - Upload video file
- `POST /api/upload/player-images` - Upload player reference images
- `GET /api/upload/status/:id` - Get upload status

### Analysis Routes
- `POST /api/analysis/process` - Start video analysis
- `GET /api/analysis/status/:id` - Get analysis status
- `GET /api/analysis/results/:id` - Get analysis results

### Highlights Routes
- `POST /api/highlights/generate` - Generate highlights
- `GET /api/highlights/download/:id` - Download highlights

## File Naming Convention
- `route.ts` - Main route handler
- `types.ts` - TypeScript types for the route
- `utils.ts` - Utility functions
- `validation.ts` - Input validation schemas

## Example Route Structure
```typescript
// app/api/upload/video/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'

const uploadSchema = z.object({
  // validation schema
})

export async function POST(request: NextRequest) {
  try {
    // Handle upload logic
    return NextResponse.json({ success: true })
  } catch (error) {
    return NextResponse.json(
      { error: 'Upload failed' },
      { status: 500 }
    )
  }
}
```

## Middleware
- Authentication middleware in `middleware.ts`
- Rate limiting
- CORS handling
- Request validation

## Database Integration
- Prisma ORM for database operations
- Connection pooling
- Migration management

## External Services
- AWS S3 for file storage
- AI/ML services for video analysis
- Payment processing (Stripe)
- Email services 