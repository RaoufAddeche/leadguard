import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
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

const EMPTY = {
  firstname: '',
  lastname: '',
  email: '',
  phone: '',
  postal_code: '',
  source: 'google_ads',
  campaign: '',
  project_description: '',
  owner: null,
  budget: '',
  consent: false,
}

const SOURCES = ['google_ads', 'meta_ads', 'partner_form', 'external']
// Labelled by what each one demonstrates, not just by name.
const PERSONA_LABELS = {
  thomas: 'Thomas — heat pump, excellent',
  laura: 'Laura — solar, incomplete',
  marco: 'Marco — no vertical, poor',
  helene: 'Hélène — hearing aid, excellent',
  bernard: 'Bernard — hearing aid, enquiring for a relative',
  sylvie: 'Sylvie — IT B2B, decision-maker',
  kevin: 'Kevin — IT B2B, no authority',
}

export default function NewLead() {
  const [form, setForm] = useState(EMPTY)
  const [personas, setPersonas] = useState({})
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  // Personas come from the backend so both sides quote the same payloads.
  useEffect(() => {
    api.getConfig().then((c) => setPersonas(c.personas || {})).catch(() => {})
  }, [])

  function set(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  function prefill(key) {
    const persona = personas[key]
    if (!persona) return
    setForm({ ...EMPTY, ...persona, budget: persona.budget ?? '' })
    setResult(null)
    setError(null)
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const payload = {
        ...form,
        // Empty string means "not provided", which is not the same as zero.
        budget: form.budget === '' ? null : Number(form.budget),
      }
      setResult(await api.createLead(payload))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <ErrorNotice error={error} />

      <div className="grid cols-2">
        <div className="panel">
          <h2>Create a lead</h2>

          {Object.keys(personas).length > 0 && (
            <div style={{ marginBottom: 18 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 7 }}>
                Prefill a demo scenario:
              </div>
              <div className="btn-row">
                {Object.keys(personas).map((key) => (
                  <button type="button" className="chip" key={key} onClick={() => prefill(key)}>
                    {PERSONA_LABELS[key] || humanize(key)}
                  </button>
                ))}
                <button type="button" className="chip" onClick={() => setForm(EMPTY)}>
                  Clear
                </button>
              </div>
            </div>
          )}

          <form onSubmit={submit}>
            <div className="grid cols-2" style={{ gap: 0, columnGap: 14 }}>
              <div className="field">
                <label htmlFor="firstname">First name *</label>
                <input id="firstname" type="text" required value={form.firstname}
                  onChange={(e) => set('firstname', e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="lastname">Last name *</label>
                <input id="lastname" type="text" required value={form.lastname}
                  onChange={(e) => set('lastname', e.target.value)} />
              </div>
            </div>

            <div className="field">
              <label htmlFor="email">Email *</label>
              <input id="email" type="email" required value={form.email}
                onChange={(e) => set('email', e.target.value)} />
            </div>

            <div className="grid cols-2" style={{ gap: 0, columnGap: 14 }}>
              <div className="field">
                <label htmlFor="phone">Phone *</label>
                <input id="phone" type="text" required value={form.phone}
                  onChange={(e) => set('phone', e.target.value)} placeholder="0612345678" />
              </div>
              <div className="field">
                <label htmlFor="postal_code">Postal code *</label>
                <input id="postal_code" type="text" required value={form.postal_code}
                  onChange={(e) => set('postal_code', e.target.value)} placeholder="69003" />
              </div>
            </div>

            <div className="grid cols-2" style={{ gap: 0, columnGap: 14 }}>
              <div className="field">
                <label htmlFor="source">Source *</label>
                <select id="source" value={form.source} onChange={(e) => set('source', e.target.value)}>
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>{humanize(s)}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="campaign">Campaign *</label>
                <input id="campaign" type="text" required value={form.campaign}
                  onChange={(e) => set('campaign', e.target.value)} placeholder="PAC_Lyon" />
              </div>
            </div>

            <div className="field">
              <label htmlFor="project_description">Project description *</label>
              <textarea id="project_description" required value={form.project_description}
                onChange={(e) => set('project_description', e.target.value)}
                placeholder="Describe the project in free text — this is what the AI extracts from." />
            </div>

            <div className="grid cols-2" style={{ gap: 0, columnGap: 14 }}>
              <div className="field">
                <label htmlFor="owner">Property owner</label>
                <select id="owner" value={form.owner === null ? '' : String(form.owner)}
                  onChange={(e) => set('owner', e.target.value === '' ? null : e.target.value === 'true')}>
                  <option value="">not provided</option>
                  <option value="true">yes</option>
                  <option value="false">no</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="budget">Budget (€)</label>
                <input id="budget" type="number" min="0" value={form.budget}
                  onChange={(e) => set('budget', e.target.value)} placeholder="12000" />
              </div>
            </div>

            <div className="field checkbox">
              <input id="consent" type="checkbox" checked={form.consent}
                onChange={(e) => set('consent', e.target.checked)} />
              <label htmlFor="consent">Marketing consent granted (GDPR)</label>
            </div>

            <button type="submit" className="primary" disabled={busy}>
              {busy ? 'Qualifying…' : 'Submit & qualify'}
            </button>
          </form>
        </div>

        <div>
          {!result && (
            <div className="panel">
              <h2>Result</h2>
              <p className="muted" style={{ marginTop: 0 }}>
                Submit a lead to run the full pipeline: validation → consent → duplicate check →
                AI extraction → business rules → scoring → decision → routing → CRM.
              </p>
            </div>
          )}

          {result && (
            <>
              <div className="panel">
                <div className="row-between">
                  <h2 style={{ margin: 0 }}>Result</h2>
                  <span className="mono muted">{result.public_id}</span>
                </div>
                <div style={{ marginTop: 14 }}>
                  <DuplicateNotice duplicate={result.duplicate} />
                  <div className="row-between">
                    <Score value={result.score} />
                    <div style={{ textAlign: 'right' }}>
                      <StatusBadge status={result.status} />
                      <div className="muted" style={{ fontSize: 12.5, marginTop: 7 }}>
                        {humanize(result.vertical)}
                      </div>
                      <div className="muted" style={{ fontSize: 12.5 }}>
                        {result.team ? `Destination: ${result.team}` : 'Not routed'}
                      </div>
                      <div className="muted" style={{ fontSize: 12.5 }}>
                        CRM: {result.crm_status}
                      </div>
                    </div>
                  </div>
                  <div className="btn-row" style={{ marginTop: 18 }}>
                    <button className="primary" onClick={() => navigate(`/leads/${result.lead_id}`)}>
                      Open lead detail
                    </button>
                    <Link to="/"><button>Dashboard</button></Link>
                  </div>
                </div>
              </div>

              {result.ai_analysis && (
                <div className="panel">
                  <h2>AI analysis</h2>
                  <p style={{ marginTop: 0 }}>{result.ai_analysis.summary}</p>
                  <dl className="kv">
                    <dt>Project type</dt><dd>{humanize(result.ai_analysis.project_type)}</dd>
                    <dt>Location</dt><dd>{result.ai_analysis.location || '—'}</dd>
                    <dt>Urgency</dt><dd>{result.ai_analysis.urgency}</dd>
                    <dt>Purchase intent</dt><dd>{result.ai_analysis.purchase_intent}</dd>
                  </dl>
                  <AiDetails details={result.ai_analysis.details} />
                </div>
              )}

              <div className="panel">
                <h2>Checks</h2>
                <RuleChecks rules={result.rule_results} />
              </div>

              <div className="panel">
                <h2>Pipeline trace</h2>
                <Timeline events={result.events} />
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}
