// Response helper functions for consistent API responses

const createSuccessResponse = (res, data, status = 200) => {
  return res.status(status).json({
    success: true,
    ...data
  });
};

const createErrorResponse = (res, error, status = 500, details = null) => {
  const response = {
    success: false,
    error: error
  };

  if (details) {
    response.details = details;
  }

  return res.status(status).json(response);
};

const createPaginatedResponse = (res, data, pagination) => {
  return res.status(200).json({
    success: true,
    data,
    pagination: {
      page: pagination.page,
      limit: pagination.limit,
      total: pagination.total,
      pages: Math.ceil(pagination.total / pagination.limit)
    }
  });
};

module.exports = {
  createSuccessResponse,
  createErrorResponse,
  createPaginatedResponse
}; 