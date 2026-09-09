import { NavLink, Route, Routes } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from './api/client'
import Dashboard from './pages/Dashboard'
import LeadDetail from './pages/LeadDetail'
import NewLead from './pages/NewLead'
import Reviews from './pages/Reviews'
import Crm from './pages/Crm'

export default function App() {
  const [config, setConfig] = useState(null)

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => {})
  }, [])

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <div className="brand">
            Lead<span>Guard</span>
          </div>
          <div className="tagline">
            AI-assisted Lead Qualification &amp; Routing
            {config && (
              <>
                {' · '}AI provider: <span className="mono">{config.ai_provider}</span>
                {' · '}thresholds {config.qualified_threshold}+ qualified,{' '}
                {config.review_threshold}–{config.qualified_threshold - 1} review
              </>
            )}
          </div>
        </div>
        <nav className="tabs">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Dashboard
          </NavLink>
          <NavLink to="/new" className={({ isActive }) => (isActive ? 'active' : '')}>
            New lead
          </NavLink>
          <NavLink to="/reviews" className={({ isActive }) => (isActive ? 'active' : '')}>
            Review queue
          </NavLink>
          <NavLink to="/crm" className={({ isActive }) => (isActive ? 'active' : '')}>
            CRM
          </NavLink>
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new" element={<NewLead />} />
        <Route path="/reviews" element={<Reviews />} />
        <Route path="/leads/:id" element={<LeadDetail />} />
        <Route path="/crm" element={<Crm />} />
      </Routes>
    </div>
  )
}
