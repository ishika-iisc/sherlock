import axios from 'axios';

const api = axios.create({ baseURL: '/api/v1' });

export const uploadDocument = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

export const getDocuments = (params = {}) => api.get('/documents', { params });
export const getDocument = (id) => api.get(`/documents/${id}`);
export const deleteDocument = (id) => api.delete(`/documents/${id}`);
export const reprocessDocument = (id) => api.post(`/documents/${id}/reprocess`);
export const validateDocument = (id) => api.get(`/documents/${id}/validate`);
export const searchDocuments = (query, docType, limit = 10) =>
  api.post('/search', { query, doc_type: docType, limit });
export const getStats = () => api.get('/stats');
export const askQuestion = (id, question) =>
  api.post(`/documents/${id}/ask`, { question });
export const askAllDocuments = (question) =>
  api.post('/ask', { question });
