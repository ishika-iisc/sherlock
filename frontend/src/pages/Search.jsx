import React, { useState } from 'react';
import { searchDocuments, askAllDocuments } from '../services/api';
import { useNavigate } from 'react-router-dom';

export default function Search() {
  const [query, setQuery] = useState('');
  const [docType, setDocType] = useState('');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState('search'); // 'search' or 'ask'
  const [qaResults, setQaResults] = useState(null);
  const [qaLoading, setQaLoading] = useState(false);
  const navigate = useNavigate();

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;

    if (mode === 'ask') {
      setQaLoading(true);
      setQaResults(null);
      try {
        const res = await askAllDocuments(query);
        setQaResults(res.data);
      } catch {
        setQaResults([{ answer: 'Failed to get answer.', confidence: 0, error: 'failed' }]);
      } finally {
        setQaLoading(false);
      }
    } else {
      setLoading(true);
      setResults(null);
      try {
        const res = await searchDocuments(query, docType || null);
        setResults(res.data);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>Search & Ask</h2>

      {/* Mode Toggle */}
      <div className="card" style={{ padding: 16 }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button
            className={`btn ${mode === 'search' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => { setMode('search'); setQaResults(null); }}
          >
            🔍 Keyword Search
          </button>
          <button
            className={`btn ${mode === 'ask' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => { setMode('ask'); setResults(null); }}
          >
            💬 Ask All Documents
          </button>
        </div>

        <form onSubmit={handleSearch} className="search-bar">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={mode === 'ask'
              ? 'Ask a question across all documents...'
              : 'Search by keyword...'}
          />
          {mode === 'search' && (
            <select value={docType} onChange={(e) => setDocType(e.target.value)}
              style={{ padding: '10px', borderRadius: 8, border: '1px solid #ddd' }}>
              <option value="">All Types</option>
              <option value="invoice">Invoice</option>
              <option value="contract">Contract</option>
              <option value="form">Form</option>
              <option value="report">Report</option>
            </select>
          )}
          <button type="submit" className="btn btn-primary" disabled={loading || qaLoading}>
            {(loading || qaLoading) ? '⏳...' : mode === 'ask' ? '💬 Ask' : '🔍 Search'}
          </button>
        </form>
      </div>

      {/* Q&A Results */}
      {qaResults && (
        <div className="card">
          <h2>Answers from your documents</h2>
          {qaResults.map((r, i) => (
            <div key={i} style={{
              padding: 16, borderBottom: i < qaResults.length - 1 ? '1px solid #eee' : 'none',
            }}>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
                {r.answer}
              </div>
              {r.document_name && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span className="badge badge-blue">📄 {r.document_name}</span>
                  {r.confidence > 0 && (
                    <span style={{ fontSize: 12, color: '#666' }}>
                      Confidence: {(r.confidence * 100).toFixed(1)}%
                    </span>
                  )}
                  {r.document_id && (
                    <button
                      className="btn btn-secondary"
                      style={{ fontSize: 12, padding: '4px 10px' }}
                      onClick={() => navigate(`/documents/${r.document_id}`)}
                    >
                      View Document →
                    </button>
                  )}
                </div>
              )}
              {r.context_snippet && (
                <div style={{
                  fontSize: 13, padding: 10, background: '#f8f9fa',
                  borderRadius: 6, color: '#555', fontStyle: 'italic', lineHeight: 1.5,
                }}>
                  "...{r.context_snippet}..."
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Search Results */}
      {results !== null && (
        <div className="card">
          <h2>Results ({results.length})</h2>
          {results.length === 0 ? (
            <p style={{ color: '#666' }}>No documents matched your query.</p>
          ) : (
            results.map((r, i) => (
              <div key={i}
                style={{ padding: 16, borderBottom: '1px solid #eee', cursor: 'pointer' }}
                onClick={() => navigate(`/documents/${r.document_id}`)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <strong>{r.filename}</strong>
                  <div>
                    <span className="badge badge-blue" style={{ marginRight: 8 }}>{r.doc_type}</span>
                    <span style={{ fontSize: 13, color: '#666' }}>Score: {r.score}</span>
                  </div>
                </div>
                <p style={{ fontSize: 13, color: '#555' }}>{r.snippet}</p>
                {r.extractions?.length > 0 && (
                  <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                    {r.extractions.slice(0, 5).map((ext, j) => (
                      <span key={j} className="badge badge-gray">{ext.field_name}: {ext.field_value}</span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
