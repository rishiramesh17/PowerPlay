const express = require('express');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const { body, validationResult } = require('express-validator');
const { createErrorResponse, createSuccessResponse } = require('../utils/responseHelpers');
const router = express.Router();

// Register user
router.post('/register',
  [
    body('email').isEmail().withMessage('Valid email is required'),
    body('password').isLength({ min: 6 }).withMessage('Password must be at least 6 characters'),
    body('name').notEmpty().withMessage('Name is required'),
  ],
  async (req, res) => {
    try {
      const errors = validationResult(req);
      if (!errors.isEmpty()) {
        return res.status(400).json({
          error: 'Validation failed',
          details: errors.array()
        });
      }

      const { email, password, name } = req.body;

      // TODO: Check if user already exists
      // const existingUser = await User.findOne({ email });
      // if (existingUser) {
      //   return createErrorResponse(res, 'User already exists', 400);
      // }

      // Hash password
      const saltRounds = 12;
      const hashedPassword = await bcrypt.hash(password, saltRounds);

      // TODO: Create user in database
      const user = {
        id: `user-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        email,
        name,
        password: hashedPassword,
        createdAt: new Date()
      };

      // Generate JWT token
      const token = jwt.sign(
        { userId: user.id, email: user.email },
        process.env.JWT_SECRET || 'your-secret-key',
        { expiresIn: '7d' }
      );

      return createSuccessResponse(res, {
        success: true,
        message: 'User registered successfully',
        user: {
          id: user.id,
          email: user.email,
          name: user.name
        },
        token
      });

    } catch (error) {
      console.error('Registration error:', error);
      return createErrorResponse(res, 'Registration failed', 500);
    }
  }
);

// Login user
router.post('/login',
  [
    body('email').isEmail().withMessage('Valid email is required'),
    body('password').notEmpty().withMessage('Password is required'),
  ],
  async (req, res) => {
    try {
      const errors = validationResult(req);
      if (!errors.isEmpty()) {
        return res.status(400).json({
          error: 'Validation failed',
          details: errors.array()
        });
      }

      const { email, password } = req.body;

      // TODO: Find user in database
      // const user = await User.findOne({ email });
      // if (!user) {
      //   return createErrorResponse(res, 'Invalid credentials', 401);
      // }

      // Mock user for now
      const user = {
        id: 'mock-user-id',
        email,
        password: '$2a$12$mock-hashed-password',
        name: 'Mock User'
      };

      // Verify password
      const isPasswordValid = await bcrypt.compare(password, user.password);
      if (!isPasswordValid) {
        return createErrorResponse(res, 'Invalid credentials', 401);
      }

      // Generate JWT token
      const token = jwt.sign(
        { userId: user.id, email: user.email },
        process.env.JWT_SECRET || 'your-secret-key',
        { expiresIn: '7d' }
      );

      return createSuccessResponse(res, {
        success: true,
        message: 'Login successful',
        user: {
          id: user.id,
          email: user.email,
          name: user.name
        },
        token
      });

    } catch (error) {
      console.error('Login error:', error);
      return createErrorResponse(res, 'Login failed', 500);
    }
  }
);

// Get current user
router.get('/me', async (req, res) => {
  try {
    // TODO: Get user from database using token
    const user = {
      id: 'mock-user-id',
      email: 'user@example.com',
      name: 'Mock User',
      createdAt: new Date()
    };

    return createSuccessResponse(res, {
      user
    });

  } catch (error) {
    console.error('Get user error:', error);
    return createErrorResponse(res, 'Failed to get user', 500);
  }
});

// Logout user
router.post('/logout', async (req, res) => {
  try {
    // TODO: Invalidate token (add to blacklist)
    return createSuccessResponse(res, {
      success: true,
      message: 'Logout successful'
    });

  } catch (error) {
    console.error('Logout error:', error);
    return createErrorResponse(res, 'Logout failed', 500);
  }
});

// Refresh token
router.post('/refresh', async (req, res) => {
  try {
    const { token } = req.body;

    if (!token) {
      return createErrorResponse(res, 'Token is required', 400);
    }

    // TODO: Verify and refresh token
    const newToken = jwt.sign(
      { userId: 'mock-user-id', email: 'user@example.com' },
      process.env.JWT_SECRET || 'your-secret-key',
      { expiresIn: '7d' }
    );

    return createSuccessResponse(res, {
      success: true,
      token: newToken
    });

  } catch (error) {
    console.error('Token refresh error:', error);
    return createErrorResponse(res, 'Token refresh failed', 500);
  }
});

module.exports = router; 