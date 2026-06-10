import React, { useState } from 'react';
import { BrainCircuit, FileText, Gauge, Route, SearchCheck, Sparkles } from 'lucide-react';
import { askAgenticRag } from '../services/api';

const examples = [
  'What is the contract number?',
  'Find risky obligations in the uploaded documents',
  'Compare payment terms across documents',
  'Summarize the key parties, dates, and obligations',
];

export default function AgenticRAG() {
  const [question, setQuestion] = useState('');
  const [maxEvidence, setMaxEvidence] = useState(6);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const runAgenticRag = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await askAgenticRag({ question, max_evidence: maxEvidence });
      setResult(res.data);
    } catch (err) {
      setResult({
        answer: 'Agentic RAG failed to complete the request.',
        intent: 'error',
        confidence: 0,
        evidence: [],
        steps: [],
        latency_ms: 0,
        error: err?.message || 'request_failed',
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="section-heading">
        <div>
          <h2>Agentic RAG</h2>
          <p className="section-subtitle">Plan, retrieve, grade evidence, answer, cite.</p>
        </div>
      </div>

      <div className="agent-shell">
        <section className="agent-panel">
          <div className="agent-panel-title">
            <BrainCircuit size={18} />
            <span>Question</span>
          </div>
          <form onSubmit={runAgenticRag}>
            <textarea
              className="agent-textarea"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask across your indexed documents..."
            />
            <div className="agent-controls">
              <label>
                Evidence
                <input
                  type="number"
                  min="2"
                  max="10"
                  value={maxEvidence}
                  onChange={(e) => setMaxEvidence(Number(e.target.value))}
                />
              </label>
              <button type="submit" className="btn btn-primary" disabled={loading}>
                <Sparkles size={16} />
                {loading ? 'Thinking...' : 'Run'}
              </button>
            </div>
          </form>
          <div className="agent-examples">
            {examples.map((item) => (
              <button key={item} type="button" onClick={() => setQuestion(item)}>
                {item}
              </button>
            ))}
          </div>
        </section>

        <section className="agent-panel agent-output">
          {!result && !loading && (
            <div className="agent-empty">
              <SearchCheck size={22} />
              <span>Ready</span>
            </div>
          )}
          {loading && <div className="loading">Running agentic retrieval...</div>}
          {result && (
            <>
              <div className="agent-result-header">
                <span className="badge badge-blue">
                  <Route size={12} /> {result.intent}
                </span>
                <span className="badge badge-gray">
                  <Gauge size={12} /> {(Number(result.confidence || 0) * 100).toFixed(1)}%
                </span>
                <span className="badge badge-gray">{result.latency_ms} ms</span>
              </div>
              <div className="agent-answer">{result.answer}</div>
              {result.error && <div className="error">{result.error}</div>}
            </>
          )}
        </section>
      </div>

      {result?.evidence?.length > 0 && (
        <div className="agent-grid">
          <section className="agent-panel">
            <div className="agent-panel-title">
              <FileText size={18} />
              <span>Evidence</span>
            </div>
            <div className="evidence-list">
              {result.evidence.map((item) => (
                <article key={`${item.document_id}-${item.rank}`} className="evidence-item">
                  <div className="evidence-meta">
                    <strong>{item.document_name || 'Document'}</strong>
                    <span>{(item.score * 100).toFixed(1)}%</span>
                  </div>
                  <p>{item.snippet}</p>
                  {item.evidence_reason && (
                    <div className="evidence-reason">{item.evidence_reason}</div>
                  )}
                  <div className="evidence-tags">
                    <span>{item.source}</span>
                    {item.clause_type && <span>{item.clause_type}</span>}
                    {item.matched_query && <span>{item.matched_query}</span>}
                    {item.matched_terms?.map((term) => (
                      <span key={`${item.rank}-${term}`}>{term}</span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="agent-panel">
            <div className="agent-panel-title">
              <BrainCircuit size={18} />
              <span>Trace</span>
            </div>
            <div className="trace-list">
              {result.steps.map((step, index) => (
                <div key={`${step.name}-${index}`} className="trace-item">
                  <span>{index + 1}</span>
                  <div>
                    <strong>{step.name}</strong>
                    <p>{step.detail}</p>
                  </div>
                  <em>{step.status}</em>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
