import React, { useState, useEffect } from 'react';
import { getStats, getDocuments } from '../services/api';

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);

  useEffect(() => {
    getStats().then(r => setStats(r.data)).catch(() => {});
    getDocuments({ limit: 5 }).then(r => setRecent(r.data)).catch(() => {});
  }, []);

  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>Dashboard</h2>
      <div className="stats-grid">
        <StatCard label="Total Documents" value={stats?.total_documents ?? '—'} />
        <StatCard label="Completed" value={stats?.completed ?? '—'} />
        <StatCard label="Needs Review" value={stats?.review_needed ?? '—'} />
        <StatCard label="Avg Processing Time" value={stats?.avg_processing_time_ms ? `${stats.avg_processing_time_ms}ms` : '—'} />
      </div>
      <div className="card">
        <h2>Recent Documents</h2>
        {recent.length === 0 ? (
          <p style={{ color: '#666' }}>No documents yet. Upload one to get started.</p>
        ) : (
          <table>
            <thead><tr><th>Filename</th><th>Type</th><th>Status</th><th>Uploaded</th></tr></thead>
            <tbody>
              {recent.map(doc => (
                <tr key={doc.id}>
                  <td><a href={`/documents/${doc.id}`}>{doc.original_filename}</a></td>
                  <td><span className="badge badge-blue">{doc.doc_type}</span></td>
                  <td><StatusBadge status={doc.status} /></td>
                  <td>{new Date(doc.uploaded_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="stat-card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

function StatusBadge({ status }) {
  const cls = { completed: 'badge-green', processing: 'badge-blue', failed: 'badge-red', review_needed: 'badge-yellow', uploaded: 'badge-gray' };
  return <span className={`badge ${cls[status] || 'badge-gray'}`}>{status}</span>;
}
