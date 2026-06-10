import React, { useState, useEffect } from 'react';
import { getStats, getDocuments, getEvaluationMetrics } from '../services/api';

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [evaluationMetrics, setEvaluationMetrics] = useState([]);
  const [benchmarkAvailable, setBenchmarkAvailable] = useState(false);

  useEffect(() => {
    getStats().then(r => setStats(r.data)).catch(() => {});
    getDocuments({ limit: 5 }).then(r => setRecent(r.data)).catch(() => {});
    getEvaluationMetrics().then(r => {
      setEvaluationMetrics(r.data.metrics || []);
      setBenchmarkAvailable(Boolean(r.data.benchmark_available));
    }).catch(() => {});
  }, []);

  const implementedMetrics = evaluationMetrics.filter((metric) => metric.category !== 'planned');
  const plannedMetrics = evaluationMetrics.filter((metric) => metric.category === 'planned');

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
        <div className="section-heading">
          <div>
            <h2>Evaluation Metrics</h2>
            <p className="section-subtitle">
              Research metrics for benchmarking extraction accuracy, retrieval quality, question-answering performance, and system efficiency.
            </p>
          </div>
          <span className="badge badge-gray">{benchmarkAvailable ? 'Benchmark Dataset Loaded' : 'Benchmark Dataset Missing'}</span>
        </div>
        <div style={{ marginBottom: 18 }}>
          <h3 style={{ margin: '0 0 10px 0', fontSize: 16 }}>Currently Available in App</h3>
          <div className="evaluation-grid">
            {implementedMetrics.map((metric) => (
              <MetricCard key={metric.key} metric={metric} />
            ))}
          </div>
        </div>
        {plannedMetrics.length > 0 && (
          <div>
            <h3 style={{ margin: '0 0 10px 0', fontSize: 16 }}>Planned Next</h3>
            <div className="evaluation-grid">
              {plannedMetrics.map((metric) => (
                <MetricCard key={metric.key} metric={metric} />
              ))}
            </div>
          </div>
        )}
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

function MetricCard({ metric }) {
  return (
    <div className="evaluation-card">
      <div className="evaluation-label">{metric.label}</div>
      <div className="evaluation-value">{metric.display_value}</div>
      <div className={`evaluation-status status-${metric.status}`}>{metric.status}</div>
      <p className="evaluation-detail">{metric.description}</p>
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
