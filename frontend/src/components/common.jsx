import { Fragment } from 'react'

// Small shared presentational pieces.

export function StatusBadge({ status }) {
  return <span className={`badge ${status}`}>{status}</span>
}

export function Score({ value, max = 100 }) {
  const color = value >= 80 ? 'var(--green)' : value >= 50 ? 'var(--amber)' : 'var(--red)'
  return (
    <div>
      <div className="score-big" style={{ color }}>
        {value}
        <small> / {max}</small>
      </div>
      <div className="meter">
        <div style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: color }} />
      </div>
    </div>
  )
}

export function DuplicateNotice({ duplicate }) {
  if (!duplicate?.duplicate) return null
  return (
    <div className="notice warn">
      <strong>Potential duplicate detected</strong>
      Existing lead <span className="mono">{duplicate.duplicate_lead_id}</span>
      {duplicate.similarity != null && <> · similarity {duplicate.similarity}%</>}
      {duplicate.reason && <> · {duplicate.reason}</>}
    </div>
  )
}

// Turns a snake_case rule/project name into readable text.
export function humanize(value) {
  if (!value) return '—'
  return value.replace(/_check$/, '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

export function RuleChecks({ rules }) {
  if (!rules?.length) return <p className="muted">No rule results recorded.</p>
  return (
    <div>
      {rules.map((rule) => (
        <div className="check" key={rule.rule}>
          <span className={`mark ${rule.passed ? 'ok' : 'ko'}`}>{rule.passed ? '✓' : '✗'}</span>
          <span style={{ flex: 1 }}>
            {humanize(rule.rule)}
            <div className="reason">{rule.reason}</div>
          </span>
          <span className="pts">
            {rule.score > 0 ? `+${rule.score}` : rule.score}
            {rule.max_score > 0 ? ` / ${rule.max_score}` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}

export function Timeline({ events }) {
  if (!events?.length) return <p className="muted">No events recorded.</p>
  return (
    <ul className="timeline">
      {events.map((event) => (
        <li key={event.id}>
          <span className="ts">{new Date(event.created_at).toLocaleTimeString()}</span>
          <span>{event.message}</span>
        </li>
      ))}
    </ul>
  )
}

// The per-vertical extracted fields. Rendered generically so a new vertical
// needs no frontend change: the backend decides what is worth showing.
export function AiDetails({ details }) {
  const entries = Object.entries(details || {}).filter(
    ([, value]) => value !== null && value !== undefined && value !== '',
  )
  if (entries.length === 0) return null

  return (
    <>
      <div className="muted" style={{ fontSize: 12, margin: '14px 0 6px' }}>
        Vertical-specific fields
      </div>
      <dl className="kv">
        {entries.map(([key, value]) => (
          <Fragment key={key}>
            <dt>{humanize(key)}</dt>
            <dd>{typeof value === 'boolean' ? (value ? 'yes' : 'no') : humanize(String(value))}</dd>
          </Fragment>
        ))}
      </dl>
    </>
  )
}

export function ErrorNotice({ error }) {
  if (!error) return null
  return (
    <div className="notice error">
      <strong>Something went wrong</strong>
      {String(error)}
    </div>
  )
}
