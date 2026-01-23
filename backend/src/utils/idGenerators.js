// ID generation utilities

const generateUploadId = () => {
  return `upload-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

const generateAnalysisId = () => {
  return `analysis-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

const generateHighlightId = () => {
  return `highlight-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

const generateUserId = () => {
  return `user-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

const generateJobId = () => {
  return `job-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

const generateSessionId = () => {
  return `session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

module.exports = {
  generateUploadId,
  generateAnalysisId,
  generateHighlightId,
  generateUserId,
  generateJobId,
  generateSessionId
}; 