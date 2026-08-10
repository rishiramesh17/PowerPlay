# PowerPlay Backend

A Node.js/Express backend API for the PowerPlay video analysis application.

## 🏗️ Project Structure

```
backend/
├── src/
│   ├── server.js              # Main server file
│   ├── routes/                # API route handlers
│   │   ├── auth.js           # Authentication routes
│   │   ├── upload.js         # File upload routes
│   │   ├── analysis.js       # AI analysis routes
│   │   ├── highlights.js     # Highlight generation routes
│   │   ├── users.js          # User management routes
│   │   └── webhooks.js       # External service webhooks
│   ├── middleware/            # Express middleware
│   │   ├── auth.js           # Authentication middleware
│   │   └── errorHandler.js   # Error handling middleware
│   ├── utils/                 # Utility functions
│   │   ├── responseHelpers.js # API response helpers
│   │   ├── fileValidation.js # File validation utilities
│   │   └── idGenerators.js   # ID generation utilities
│   ├── services/              # Business logic services
│   │   ├── s3Service.js      # AWS S3 integration
│   │   ├── analysisService.js # AI analysis service
│   │   └── emailService.js   # Email service
│   ├── models/                # Database models (TODO)
│   └── config/                # Configuration files (TODO)
├── package.json               # Dependencies and scripts
├── .env.example              # Environment variables template
└── README.md                 # This file
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd backend
npm install
```

### 2. Set Up Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# Server
PORT=5000
NODE_ENV=development

# Database
DATABASE_URL="postgresql://username:password@localhost:5432/powerplay"

# Authentication
JWT_SECRET="your-super-secret-jwt-key"

# AWS S3
AWS_ACCESS_KEY_ID="your-access-key"
AWS_SECRET_ACCESS_KEY="your-secret-key"
AWS_REGION="us-east-1"
S3_BUCKET_NAME="powerplay-videos"

# External Services
FRONTEND_URL="http://localhost:3000"
STRIPE_SECRET_KEY="your-stripe-secret"
STRIPE_WEBHOOK_SECRET="your-webhook-secret"

# AI Services
OPENAI_API_KEY="your-openai-key"
REPLICATE_API_TOKEN="your-replicate-token"
```

### 3. Start Development Server

```bash
npm run dev
```

The server will start on `http://localhost:5000`

## 📚 API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - User login
- `GET /api/auth/me` - Get current user
- `POST /api/auth/logout` - User logout
- `POST /api/auth/refresh` - Refresh token

### File Upload
- `POST /api/upload/video` - Upload video file
- `POST /api/upload/player-images` - Upload player reference images
- `GET /api/upload/status/:id` - Get upload status
- `POST /api/upload/presigned-url` - Get presigned URL for direct upload

### AI Analysis
- `POST /api/analysis/process` - Start video analysis
- `GET /api/analysis/status/:id` - Get analysis status
- `GET /api/analysis/results/:id` - Get analysis results
- `DELETE /api/analysis/cancel/:id` - Cancel analysis
- `GET /api/analysis/list` - List user's analyses

### Highlights
- `POST /api/highlights/generate` - Generate highlights
- `GET /api/highlights/status/:id` - Get highlight status
- `GET /api/highlights/download/:id` - Download highlight
- `GET /api/highlights/list` - List user's highlights
- `DELETE /api/highlights/:id` - Delete highlight

### User Management
- `GET /api/users/profile` - Get user profile
- `PUT /api/users/profile` - Update user profile
- `GET /api/users/settings` - Get user settings
- `PUT /api/users/settings` - Update user settings
- `GET /api/users/stats` - Get user statistics
- `DELETE /api/users/account` - Delete user account

### Webhooks
- `POST /api/webhooks/stripe` - Stripe payment webhooks
- `POST /api/webhooks/ai-service` - AI service callbacks
- `POST /api/webhooks/video-processing` - Video processing callbacks
- `POST /api/webhooks/email-service` - Email service callbacks

## 🔧 Development

### Available Scripts

```bash
npm run dev          # Start development server with nodemon
npm start           # Start production server
npm test            # Run tests
npm run lint        # Lint code
npm run db:migrate  # Run database migrations
npm run db:generate # Generate Prisma client
npm run db:studio   # Open Prisma Studio
```

### Code Style

- Use ES6+ features
- Follow Express.js best practices
- Use async/await for asynchronous operations
- Implement proper error handling
- Use middleware for cross-cutting concerns

### Testing

```bash
# Run all tests
npm test

# Run tests in watch mode
npm run test:watch

# Run tests with coverage
npm run test:coverage
```

## 🗄️ Database Setup

### 1. Install Prisma

```bash
npm install prisma @prisma/client
npx prisma init
```

### 2. Configure Database

Update `prisma/schema.prisma` with your database configuration.

### 3. Run Migrations

```bash
npx prisma migrate dev --name init
npx prisma generate
```

### 4. Seed Database (Optional)

```bash
npx prisma db seed
```

## 🔒 Security Features

- JWT-based authentication
- Password hashing with bcrypt
- Rate limiting
- CORS protection
- Helmet security headers
- Input validation with express-validator
- File upload validation
- Error handling middleware

## 📦 Dependencies

### Core Dependencies
- `express` - Web framework
- `cors` - Cross-origin resource sharing
- `helmet` - Security headers
- `morgan` - HTTP request logging
- `dotenv` - Environment variables

### Authentication
- `bcryptjs` - Password hashing
- `jsonwebtoken` - JWT tokens

### File Handling
- `multer` - File upload middleware
- `aws-sdk` - AWS S3 integration

### Database
- `prisma` - Database ORM
- `@prisma/client` - Prisma client

### Validation & Security
- `express-validator` - Input validation
- `express-rate-limit` - Rate limiting

### Background Processing
- `bull` - Job queue
- `redis` - Redis client
- `node-cron` - Cron jobs

### Utilities
- `compression` - Response compression
- `winston` - Logging
- `sharp` - Image processing
- `ffmpeg-static` - Video processing

## 🚀 Deployment

### Environment Setup

1. Set up production database
2. Configure environment variables
3. Set up AWS S3 bucket
4. Configure external services

### Build & Deploy

```bash
# Install dependencies
npm install --production

# Start server
npm start
```

### Docker Deployment

```bash
# Build image
docker build -t powerplay-backend .

# Run container
docker run -p 5000:5000 powerplay-backend
```

## 📊 Monitoring

### Health Check

```bash
curl http://localhost:5000/health
```

### Logging

Logs are written to console and can be configured for file output.

### Error Tracking

Integrate with services like Sentry for error tracking.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## 🆘 Support

For support, email rishi17ramesh@gmail.com or create an issue in the repository. 
