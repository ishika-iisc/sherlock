import React, { useState, useRef } from 'react';
import { uploadDocument } from '../services/api';
import { useNavigate } from 'react-router-dom';

export default function Upload() {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const fileRef = useRef();
  const navigate = useNavigate();

  const handleFile = async (file) => {
    setError(null);
    setSuccess(null);
    setUploading(true);
    try {
      const res = await uploadDocument(file);
      setSuccess(`Uploaded "${file.name}" — processing started.`);
      setTimeout(() => navigate(`/documents/${res.data.id}`), 1500);
    } catch (e) {
      setError(e.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>Upload Document</h2>
      <div className="card">
        <div
          className={`upload-zone ${dragging ? 'dragging' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".pdf,.png,.jpg,.jpeg,.tiff,.docx"
            onChange={(e) => e.target.files[0] && handleFile(e.target.files[0])}
          />
          {uploading ? (
            <p>⏳ Uploading...</p>
          ) : (
            <>
              <p style={{ fontSize: 36, marginBottom: 8 }}>📄</p>
              <p style={{ fontSize: 16, fontWeight: 500 }}>Drop a document here or click to browse</p>
              <p style={{ fontSize: 13, color: '#666', marginTop: 8 }}>
                Supports PDF, PNG, JPG, TIFF, DOCX (max 50MB)
              </p>
            </>
          )}
        </div>
        {error && <div className="error" style={{ marginTop: 16 }}>{error}</div>}
        {success && <div className="badge badge-green" style={{ marginTop: 16, padding: 12, fontSize: 14 }}>{success}</div>}
      </div>
    </div>
  );
}
