import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import {
  AiDetails,
  DuplicateNotice,
  ErrorNotice,
  RuleChecks,
  Score,
  StatusBadge,
  Timeline,
  humanize,
} from '../components/common'

export default function LeadDetail() {
  const { id } = useParams()
  const [lead, setLead] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState('')

  const load = useCallback(() => {
    api.getLead(id).then(setLead).catch((e) => setError(e.message))
  }, [id])

  useEffect(load, [load])

  async function decide(decision) {
    setBusy(true)
    setError(null)
    try {
      // Re-fetch rather than trusting the local copy: the decision may have
      // triggered routing and a CRM sync server-side.
      await api.reviewLead(id, { decision, reviewer: 'demo-user', reason: reason || null })
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !lead) return <ErrorNotice error={error} />
  if (!lead) return <p className="muted">Loading…</p>

  const needsReview = lead.system_status === 'REVIEW' && !lead.human_status
  const failed = (lead.rule_results || []).filter((r) => !r.passed && r.max_score > 0)

  return (
    <>
      <div className="row-between" style={{ marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, textTransform: 'uppercase', letterSpacing: 0.4 }}>
            {lead.full_name}
          </h1>
          <div className="muted mono">{lead.public_id}</div>
        </div>
        <Link to="/">
          <button>← Back to dashboard</button>
        </Link>
      </div>

      <ErrorNotice error={error} />
      <DuplicateNotice duplicate={lead.duplicate} />

      {lead.crm_status === 'FAILED' && (
        <div className="notice warn">
          <strong>CRM synchronization failed</strong>
          {lead.crm_error} — the lead is retained in LeadGuard and can be re-pushed.
        </div>
      )}

      <div className="grid cols-2">
        <div>
          <div className="panel">
            <h2>Qualification</h2>
            <div className="row-between">
              <Score value={lead.score} />
              <div style={{ textAlign: 'right' }}>
                <StatusBadge status={lead.status} />
                {lead.human_status && (
                  <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                    system decided {lead.system_status}
                  </div>
                )}
              </div>
            </div>
          </div>

          {needsReview && (
            <div className="panel">
              <h2>Human review required</h2>
              <p style={{ marginTop: 0 }}>
                The engine scored this lead in the review band. A human decides.
              </p>
              {failed.length > 0 && (
                <>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                    Reason{failed.length > 1 ? 's' : ''}:
                  </div>
                  <ul style={{ margin: '0 0 14px', paddingLeft: 18 }}>
                    {failed.map((r) => (
                      <li key={r.rule} style={{ fontSize: 13.5 }}>
                        {r.reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <div className="field">
                <label htmlFor="reason">Reviewer note (optional)</label>
                <input
                  id="reason"
                  type="text"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Ownership confirmed by phone"
                />
              </div>
              <div className="btn-row">
                <button className="success" disabled={busy} onClick={() => decide('QUALIFIED')}>
                  QUALIFY
                </button>
                <button className="danger" disabled={busy} onClick={() => decide('REJECTED')}>
                  REJECT
                </button>
              </div>
            </div>
          )}

          {lead.human_status && (
            <div className="panel">
              <h2>Human decision</h2>
              <dl className="kv">
                <dt>System decision</dt>
                <dd>
                  <StatusBadge status={lead.system_status} />
                </dd>
                <dt>Human decision</dt>
                <dd>
                  <StatusBadge status={lead.human_status} />
                </dd>
                <dt>Reviewer</dt>
                <dd>{lead.reviewer}</dd>
                <dt>Reviewed at</dt>
                <dd>{new Date(lead.reviewed_at).toLocaleString()}</dd>
                {lead.review_reason && (
                  <>
                    <dt>Reason</dt>
                    <dd>{lead.review_reason}</dd>
                  </>
                )}
              </dl>
            </div>
          )}

          <div className="panel">
            <h2>Lead information</h2>
            <dl className="kv">
              <dt>Email</dt>
              <dd>{lead.email}</dd>
              <dt>Phone</dt>
              <dd>{lead.phone}</dd>
              <dt>Postal code</dt>
              <dd>{lead.postal_code}</dd>
              <dt>Source</dt>
              <dd>{humanize(lead.source)}</dd>
              <dt>Campaign</dt>
              <dd>{lead.campaign}</dd>
              <dt>Owner</dt>
              <dd>{lead.owner === null ? 'not provided' : lead.owner ? 'yes' : 'no'}</dd>
              <dt>Budget</dt>
              <dd>{lead.budget ? `${lead.budget.toLocaleString()} €` : 'not provided'}</dd>
              <dt>Project</dt>
              <dd>{humanize(lead.project_type)}</dd>
              <dt>Vertical</dt>
              <dd>{humanize(lead.vertical)}</dd>
              <dt>Country</dt>
              <dd>{lead.country}</dd>
            </dl>
          </div>

          <div className="panel">
            <h2>Consent &amp; traceability</h2>
            <dl className="kv">
              <dt>Consent</dt>
              <dd>{lead.consent ? '✓ granted' : '✗ not granted'}</dd>
              <dt>Consent timestamp</dt>
              <dd>
                {lead.consent_timestamp
                  ? new Date(lead.consent_timestamp).toLocaleString()
                  : '—'}
              </dd>
              <dt>SHA-256 fingerprint</dt>
              <dd className="mono" style={{ fontSize: 11 }}>
                {lead.data_fingerprint}
              </dd>
            </dl>
          </div>
        </div>

        <div>
          <div className="panel">
            <h2>AI analysis</h2>
            {lead.ai_analysis ? (
              <>
                <p style={{ marginTop: 0 }}>{lead.ai_analysis.summary}</p>
                <dl className="kv">
                  <dt>Project type</dt>
                  <dd>{humanize(lead.ai_analysis.project_type)}</dd>
                  <dt>Location</dt>
                  <dd>{lead.ai_analysis.location || '—'}</dd>
                  <dt>Property type</dt>
                  <dd>{humanize(lead.ai_analysis.property_type)}</dd>
                  <dt>Owner intent</dt>
                  <dd>
                    {lead.ai_analysis.owner_intent === null
                      ? 'unclear'
                      : lead.ai_analysis.owner_intent
                        ? 'owner'
                        : 'tenant'}
                  </dd>
                  <dt>Urgency</dt>
                  <dd>{lead.ai_analysis.urgency}</dd>
                  <dt>Purchase intent</dt>
                  <dd>{lead.ai_analysis.purchase_intent}</dd>
                  <dt>Provider</dt>
                  <dd className="mono">{lead.ai_provider}</dd>
                </dl>
                <AiDetails details={lead.ai_analysis.details} />
                <div className="notice info" style={{ marginTop: 14, marginBottom: 0 }}>
                  Extraction only. The AI supplies these structured fields; the score and the
                  status below are computed by deterministic business rules.
                </div>
              </>
            ) : (
              <p className="muted">No AI analysis available.</p>
            )}
          </div>

          <div className="panel">
            <h2>
              Checks — universal + {humanize(lead.vertical)} criteria
            </h2>
            <RuleChecks rules={lead.rule_results} />
          </div>

          <div className="panel">
            <h2>Routing &amp; CRM</h2>
            <dl className="kv">
              <dt>Team</dt>
              <dd>{lead.routed_team || 'not routed'}</dd>
              <dt>Reason</dt>
              <dd>{lead.routing_reason || '—'}</dd>
              <dt>CRM status</dt>
              <dd>{lead.crm_status}</dd>
              <dt>CRM reference</dt>
              <dd className="mono">{lead.crm_reference || '—'}</dd>
            </dl>
          </div>

          <div className="panel">
            <h2>Audit trail</h2>
            <Timeline events={lead.events} />
          </div>
        </div>
      </div>
    </>
  )
}
