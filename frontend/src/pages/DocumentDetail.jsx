import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { getDocument, validateDocument, reprocessDocument, askQuestion } from '../services/api';

function makeValidationKey(fieldName, fieldValue) {
  return `${fieldName}::${fieldValue || ''}`;
}

export default function DocumentDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [validations, setValidations] = useState(null);
  const [loading, setLoading] = useState(true);
  const [question, setQuestion] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    let active = true;
    let intervalId = null;

    const load = async (showSpinner = false) => {
      if (showSpinner) setLoading(true);
      try {
        const res = await getDocument(id);
        if (!active) return;
        setData(res.data);

        const status = res.data?.document?.status;
        if ((status === 'completed' || status === 'review_needed') && !validations) {
          try {
            const validationRes = await validateDocument(id);
            if (active) setValidations(validationRes.data);
          } catch (_) {
          }
        }
        const shouldPoll = status === 'uploaded' || status === 'processing';
        if (shouldPoll && !intervalId) {
          intervalId = window.setInterval(() => load(false), 3000);
        }
        if (!shouldPoll && intervalId) {
          window.clearInterval(intervalId);
          intervalId = null;
        }
      } catch (_) {
      } finally {
        if (showSpinner && active) setLoading(false);
      }
    };

    load(true);

    return () => {
      active = false;
      if (intervalId) window.clearInterval(intervalId);
    };
  }, [id]);

  const handleValidate = async () => {
    const res = await validateDocument(id);
    setValidations(res.data);
  };

  const handleReprocess = async () => {
    await reprocessDocument(id);
    setTimeout(() => window.location.reload(), 2000);
  };

  const handleAsk = async (e) => {
    e.preventDefault();
    if (!question.trim() || asking) return;
    const q = question.trim();
    setChatHistory(prev => [...prev, { type: 'question', text: q }]);
    setQuestion('');
    setAsking(true);
    try {
      const res = await askQuestion(id, q);
      setChatHistory(prev => [...prev, {
        type: 'answer',
        text: res.data.answer,
        confidence: res.data.confidence,
        context: res.data.context_snippet,
        error: res.data.error,
      }]);
    } catch (err) {
      setChatHistory(prev => [...prev, {
        type: 'answer',
        text: 'Failed to get answer. Please try again.',
        error: true,
      }]);
    } finally {
      setAsking(false);
    }
  };

  if (loading) return <div className="loading">Loading...</div>;
  if (!data) return <div className="error">Document not found</div>;

  const { document: doc, extractions, processing_logs: processingLogs = [] } = data;
  const validationMap = new Map(
    (validations || []).map((v) => [makeValidationKey(v.field_name, v.extracted_value), v])
  );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2>{doc.original_filename}</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary" onClick={handleReprocess}>🔄 Reprocess</button>
          <button className="btn btn-primary" onClick={handleValidate}>✅ Validate</button>
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card"><div className="label">Type</div><div className="value" style={{ fontSize: 18 }}>{doc.doc_type}</div></div>
        <div className="stat-card"><div className="label">Status</div><div className="value" style={{ fontSize: 18 }}><StatusBadge status={doc.status} /></div></div>
        <div className="stat-card"><div className="label">Pages</div><div className="value">{doc.page_count}</div></div>
        <div className="stat-card"><div className="label">Processing Time</div><div className="value" style={{ fontSize: 18 }}>{doc.processing_time_ms ? `${doc.processing_time_ms}ms` : '—'}</div></div>
      </div>

      {/* Q&A Section */}
      <div className="card">
        <h2>💬 Ask a Question</h2>
        <div style={{ maxHeight: 400, overflowY: 'auto', marginBottom: 12, padding: '8px 0' }}>
          {chatHistory.length === 0 && (
            <p style={{ color: '#999', fontSize: 14 }}>Ask anything about this document — e.g. "What are the key terms?" or "Who are the parties involved?"</p>
          )}
          {chatHistory.map((msg, i) => (
            <div key={i} style={{
              display: 'flex',
              justifyContent: msg.type === 'question' ? 'flex-end' : 'flex-start',
              marginBottom: 8,
            }}>
              <div style={{
                maxWidth: '80%',
                padding: '10px 14px',
                borderRadius: 12,
                background: msg.type === 'question' ? '#7c83ff' : '#f0f0f0',
                color: msg.type === 'question' ? '#fff' : '#1a1a2e',
                fontSize: 14,
              }}>
                <div>{msg.text}</div>
                {msg.type === 'answer' && msg.confidence != null && msg.confidence > 0 && (
                  <div style={{ fontSize: 11, marginTop: 6, opacity: 0.7 }}>
                    Confidence: {(msg.confidence * 100).toFixed(1)}%
                  </div>
                )}
                {msg.type === 'answer' && msg.context && (
                  <div style={{
                    fontSize: 12, marginTop: 8, padding: 8,
                    background: 'rgba(0,0,0,0.05)', borderRadius: 6,
                    fontStyle: 'italic', lineHeight: 1.4,
                  }}>
                    "...{msg.context}..."
                  </div>
                )}
              </div>
            </div>
          ))}
          {asking && (
            <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: 8 }}>
              <div style={{ padding: '10px 14px', borderRadius: 12, background: '#f0f0f0', fontSize: 14, color: '#666' }}>
                ⏳ Thinking...
              </div>
            </div>
          )}
        </div>
        <form onSubmit={handleAsk} className="search-bar">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about this document..."
            disabled={asking}
          />
          <button type="submit" className="btn btn-primary" disabled={asking || !question.trim()}>
            Ask
          </button>
        </form>
      </div>

      {/* Extractions */}
      <div className="card">
        <h2>Extracted Fields ({extractions.length})</h2>
        {extractions.length === 0 ? (
          <p style={{ color: '#666' }}>No extractions yet. Document may still be processing.</p>
        ) : (
          <div className="extraction-grid">
            {extractions.map(ext => {
              const validation = validationMap.get(makeValidationKey(ext.field_name, ext.field_value));
              const reviewMessage = ext.needs_review
                ? (validation?.message || 'This field was flagged for manual review.')
                : null;

              return (
              <div key={ext.id} className="extraction-item" style={{ borderColor: ext.needs_review ? '#ffc107' : '#eee' }}>
                <div className="field-name">
                  {ext.field_name}
                  {ext.needs_review ? ' ⚠️' : ''}
                </div>
                <div className="field-value">{ext.field_value || '—'}</div>
                {reviewMessage && (
                  <div style={{
                    marginTop: 8,
                    padding: '8px 10px',
                    borderRadius: 8,
                    background: '#fff8e1',
                    color: '#8a6d1d',
                    fontSize: 12,
                    lineHeight: 1.4,
                  }}>
                    {reviewMessage}
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12, color: '#666' }}>
                  <span>Source: {ext.source}</span>
                  <span>
                    <ConfidenceBar value={ext.confidence} /> {(ext.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            )})}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Processing Logs</h2>
        {processingLogs.length === 0 ? (
          <p style={{ color: '#666' }}>No processing logs yet.</p>
        ) : (
          <div style={{
            maxHeight: 360,
            overflowY: 'auto',
            background: '#111827',
            borderRadius: 12,
            padding: 12,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            fontSize: 12,
            color: '#e5e7eb',
          }}>
            {processingLogs.map((log) => (
              <div key={log.id} style={{
                display: 'grid',
                gridTemplateColumns: '120px 110px 1fr',
                gap: 12,
                padding: '6px 0',
                borderBottom: '1px solid rgba(255,255,255,0.08)',
              }}>
                <span style={{ color: '#93c5fd' }}>{new Date(log.created_at).toLocaleTimeString()}</span>
                <span style={{ color: log.level === 'error' ? '#fca5a5' : log.level === 'warning' ? '#fde68a' : '#86efac' }}>
                  [{log.step}]
                </span>
                <span>{log.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Validation Results */}
      {validations && (
        <div className="card">
          <h2>Validation Results</h2>
          <table>
            <thead><tr><th>Field</th><th>Value</th><th>Status</th><th>Message</th></tr></thead>
            <tbody>
              {validations.map((v, i) => (
                <tr key={i}>
                  <td>{v.field_name}</td>
                  <td>{v.extracted_value}</td>
                  <td>{v.is_valid ? <span className="badge badge-green">Valid</span> : <span className="badge badge-red">Invalid</span>}</td>
                  <td>{v.message}</td>
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

function ConfidenceBar({ value }) {
  const cls = value >= 0.8 ? 'fill-high' : value >= 0.5 ? 'fill-medium' : 'fill-low';
  return (
    <span className="confidence-bar">
      <span className={`fill ${cls}`} style={{ width: `${value * 100}%` }} />
    </span>
  );
}
