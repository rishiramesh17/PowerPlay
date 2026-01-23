const express = require('express');
const { body, validationResult } = require('express-validator');
const { createErrorResponse, createSuccessResponse } = require('../utils/responseHelpers');
const router = express.Router();

// Get user profile
router.get('/profile', async (req, res) => {
  try {
    const userId = req.user.id;

    // TODO: Get user profile from database
    const profile = {
      id: userId,
      email: 'user@example.com',
      name: 'Mock User',
      createdAt: new Date(),
      subscription: {
        plan: 'free',
        status: 'active',
        currentPeriodEnd: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000)
      }
    };

    return createSuccessResponse(res, { profile });

  } catch (error) {
    console.error('Get profile error:', error);
    return createErrorResponse(res, 'Failed to get profile', 500);
  }
});

// Update user profile
router.put('/profile',
  [
    body('name').optional().isString().withMessage('Name must be a string'),
    body('email').optional().isEmail().withMessage('Valid email is required'),
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

      const userId = req.user.id;
      const { name, email } = req.body;

      // TODO: Update user in database
      const updatedProfile = {
        id: userId,
        name: name || 'Mock User',
        email: email || 'user@example.com',
        updatedAt: new Date()
      };

      return createSuccessResponse(res, {
        success: true,
        message: 'Profile updated successfully',
        profile: updatedProfile
      });

    } catch (error) {
      console.error('Update profile error:', error);
      return createErrorResponse(res, 'Failed to update profile', 500);
    }
  }
);

// Get user settings
router.get('/settings', async (req, res) => {
  try {
    const userId = req.user.id;

    // TODO: Get user settings from database
    const settings = {
      notifications: {
        email: true,
        push: false
      },
      privacy: {
        publicProfile: false,
        shareAnalytics: true
      },
      preferences: {
        defaultSport: 'cricket',
        language: 'en',
        timezone: 'UTC'
      }
    };

    return createSuccessResponse(res, { settings });

  } catch (error) {
    console.error('Get settings error:', error);
    return createErrorResponse(res, 'Failed to get settings', 500);
  }
});

// Update user settings
router.put('/settings', async (req, res) => {
  try {
    const userId = req.user.id;
    const { notifications, privacy, preferences } = req.body;

    // TODO: Update user settings in database
    const updatedSettings = {
      notifications: notifications || {},
      privacy: privacy || {},
      preferences: preferences || {}
    };

    return createSuccessResponse(res, {
      success: true,
      message: 'Settings updated successfully',
      settings: updatedSettings
    });

  } catch (error) {
    console.error('Update settings error:', error);
    return createErrorResponse(res, 'Failed to update settings', 500);
  }
});

// Get user statistics
router.get('/stats', async (req, res) => {
  try {
    const userId = req.user.id;

    // TODO: Get user statistics from database
    const stats = {
      totalVideos: 15,
      totalAnalyses: 12,
      totalHighlights: 8,
      storageUsed: '2.5 GB',
      storageLimit: '10 GB',
      lastUpload: new Date(Date.now() - 24 * 60 * 60 * 1000)
    };

    return createSuccessResponse(res, { stats });

  } catch (error) {
    console.error('Get stats error:', error);
    return createErrorResponse(res, 'Failed to get statistics', 500);
  }
});

// Delete user account
router.delete('/account', async (req, res) => {
  try {
    const userId = req.user.id;

    // TODO: Delete user account and all associated data
    // TODO: Clean up storage

    return createSuccessResponse(res, {
      success: true,
      message: 'Account deleted successfully'
    });

  } catch (error) {
    console.error('Delete account error:', error);
    return createErrorResponse(res, 'Failed to delete account', 500);
  }
});

module.exports = router; 