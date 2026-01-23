// Configuration file for PowerPlay backend

const config = {
  // Server configuration
  server: {
    port: process.env.PORT || 5000,
    nodeEnv: process.env.NODE_ENV || 'development',
    apiBaseUrl: process.env.API_BASE_URL || 'http://localhost:5000',
    frontendUrl: process.env.FRONTEND_URL || 'http://localhost:3000'
  },

  // Database configuration
  database: {
    url: process.env.DATABASE_URL
  },

  // Authentication configuration
  auth: {
    jwtSecret: process.env.JWT_SECRET || 'your-super-secret-jwt-key-change-this-in-production',
    jwtExpiresIn: process.env.JWT_EXPIRES_IN || '7d',
    bcryptRounds: 12
  },

  // AWS S3 configuration
  s3: {
    accessKeyId: process.env.AWS_ACCESS_KEY_ID,
    secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
    region: process.env.AWS_REGION || 'us-east-1',
    bucketName: process.env.S3_BUCKET_NAME,
    bucketRegion: process.env.S3_BUCKET_REGION || 'us-east-1'
  },

  // Email configuration
  email: {
    host: process.env.SMTP_HOST,
    port: parseInt(process.env.SMTP_PORT) || 587,
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASS,
    from: process.env.EMAIL_FROM || 'noreply@powerplay.com'
  },

  // Payment configuration (Stripe)
  stripe: {
    secretKey: process.env.STRIPE_SECRET_KEY,
    publishableKey: process.env.STRIPE_PUBLISHABLE_KEY,
    webhookSecret: process.env.STRIPE_WEBHOOK_SECRET
  },

  // AI Services configuration
  ai: {
    openai: {
      apiKey: process.env.OPENAI_API_KEY
    },
    replicate: {
      apiToken: process.env.REPLICATE_API_TOKEN
    }
  },

  // Redis configuration
  redis: {
    url: process.env.REDIS_URL || 'redis://localhost:6379'
  },

  // File upload configuration
  upload: {
    maxFileSize: parseInt(process.env.MAX_FILE_SIZE) || 524288000, // 500MB
    maxImageSize: parseInt(process.env.MAX_IMAGE_SIZE) || 10485760, // 10MB
    allowedVideoTypes: ['video/mp4', 'video/avi', 'video/mov', 'video/mkv', 'video/webm'],
    allowedImageTypes: ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
  },

  // Rate limiting configuration
  rateLimit: {
    windowMs: parseInt(process.env.RATE_LIMIT_WINDOW_MS) || 900000, // 15 minutes
    maxRequests: parseInt(process.env.RATE_LIMIT_MAX_REQUESTS) || 100
  },

  // Security configuration
  security: {
    corsOrigin: process.env.CORS_ORIGIN || 'http://localhost:3000',
    sessionSecret: process.env.SESSION_SECRET || 'your-session-secret'
  },

  // Logging configuration
  logging: {
    level: process.env.LOG_LEVEL || 'info',
    file: process.env.LOG_FILE || 'logs/app.log'
  },

  // Monitoring configuration
  monitoring: {
    sentryDsn: process.env.SENTRY_DSN
  }
};

// Validate required configuration
const validateConfig = () => {
  const required = [
    'database.url',
    'auth.jwtSecret',
    's3.accessKeyId',
    's3.secretAccessKey',
    's3.bucketName',
    'email.host',
    'email.user',
    'email.pass'
  ];

  const missing = required.filter(key => {
    const value = key.split('.').reduce((obj, k) => obj?.[k], config);
    return !value;
  });

  if (missing.length > 0) {
    console.warn('Missing required configuration:', missing);
    console.warn('Please check your environment variables.');
  }
};

// Validate configuration on load
validateConfig();

module.exports = config; 