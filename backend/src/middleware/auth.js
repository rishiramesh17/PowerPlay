const jwt = require('jsonwebtoken');
const { createErrorResponse } = require('../utils/responseHelpers');

const authMiddleware = (req, res, next) => {
  try {
    // Get token from header
    const authHeader = req.headers.authorization;
    
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return createErrorResponse(res, 'Access denied. No token provided.', 401);
    }

    // Extract token
    const token = authHeader.substring(7); // Remove 'Bearer ' prefix

    if (!token) {
      return createErrorResponse(res, 'Access denied. No token provided.', 401);
    }

    // Verify token
    const decoded = jwt.verify(token, process.env.JWT_SECRET || 'your-secret-key');
    
    // Add user info to request
    req.user = {
      id: decoded.userId,
      email: decoded.email
    };

    next();
  } catch (error) {
    if (error.name === 'TokenExpiredError') {
      return createErrorResponse(res, 'Token expired', 401);
    } else if (error.name === 'JsonWebTokenError') {
      return createErrorResponse(res, 'Invalid token', 401);
    } else {
      console.error('Auth middleware error:', error);
      return createErrorResponse(res, 'Authentication failed', 500);
    }
  }
};

// Optional auth middleware (doesn't fail if no token)
const optionalAuthMiddleware = (req, res, next) => {
  try {
    const authHeader = req.headers.authorization;
    
    if (authHeader && authHeader.startsWith('Bearer ')) {
      const token = authHeader.substring(7);
      const decoded = jwt.verify(token, process.env.JWT_SECRET || 'your-secret-key');
      
      req.user = {
        id: decoded.userId,
        email: decoded.email
      };
    }

    next();
  } catch (error) {
    // Continue without user info if token is invalid
    next();
  }
};

// Admin middleware (requires admin role)
const adminMiddleware = (req, res, next) => {
  try {
    // First check if user is authenticated
    if (!req.user) {
      return createErrorResponse(res, 'Authentication required', 401);
    }

    // TODO: Check if user has admin role
    // const user = await User.findById(req.user.id);
    // if (!user || user.role !== 'admin') {
    //   return createErrorResponse(res, 'Admin access required', 403);
    // }

    next();
  } catch (error) {
    console.error('Admin middleware error:', error);
    return createErrorResponse(res, 'Authorization failed', 500);
  }
};

module.exports = {
  authMiddleware,
  optionalAuthMiddleware,
  adminMiddleware
}; 