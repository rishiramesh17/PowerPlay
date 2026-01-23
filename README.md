# PowerPlay - Video Analysis Platform

A modern video analysis platform that uses AI to automatically generate sports highlights from uploaded videos.

## 🏗️ Project Structure

This project is organized into two separate applications:

```
powerplay/
├── frontend/          # Next.js 14 React frontend
│   ├── app/          # Next.js App Router pages
│   ├── components/   # React components
│   ├── hooks/        # Custom React hooks
│   ├── lib/          # Utility functions
│   ├── public/       # Static assets
│   └── package.json  # Frontend dependencies
├── backend/           # Node.js/Express API
│   ├── src/          # Backend source code
│   ├── routes/       # API route handlers
│   ├── middleware/   # Express middleware
│   ├── utils/        # Utility functions
│   └── package.json  # Backend dependencies
├── CHATGPT_PROMPTS.md # ChatGPT integration guide
├── DEVELOPMENT_WORKFLOW.md # Development workflow
└── README.md         # This file
```

## 🚀 Quick Start

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

Frontend will be available at: `http://localhost:3000`

### Backend (Express API)

```bash
cd backend
npm install
cp env.example .env
# Edit .env with your configuration
npm run dev
```

Backend will be available at: `http://localhost:5000`

## 📚 Documentation

- **[Frontend Guide](frontend/README.md)** - Next.js frontend documentation
- **[Backend Guide](backend/README.md)** - Express API documentation
- **[Development Workflow](DEVELOPMENT_WORKFLOW.md)** - How to work with ChatGPT
- **[ChatGPT Prompts](CHATGPT_PROMPTS.md)** - Ready-to-use prompts

## 🛠️ Tech Stack

### Frontend
- **Framework**: Next.js 14 with App Router
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **UI Components**: Shadcn/ui
- **State Management**: React hooks
- **Forms**: React Hook Form + Zod

### Backend
- **Framework**: Express.js
- **Language**: JavaScript/Node.js
- **Database**: PostgreSQL with Prisma ORM
- **Authentication**: JWT with bcrypt
- **File Storage**: AWS S3
- **AI Processing**: OpenAI, Replicate
- **Job Queue**: Bull with Redis
- **Validation**: Express Validator

## 🔧 Development

### Prerequisites
- Node.js 18+
- PostgreSQL
- Redis (for job queues)
- AWS S3 bucket
- AI service API keys

### Environment Setup

1. **Frontend Environment**:
   ```bash
   cd frontend
   cp .env.example .env.local
   # Configure frontend environment variables
   ```

2. **Backend Environment**:
   ```bash
   cd backend
   cp env.example .env
   # Configure backend environment variables
   ```

### Database Setup

```bash
cd backend
npx prisma migrate dev
npx prisma generate
```

### Running Both Applications

You can run both frontend and backend simultaneously:

```bash
# Terminal 1 - Frontend
cd frontend && npm run dev

# Terminal 2 - Backend
cd backend && npm run dev
```

## 📋 Features

### Core Features
- ✅ Video upload and processing
- ✅ AI-powered player detection
- ✅ Automatic highlight generation
- ✅ User authentication and profiles
- ✅ Real-time processing status
- ✅ Download and sharing capabilities

### Technical Features
- ✅ Responsive design
- ✅ TypeScript support
- ✅ API rate limiting
- ✅ File validation
- ✅ Error handling
- ✅ Logging and monitoring
- ✅ Security best practices

## 🔒 Security

- JWT-based authentication
- Password hashing with bcrypt
- CORS protection
- Rate limiting
- Input validation
- File upload security
- Environment variable protection

## 🚀 Deployment

### Frontend Deployment
- Vercel (recommended for Next.js)
- Netlify
- AWS Amplify

### Backend Deployment
- Railway
- Heroku
- AWS EC2
- Docker containers

### Database
- PostgreSQL on Railway/Heroku
- AWS RDS
- Supabase

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test both frontend and backend
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## 🆘 Support

- **Documentation**: Check the README files in each folder
- **Issues**: Create an issue in the repository
- **Email**: rishi17ramesh@gmail.com

## 🔄 Development Workflow

1. **Frontend Development**: Work in the `frontend/` folder
2. **Backend Development**: Work in the `backend/` folder
3. **API Integration**: Frontend calls backend at `http://localhost:5000/api`
4. **Database**: Use Prisma migrations for schema changes
5. **Testing**: Test both applications independently

## 📊 Project Status

- ✅ Project structure setup
- ✅ Frontend foundation (Next.js + TypeScript)
- ✅ Backend foundation (Express + Node.js)
- ✅ Authentication system
- ✅ File upload system
- ✅ API route structure
- 🔄 AI integration (in progress)
- 🔄 Database implementation (in progress)
- 🔄 Deployment setup (in progress)

---

**PowerPlay** - Transform your sports videos into professional highlights with AI. 
