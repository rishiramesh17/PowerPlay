const winston = require('winston');
const path = require('path');

// Define log format
const logFormat = winston.format.combine(
  winston.format.timestamp(),
  winston.format.errors({ stack: true }),
  winston.format.json()
);

// Create logger instance
const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  format: logFormat,
  defaultMeta: { service: 'powerplay-backend' },
  transports: [
    // Write all logs with importance level of `error` or less to `error.log`
    new winston.transports.File({ 
      filename: path.join(__dirname, '../../logs/error.log'), 
      level: 'error' 
    }),
    // Write all logs with importance level of `info` or less to `combined.log`
    new winston.transports.File({ 
      filename: path.join(__dirname, '../../logs/combined.log') 
    }),
  ],
});

// If we're not in production then log to the `console` with the format:
// `${info.level}: ${info.message} JSON.stringify({ ...rest }) `
if (process.env.NODE_ENV !== 'production') {
  logger.add(new winston.transports.Console({
    format: winston.format.combine(
      winston.format.colorize(),
      winston.format.simple()
    )
  }));
}

// Create a stream object with a 'write' function that will be used by Morgan
logger.stream = {
  write: function(message) {
    logger.info(message.trim());
  },
};

// Helper functions for different log levels
const logInfo = (message, meta = {}) => {
  logger.info(message, meta);
};

const logError = (message, error = null, meta = {}) => {
  if (error) {
    meta.error = {
      message: error.message,
      stack: error.stack,
      name: error.name
    };
  }
  logger.error(message, meta);
};

const logWarn = (message, meta = {}) => {
  logger.warn(message, meta);
};

const logDebug = (message, meta = {}) => {
  logger.debug(message, meta);
};

// API request logging
const logApiRequest = (req, res, duration) => {
  const logData = {
    method: req.method,
    url: req.url,
    statusCode: res.statusCode,
    duration: `${duration}ms`,
    userAgent: req.get('User-Agent'),
    ip: req.ip,
    userId: req.user?.id || 'anonymous'
  };

  if (res.statusCode >= 400) {
    logError('API Request Error', null, logData);
  } else {
    logInfo('API Request', logData);
  }
};

// Database operation logging
const logDbOperation = (operation, table, duration, success = true) => {
  const logData = {
    operation,
    table,
    duration: `${duration}ms`,
    success
  };

  if (success) {
    logDebug('Database Operation', logData);
  } else {
    logError('Database Operation Failed', null, logData);
  }
};

// File operation logging
const logFileOperation = (operation, filename, size, success = true) => {
  const logData = {
    operation,
    filename,
    size: size ? `${size} bytes` : undefined,
    success
  };

  if (success) {
    logInfo('File Operation', logData);
  } else {
    logError('File Operation Failed', null, logData);
  }
};

// Authentication logging
const logAuth = (action, userId, success = true, details = {}) => {
  const logData = {
    action,
    userId,
    success,
    ...details
  };

  if (success) {
    logInfo('Authentication', logData);
  } else {
    logWarn('Authentication Failed', logData);
  }
};

// Analysis job logging
const logAnalysisJob = (action, analysisId, userId, details = {}) => {
  const logData = {
    action,
    analysisId,
    userId,
    ...details
  };

  logInfo('Analysis Job', logData);
};

// Error logging with context
const logErrorWithContext = (error, context = {}) => {
  logError('Application Error', error, context);
};

module.exports = {
  logger,
  logInfo,
  logError,
  logWarn,
  logDebug,
  logApiRequest,
  logDbOperation,
  logFileOperation,
  logAuth,
  logAnalysisJob,
  logErrorWithContext
}; 