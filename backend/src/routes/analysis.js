const express = require('express');
const { body, validationResult } = require('express-validator');
const { createErrorResponse, createSuccessResponse } = require('../utils/responseHelpers');
const { generateAnalysisId } = require('../utils/idGenerators');
const { startAnalysisJob, getAnalysisStatus } = require('../services/analysisService');
const router = express.Router();

// Start video analysis
router.post('/process', 
  [
    body('uploadId').notEmpty().withMessage('Upload ID is required'),
    body('detectionSettings').isObject().withMessage('Detection settings must be an object'),
    body('detectionSettings.useYOLO').isBoolean().withMessage('useYOLO must be a boolean'),
    body('detectionSettings.useMediaPipe').isBoolean().withMessage('useMediaPipe must be a boolean'),
    body('detectionSettings.useDeepFace').isBoolean().withMessage('useDeepFace must be a boolean'),
    body('detectionSettings.useOSNet').isBoolean().withMessage('useOSNet must be a boolean'),
    body('detectionSettings.confidenceThreshold').isFloat({ min: 0.1, max: 1 }).withMessage('Confidence threshold must be between 0.1 and 1'),
    body('playerImages').optional().isObject().withMessage('Player images must be an object'),
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

      const { uploadId, detectionSettings, playerImages } = req.body;
      const userId = req.user.id;

      // TODO: Verify upload exists and belongs to user
      // TODO: Check if upload is ready for analysis

      // Generate analysis ID
      const analysisId = generateAnalysisId();

      // Start analysis job
      const analysisJob = await startAnalysisJob({
        analysisId,
        uploadId,
        userId,
        detectionSettings,
        playerImages
      });

      return createSuccessResponse(res, {
        success: true,
        message: 'Analysis started successfully',
        analysisId,
        status: 'processing',
        estimatedTime: '5-10 minutes',
        uploadId,
        detectionSettings
      });

    } catch (error) {
      console.error('Analysis start error:', error);
      return createErrorResponse(res, 'Failed to start analysis', 500);
    }
  }
);

// Get analysis status
router.get('/status/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const userId = req.user.id;

    // TODO: Verify analysis belongs to user
    const status = await getAnalysisStatus(id, userId);

    if (!status) {
      return createErrorResponse(res, 'Analysis not found', 404);
    }

    return createSuccessResponse(res, status);

  } catch (error) {
    console.error('Status check error:', error);
    return createErrorResponse(res, 'Failed to get analysis status', 500);
  }
});

// Get analysis results
router.get('/results/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const userId = req.user.id;

    // TODO: Get analysis results from database
    const results = {
      analysisId: id,
      status: 'completed',
      results: {
        detections: [],
        poses: [],
        faces: [],
        tracks: [],
        metadata: {
          frameCount: 0,
          duration: 0,
          resolution: '1920x1080'
        }
      },
      completedAt: new Date()
    };

    return createSuccessResponse(res, results);

  } catch (error) {
    console.error('Results fetch error:', error);
    return createErrorResponse(res, 'Failed to get analysis results', 500);
  }
});

// Cancel analysis
router.delete('/cancel/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const userId = req.user.id;

    // TODO: Cancel analysis job
    // TODO: Update database status

    return createSuccessResponse(res, {
      success: true,
      message: 'Analysis cancelled successfully',
      analysisId: id
    });

  } catch (error) {
    console.error('Cancel analysis error:', error);
    return createErrorResponse(res, 'Failed to cancel analysis', 500);
  }
});

// Get user's analyses
router.get('/list', async (req, res) => {
  try {
    const userId = req.user.id;
    const { page = 1, limit = 10, status } = req.query;

    // TODO: Get analyses from database with pagination
    const analyses = {
      analyses: [],
      pagination: {
        page: parseInt(page),
        limit: parseInt(limit),
        total: 0,
        pages: 0
      }
    };

    return createSuccessResponse(res, analyses);

  } catch (error) {
    console.error('List analyses error:', error);
    return createErrorResponse(res, 'Failed to get analyses', 500);
  }
});

module.exports = router; 