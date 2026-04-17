import React, { useState, useEffect } from 'react';
import { getDocuments, deleteDocument } from '../services/api';
import { useNavigate } from 'react-router-dom';

export default function Documents() {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = () => {
    setLoading(true);
    getDocuments().then(r => setDocs(r.data)).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    if (!confirm('Delete this document?')) return;
    await deleteDocument(id);
    load();
  };

  if (loading) return <div className="loading">Loading documents...</div>;

  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>Documents</h2>
      {docs.length === 0 ? (
        <div className="card"><p style={{ color: '#666' }}>No documents uploaded yet.</p></div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr><th>Filename</th><th>Type</th><th>Pages</th><th>Status</th><th>Processing Time</th><th>Uploaded</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {docs.map(doc => (
                <tr key={doc.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/documents/${doc.id}`)}>
                  <td>{doc.original_filename}</td>
                  <td><span className="badge badge-blue">{doc.doc_type}</span></td>
                  <td>{doc.page_count}</td>
                  <td><StatusBadge status={doc.status} /></td>
                  <td>{doc.processing_time_ms ? `${doc.processing_time_ms}ms` : '—'}</td>
                  <td>{new Date(doc.uploaded_at).toLocaleDateString()}</td>
                  <td style={{ display: 'flex', gap: 6 }}>
                    {(doc.status === 'completed' || doc.status === 'review_needed') && (
                      <button className="btn btn-primary" style={{ fontSize: 12, padding: '4px 10px' }}
                        onClick={(e) => { e.stopPropagation(); navigate(`/documents/${doc.id}`); }}>
                        💬 Ask
                      </button>
                    )}
                    <button className="btn btn-danger" style={{ fontSize: 12, padding: '4px 10px' }}
                      onClick={(e) => handleDelete(doc.id, e)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  const cls = { completed: 'badge-green', processing: 'badge-blue', failed: 'badge-red', review_needed: 'badge-yellow', uploaded: 'badge-gray' };
  return <span className={`badge ${cls[status] || 'badge-gray'}`}>{status}</span>;
}
