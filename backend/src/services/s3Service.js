const AWS = require('aws-sdk');
const { createErrorResponse } = require('../utils/responseHelpers');

// Configure AWS
AWS.config.update({
  accessKeyId: process.env.AWS_ACCESS_KEY_ID,
  secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
  region: process.env.AWS_REGION || 'us-east-1'
});

const s3 = new AWS.S3();
const bucketName = process.env.S3_BUCKET_NAME;

// Upload file to S3
const uploadToS3 = async (buffer, key, contentType) => {
  try {
    const params = {
      Bucket: bucketName,
      Key: key,
      Body: buffer,
      ContentType: contentType,
      ACL: 'private'
    };

    const result = await s3.upload(params).promise();
    
    return {
      key: result.Key,
      url: result.Location,
      bucket: result.Bucket,
      etag: result.ETag
    };
  } catch (error) {
    console.error('S3 upload error:', error);
    throw new Error('Failed to upload file to S3');
  }
};

// Generate presigned URL for direct upload
const generatePresignedUrl = async (key, operation = 'put', contentType = 'application/octet-stream') => {
  try {
    const params = {
      Bucket: bucketName,
      Key: key,
      ContentType: contentType,
      Expires: 3600 // 1 hour
    };

    const url = await s3.getSignedUrlPromise(operation, params);
    return url;
  } catch (error) {
    console.error('Presigned URL generation error:', error);
    throw new Error('Failed to generate presigned URL');
  }
};

// Delete file from S3
const deleteFromS3 = async (key) => {
  try {
    const params = {
      Bucket: bucketName,
      Key: key
    };

    await s3.deleteObject(params).promise();
    return true;
  } catch (error) {
    console.error('S3 delete error:', error);
    throw new Error('Failed to delete file from S3');
  }
};

// Get file metadata from S3
const getFileMetadata = async (key) => {
  try {
    const params = {
      Bucket: bucketName,
      Key: key
    };

    const result = await s3.headObject(params).promise();
    return {
      size: result.ContentLength,
      contentType: result.ContentType,
      lastModified: result.LastModified,
      etag: result.ETag
    };
  } catch (error) {
    console.error('S3 metadata error:', error);
    throw new Error('Failed to get file metadata');
  }
};

// List files in a directory
const listFiles = async (prefix) => {
  try {
    const params = {
      Bucket: bucketName,
      Prefix: prefix
    };

    const result = await s3.listObjectsV2(params).promise();
    return result.Contents || [];
  } catch (error) {
    console.error('S3 list error:', error);
    throw new Error('Failed to list files');
  }
};

// Copy file within S3
const copyFile = async (sourceKey, destinationKey) => {
  try {
    const params = {
      Bucket: bucketName,
      CopySource: `${bucketName}/${sourceKey}`,
      Key: destinationKey
    };

    const result = await s3.copyObject(params).promise();
    return {
      key: destinationKey,
      etag: result.CopyObjectResult.ETag
    };
  } catch (error) {
    console.error('S3 copy error:', error);
    throw new Error('Failed to copy file');
  }
};

module.exports = {
  uploadToS3,
  generatePresignedUrl,
  deleteFromS3,
  getFileMetadata,
  listFiles,
  copyFile
}; 