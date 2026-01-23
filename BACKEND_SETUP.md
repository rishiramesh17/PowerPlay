# PowerPlay Backend Setup Guide

## Overview
This guide explains how to set up and organize the backend for your PowerPlay application using Next.js 14 API routes.

## Backend Structure

### 1. API Routes (`app/api/`)
```
app/api/
├── README.md                 # API documentation
├── types.ts                  # Shared TypeScript types
├── utils.ts                  # Utility functions
├── auth/                     # Authentication endpoints
│   ├── login/route.ts
│   ├── register/route.ts
│   └── logout/route.ts
├── upload/                   # File upload endpoints
│   ├── video/route.ts        # Video upload
│   └── player-images/route.ts # Player image upload
├── analysis/                 # AI analysis endpoints
│   ├── process/route.ts      # Start analysis
│   ├── status/route.ts       # Check status
│   └── results/route.ts      # Get results
├── highlights/               # Highlight generation
│   ├── generate/route.ts
│   └── download/route.ts
├── users/                    # User management
│   ├── profile/route.ts
│   └── settings/route.ts
└── webhooks/                 # External service webhooks
    └── stripe/route.ts
```

## Implementation Steps

### Step 1: Install Backend Dependencies

```bash
# Database
pnpm add prisma @prisma/client

# File handling
pnpm add multer @types/multer

# Cloud storage (AWS S3)
pnpm add @aws-sdk/client-s3 @aws-sdk/s3-request-presigner

# Authentication
pnpm add next-auth @auth/prisma-adapter bcryptjs @types/bcryptjs

# Validation
pnpm add zod

# Rate limiting
pnpm add express-rate-limit

# Environment variables
pnpm add dotenv
```

### Step 2: Set Up Database

1. **Initialize Prisma:**
```bash
npx prisma init
```

2. **Create schema** in `prisma/schema.prisma`:
```prisma
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql" // or "mysql" or "sqlite"
  url      = env("DATABASE_URL")
}

model User {
  id        String   @id @default(cuid())
  email     String   @unique
  name      String
  password  String
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
  
  videos     Video[]
  analyses   Analysis[]
  highlights Highlight[]
}

model Video {
  id          String   @id @default(cuid())
  userId      String
  title       String
  description String?
  sport       String
  filename    String
  fileSize    Int
  fileUrl     String
  duration    Int?
  status      VideoStatus @default(uploading)
  createdAt   DateTime @default(now())
  updatedAt   DateTime @updatedAt
  
  user      User        @relation(fields: [userId], references: [id])
  analyses  Analysis[]
}

model Analysis {
  id                 String   @id @default(cuid())
  videoId            String
  userId             String
  detectionSettings  Json
  status             AnalysisStatus @default(processing)
  progress           Int      @default(0)
  currentStage       String
  results            Json?
  createdAt          DateTime @default(now())
  updatedAt          DateTime @updatedAt
  completedAt        DateTime?
  
  user      User        @relation(fields: [userId], references: [id])
  video     Video       @relation(fields: [videoId], references: [id])
  highlights Highlight[]
}

model Highlight {
  id         String   @id @default(cuid())
  analysisId String
  userId     String
  type       String
  duration   String
  fileUrl    String
  createdAt  DateTime @default(now())
  
  user     User     @relation(fields: [userId], references: [id])
  analysis Analysis @relation(fields: [analysisId], references: [id])
}

enum VideoStatus {
  uploading
  uploaded
  processing
  completed
  failed
}

enum AnalysisStatus {
  processing
  completed
  failed
}
```

3. **Generate Prisma client:**
```bash
npx prisma generate
```

4. **Run migrations:**
```bash
npx prisma migrate dev --name init
```

### Step 3: Set Up Environment Variables

Create `.env.local`:
```env
# Database
DATABASE_URL="postgresql://username:password@localhost:5432/powerplay"

# Authentication
NEXTAUTH_SECRET="your-secret-key"
NEXTAUTH_URL="http://localhost:3000"

# AWS S3
AWS_ACCESS_KEY_ID="your-access-key"
AWS_SECRET_ACCESS_KEY="your-secret-key"
AWS_REGION="us-east-1"
S3_BUCKET_NAME="powerplay-videos"

# AI Services
OPENAI_API_KEY="your-openai-key"
REPLICATE_API_TOKEN="your-replicate-token"

# External Services
STRIPE_SECRET_KEY="your-stripe-secret"
STRIPE_WEBHOOK_SECRET="your-webhook-secret"
```

### Step 4: Create Database Client

Create `lib/db.ts`:
```typescript
import { PrismaClient } from '@prisma/client'

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined
}

export const prisma = globalForPrisma.prisma ?? new PrismaClient()

if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = prisma
```

### Step 5: Set Up Authentication

Create `app/api/auth/[...nextauth]/route.ts`:
```typescript
import NextAuth from 'next-auth'
import { PrismaAdapter } from '@auth/prisma-adapter'
import CredentialsProvider from 'next-auth/providers/credentials'
import { prisma } from '@/lib/db'
import bcrypt from 'bcryptjs'

const handler = NextAuth({
  adapter: PrismaAdapter(prisma),
  providers: [
    CredentialsProvider({
      name: 'credentials',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' }
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          return null
        }

        const user = await prisma.user.findUnique({
          where: { email: credentials.email }
        })

        if (!user) {
          return null
        }

        const isPasswordValid = await bcrypt.compare(
          credentials.password,
          user.password
        )

        if (!isPasswordValid) {
          return null
        }

        return {
          id: user.id,
          email: user.email,
          name: user.name
        }
      }
    })
  ],
  session: {
    strategy: 'jwt'
  },
  pages: {
    signIn: '/signup'
  }
})

export { handler as GET, handler as POST }
```

### Step 6: Create Middleware

Create `middleware.ts` in the root:
```typescript
import { withAuth } from 'next-auth/middleware'

export default withAuth(
  function middleware(req) {
    // Add custom middleware logic here
  },
  {
    callbacks: {
      authorized: ({ token }) => !!token
    }
  }
)

export const config = {
  matcher: ['/dashboard/:path*', '/upload/:path*', '/api/upload/:path*', '/api/analysis/:path*']
}
```

## API Route Examples

### Video Upload Route
The video upload route (`app/api/upload/video/route.ts`) is already created and includes:
- File validation
- Size limits
- Type checking
- Error handling
- Response formatting

### Analysis Route
The analysis route (`app/api/analysis/process/route.ts`) includes:
- Request validation
- Processing status tracking
- Error handling
- Progress reporting

## Next Steps

### 1. Implement File Storage
- Set up AWS S3 for video storage
- Implement presigned URLs for secure uploads
- Add file processing pipeline

### 2. Add AI Processing
- Integrate with AI services (OpenAI, Replicate, etc.)
- Implement video analysis pipeline
- Add player detection and tracking

### 3. Set Up Background Jobs
- Use a job queue (Bull, Agenda, etc.)
- Process videos asynchronously
- Handle long-running tasks

### 4. Add Monitoring
- Set up logging (Winston, Pino)
- Add error tracking (Sentry)
- Monitor API performance

### 5. Implement Caching
- Add Redis for caching
- Cache analysis results
- Optimize database queries

## Testing Your Backend

### 1. Test API Routes
```bash
# Test video upload
curl -X POST http://localhost:3000/api/upload/video \
  -F "file=@video.mp4" \
  -F "sport=cricket" \
  -F "title=My Game"

# Test analysis
curl -X POST http://localhost:3000/api/analysis/process \
  -H "Content-Type: application/json" \
  -d '{"uploadId":"test-id","detectionSettings":{"useYOLO":true}}'
```

### 2. Test Database
```bash
# Open Prisma Studio
npx prisma studio
```

### 3. Monitor Logs
```bash
# Start development server with logging
pnpm dev
```

## Deployment Considerations

### 1. Environment Setup
- Set up production database
- Configure environment variables
- Set up SSL certificates

### 2. File Storage
- Configure production S3 bucket
- Set up CDN for video delivery
- Implement backup strategies

### 3. Scaling
- Set up load balancers
- Configure auto-scaling
- Implement caching layers

### 4. Monitoring
- Set up application monitoring
- Configure alerting
- Monitor costs and usage

This structure provides a solid foundation for your PowerPlay backend while maintaining scalability and maintainability. 