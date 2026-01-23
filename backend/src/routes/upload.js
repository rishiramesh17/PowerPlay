const express = require('express');
const multer = require('multer');
const { body, validationResult } = require('express-validator');
const { uploadToS3, generatePresignedUrl } = require('../services/s3Service');
const { validateVideoFile, validateImageFile } = require('../utils/fileValidation');
const { createErrorResponse, createSuccessResponse } = require('../utils/responseHelpers');
const { generateUploadId } = require('../utils/idGenerators');
const router = express.Router();

// Configure multer for memory storage
const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 500 * 1024 * 1024, // 500MB
  }
});

// Upload video endpoint
router.post('/video', 
  upload.single('file'),
  [
    body('sport').notEmpty().withMessage('Sport is required'),
    body('title').notEmpty().withMessage('Title is required'),
    body('description').optional().isString(),
  ],
  async (req, res) => {
    try {
      // Check for validation errors
      const errors = validationResult(req);
      if (!errors.isEmpty()) {
        return res.status(400).json({
          error: 'Validation failed',
          details: errors.array()
        });
      }

      const { sport, title, description } = req.body;
      const file = req.file;

      // Validate file
      if (!file) {
        return createErrorResponse(res, 'No file provided', 400);
      }

      const fileValidation = validateVideoFile(file);
      if (!fileValidation.valid) {
        return createErrorResponse(res, fileValidation.error, 400);
      }

      // Generate upload ID
      const uploadId = generateUploadId();
      
      // Upload to S3
      const s3Result = await uploadToS3(file.buffer, `videos/${uploadId}/${file.originalname}`, file.mimetype);
      
      // TODO: Save to database
      const videoData = {
        id: uploadId,
        userId: req.user.id, // From auth middleware
        title,
        description,
        sport,
        filename: file.originalname,
        fileSize: file.size,
        fileUrl: s3Result.url,
        status: 'uploaded',
        createdAt: new Date()
      };

      return createSuccessResponse(res, {
        success: true,
        message: 'Video uploaded successfully',
        uploadId,
        filename: file.originalname,
        size: file.size,
        type: file.mimetype,
        url: s3Result.url
      });

    } catch (error) {
      console.error('Video upload error:', error);
      return createErrorResponse(res, 'Upload failed', 500);
    }
  }
);

// Upload player images endpoint
router.post('/player-images',
  upload.array('images', 10), // Max 10 images
  [
    body('playerId').notEmpty().withMessage('Player ID is required'),
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

      const { playerId } = req.body;
      const files = req.files;

      if (!files || files.length === 0) {
        return createErrorResponse(res, 'No images provided', 400);
      }

      const uploadedImages = [];

      for (const file of files) {
        const fileValidation = validateImageFile(file);
        if (!fileValidation.valid) {
          return createErrorResponse(res, fileValidation.error, 400);
        }

        const imageId = `img-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        const s3Result = await uploadToS3(
          file.buffer, 
          `player-images/${playerId}/${imageId}/${file.originalname}`, 
          file.mimetype
        );

        uploadedImages.push({
          id: imageId,
          filename: file.originalname,
          url: s3Result.url,
          size: file.size
        });
      }

      // TODO: Save to database
      return createSuccessResponse(res, {
        success: true,
        message: 'Player images uploaded successfully',
        playerId,
        images: uploadedImages
      });

    } catch (error) {
      console.error('Player images upload error:', error);
      return createErrorResponse(res, 'Upload failed', 500);
    }
  }
);

// Get upload status
router.get('/status/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const userId = req.user.id;

    // TODO: Get from database
    const uploadStatus = {
      uploadId: id,
      status: 'uploaded',
      progress: 100,
      message: 'Upload completed'
    };

    return createSuccessResponse(res, uploadStatus);

  } catch (error) {
    console.error('Status check error:', error);
    return createErrorResponse(res, 'Failed to get status', 500);
  }
});

// Get presigned URL for direct upload
router.post('/presigned-url', async (req, res) => {
  try {
    const { filename, contentType } = req.body;
    const userId = req.user.id;

    if (!filename || !contentType) {
      return createErrorResponse(res, 'Filename and content type are required', 400);
    }

    const uploadId = generateUploadId();
    const key = `videos/${uploadId}/${filename}`;
    const presignedUrl = await generatePresignedUrl(key, 'put', contentType);

    return createSuccessResponse(res, {
      uploadId,
      presignedUrl,
      key,
      expiresIn: 3600 // 1 hour
    });

  } catch (error) {
    console.error('Presigned URL error:', error);
    return createErrorResponse(res, 'Failed to generate presigned URL', 500);
  }
});

module.exports = router; 