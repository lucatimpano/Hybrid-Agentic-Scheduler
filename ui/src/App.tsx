import { useState, useRef, useCallback, useEffect } from 'react'
import {
  CheckIcon, LoaderIcon, CircleIcon, CalendarIcon,
  UsersIcon, ChevronDownIcon, RotateCcwIcon, AlertCircleIcon, PlayIcon
} from 'lucide-react'
import './App.css'
import BlurText from './BlurText'

// ─── Types ───────────────────────────────────────────────────────────────────

type AgentId = 'workers' | 'drafting' | 'verification' | 'fairness'
type AgentStatus = 'idle' | 'running' | 'done' | 'error'

interface AgentState {
  id: AgentId
  label: string
  description: string
  status: AgentStatus
  runs: number
  detail?: string
}

interface LogEntry {
  ts: number
  agent: AgentId
  type: 'start' | 'done' | 'error' | 'redirect'
  message: string
}

interface Assignment {
  date: string
  shift: 'Morning' | 'Afternoon' | 'Night'
  worker_id: string
}

interface Schedule { assignments: Assignment[] }

// ─── Mock data ────────────────────────────────────────────────────────────────

function generateMockSchedule(numWorkers: number, numDays: number): Schedule {
  const shifts: Array<'Morning' | 'Afternoon' | 'Night'> = ['Morning', 'Afternoon', 'Night']
  const start = new Date('2026-12-07')
  const assignments: Assignment[] = []

  for (let d = 0; d < numDays; d++) {
    const date = new Date(start)
    date.setDate(start.getDate() + d)
    const dateStr = date.toISOString().split('T')[0]

    for (const shift of shifts) {
      const base = (d * 3 + shifts.indexOf(shift) * 5) % numWorkers
      for (let i = 0; i < 2; i++) {
        const wid = `ID_${(base + i) % numWorkers}`
        if (!assignments.find(a => a.date === dateStr && a.worker_id === wid)) {
          assignments.push({ date: dateStr, shift, worker_id: wid })
        }
      }
    }
}
  return { assignments }
}

// ─── Avatars ──────────────────────────────────────────────────────────────────

const AVATARS = [
  "https://www.untitledui.com/images/avatars/olivia-rhye?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/phoenix-baker?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/lana-steiner?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/demi-wilkinson?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/candice-wu?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/natali-craig?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/drew-cano?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/orlando-diggs?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/andi-lane?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/kate-morrison?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/olivia-rhye?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/phoenix-baker?fm=webp&q=80",
  "https://www.untitledui.com/images/avatars/lana-steiner?fm=webp&q=80",
]

function Avatar({ src, placeholder, className = '' }: { src?: string; placeholder?: React.ReactNode; className?: string }) {
  return (
    <div className={`avatar-circle ${className}`}>
      {src ? <img src={src} alt="avatar" className="avatar-img" /> : placeholder}
    </div>
  );
}

function AvatarAddButton() {
  return (
    <button className="avatar-add-btn">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
    </button>
  );
}

function WorkersAvatarGroup({ count }: { count: number }) {
  const displayCount = Math.min(count, 10);
  const remaining = count > 10 ? count - 10 : 0;
  
  return (
    <div className="avatar-group-wrap">
      <div className="avatar-overlap-group">
        {AVATARS.slice(0, displayCount).map((src, i) => (
          <Avatar key={i} src={src} />
        ))}
        {remaining > 0 && (
          <Avatar placeholder={<span className="avatar-placeholder">+{remaining}</span>} />
        )}
      </div>
      <AvatarAddButton />
    </div>
  );
}

// ─── Graph simulation script ───────────────────────────────────────────────

type SimStep = [number, AgentId, 'start' | 'done' | 'error' | 'redirect', string]

const SIM_SCRIPT: SimStep[] = [
  [400,  'workers',      'start',    'Parsing natural language preferences for 13 workers…'],
  [1800, 'workers',      'done',     'Extracted hard & soft constraints for all workers.'],
  [600,  'drafting',     'start',    'Building CP-SAT model — run 1…'],
  [3200, 'drafting',     'done',     'Feasible schedule found in 2.8s (OPTIMAL).'],
  [500,  'verification', 'start',    'Validating constraints — run 1…'],
  [1400, 'verification', 'error',    'Violation detected: ID_4 exceeds 36h/week in days 8–14.'],
  [300,  'verification', 'redirect', '→ Routing back to Drafting Agent for refinement.'],
  [700,  'drafting',     'start',    'Rebuilding model with tightened weekly budget — run 2…'],
  [2800, 'drafting',     'done',     'New feasible schedule found in 2.1s (FEASIBLE).'],
  [500,  'verification', 'start',    'Re-validating constraints — run 2…'],
  [1200, 'verification', 'done',     'All 7 constraint categories passed. Schedule is valid.'],
  [600,  'fairness',     'start',    'Computing Maximin satisfaction scores…'],
  [1600, 'fairness',     'done',     'Min satisfaction: 72/100 (ID_9). Fairness threshold met.'],
]

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SHIFT_COLORS: Record<string, string> = {
  Morning: '#d4d4d4', Afternoon: '#737373', Night: '#404040',
}
const SHIFT_LABEL: Record<string, string> = {
  Morning: 'M', Afternoon: 'A', Night: 'N',
}

const AGENT_META: Record<AgentId, { label: string; description: string }> = {
  workers:      { label: 'Workers Agent',      description: 'Parse natural language preferences' },
  drafting:     { label: 'Drafting Agent',      description: 'Build & solve CP-SAT model' },
  verification: { label: 'Verification Agent',  description: 'Validate all hard constraints' },
  fairness:     { label: 'Fairness Agent',       description: 'Evaluate Maximin fairness' },
}

const AGENT_ORDER: AgentId[] = ['workers', 'drafting', 'verification', 'fairness']

function makeInitialAgents(): AgentState[] {
  return AGENT_ORDER.map(id => ({
    id,
    ...AGENT_META[id],
    status: 'idle',
    runs: 0,
  }))
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatusIcon({ status }: { status: AgentStatus }) {
  if (status === 'done')    return <CheckIcon size={16} strokeWidth={2.5} />
  if (status === 'running') return <LoaderIcon size={16} className="spin" />
  if (status === 'error')   return <AlertCircleIcon size={16} />
  return <CircleIcon size={16} strokeWidth={1.5} />
}

function formatTs(ts: number) {
  const d = new Date(ts)
  return `${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}.${String(d.getMilliseconds()).padStart(3,'0').slice(0,2)}`
}

function AgentNode({ agent, logs, isLast }: { agent: AgentState, logs: LogEntry[], isLast: boolean }) {
  if (agent.status === 'idle') return null;

  return (
    <div className="agent-node">
      <div className={`agent-node-icon status-${agent.status}`}>
        <StatusIcon status={agent.status} />
      </div>
      
      {!isLast && <div className={`agent-node-line ${agent.status === 'done' ? 'line-done' : ''}`} />}

      <div className="agent-node-content">
        <div className="agent-node-header">
          <h3 className="agent-label">{agent.label}</h3>
          {agent.runs > 1 && (
            <span className="run-badge">
              <RotateCcwIcon size={10} /> run {agent.runs}
            </span>
          )}
        </div>
        <p className="agent-desc">{agent.description}</p>
        
        <div className="agent-logs">
          {logs.map((log, i) => (
            <div key={i} className={`log-entry type-${log.type}`}>
              <span className="log-ts">{formatTs(log.ts)}</span>
              <BlurText
                text={log.message}
                delay={20}
                animateBy="words"
                direction="top"
                className="log-message"
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ScheduleGrid({ schedule, numDays }: { schedule: Schedule; numDays: number }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const start = new Date('2026-12-07')

  const byWorker: Record<string, Record<number, string>> = {}
  for (const a of schedule.assignments) {
    if (!byWorker[a.worker_id]) byWorker[a.worker_id] = {}
    const d = Math.round((new Date(a.date).getTime() - start.getTime()) / 86400000)
    byWorker[a.worker_id][d] = a.shift
  }

  const workers = Object.keys(byWorker).sort((a, b) =>
    parseInt(a.split('_')[1]) - parseInt(b.split('_')[1])
  )
  const days = Array.from({ length: numDays }, (_, i) => i)

  const totals: Record<string, Record<string, number>> = {}
  for (const w of workers) {
    totals[w] = { M: 0, A: 0, N: 0 }
    for (const d of days) {
      const s = byWorker[w]?.[d]
      if (s === 'Morning') totals[w].M++
      else if (s === 'Afternoon') totals[w].A++
      else if (s === 'Night') totals[w].N++
    }
  }

  return (
    <div className="schedule-wrap panel">
      <div style={{ padding: '16px 20px 0' }}>
        <p className="section-label">
          Generated Schedule — {schedule.assignments.length} assignments · {workers.length} workers · {numDays} days
        </p>
      </div>
      <div className="schedule-grid-inner">
        <div className="schedule-header">
          <div className="schedule-worker-col" />
          {days.map(d => <div key={d} className="schedule-day-label">{d + 1}</div>)}
          <div className="schedule-totals-col">Tot</div>
        </div>

        {workers.map(w => (
          <div
            key={w}
            className="schedule-row"
            onClick={() => setExpanded(expanded === w ? null : w)}
          >
            <div className="schedule-worker-col">
              <Avatar src={AVATARS[parseInt(w.split('_')[1]) % AVATARS.length]} className="grid-avatar" />
              <span className="worker-id">{w.replace('ID_', 'Dr. ')}</span>
              <ChevronDownIcon size={10} className={`chevron ${expanded === w ? 'chevron--open' : ''}`} />
            </div>

            {days.map(d => {
              const shift = byWorker[w]?.[d]
              return (
                <div key={d} className="schedule-cell">
                  {shift
                    ? <span className="shift-dot" style={{ color: SHIFT_COLORS[shift] }} title={shift}>{SHIFT_LABEL[shift]}</span>
                    : <span className="shift-empty">·</span>
                  }
                </div>
              )
            })}

            <div className="schedule-totals-col schedule-totals-data">
              <span style={{ color: SHIFT_COLORS.Morning }}>{totals[w].M}M</span>{' '}
              <span style={{ color: SHIFT_COLORS.Afternoon }}>{totals[w].A}A</span>{' '}
              <span style={{ color: SHIFT_COLORS.Night }}>{totals[w].N}N</span>
            </div>
          </div>
        ))}

        <div className="schedule-legend">
          {(['Morning', 'Afternoon', 'Night'] as const).map(s => (
            <span key={s} style={{ color: SHIFT_COLORS[s] }}>{SHIFT_LABEL[s]} = {s}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [agents, setAgents] = useState<AgentState[]>(makeInitialAgents())
  const [log, setLog] = useState<LogEntry[]>([])
  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [running, setRunning] = useState(false)
  const [numWorkers, setNumWorkers] = useState(13)
  const [numDays, setNumDays] = useState(31)
  const timeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([])

  // Autoscroll verso il basso durante la generazione
  useEffect(() => {
    if (running || schedule) {
      window.scrollTo({
        top: document.body.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, [log, schedule, running]);

  const pushLog = useCallback((agent: AgentId, type: LogEntry['type'], message: string) => {
    setLog(prev => [...prev, { ts: Date.now(), agent, type, message }])
  }, [])

  const updateAgent = useCallback((id: AgentId, patch: Partial<AgentState>) => {
    setAgents(prev => prev.map(a => a.id === id ? { ...a, ...patch } : a))
  }, [])

  const stopAll = () => {
    timeoutsRef.current.forEach(clearTimeout)
    timeoutsRef.current = []
  }

  const runSimulation = () => {
    if (running) return
    stopAll()
    setRunning(true)
    setSchedule(null)
    setLog([])
    setAgents(makeInitialAgents())

    let elapsed = 0

    for (const [delay, agent, type, message] of SIM_SCRIPT) {
      elapsed += delay
      const t = setTimeout(() => {
        pushLog(agent, type, message)

        if (type === 'start') {
          updateAgent(agent, {
            status: 'running',
            runs: 0,
            detail: undefined,
          })
          setAgents(prev => prev.map(a =>
            a.id === agent ? { ...a, status: 'running', runs: a.runs + 1 } : a
          ))
        } else if (type === 'done') {
          updateAgent(agent, { status: 'done', detail: message })
        } else if (type === 'error') {
          updateAgent(agent, { status: 'error', detail: message })
        }
      }, elapsed)

      timeoutsRef.current.push(t)
    }

    const totalElapsed = elapsed + 800
    const finalT = setTimeout(() => {
      setSchedule(generateMockSchedule(numWorkers, numDays))
      setRunning(false)
    }, totalElapsed)
    timeoutsRef.current.push(finalT)
  }

  const anyDone = agents.some(a => a.status !== 'idle')

  // Identify the last non-idle agent to not render the connecting line for it
  const activeAgents = agents.filter(a => a.status !== 'idle');

  return (
    <main>
      <div className="container centered-layout">

        {/* ── Header ── */}
        <header className="page-header">
          <div>
            <h1 className="page-title">SmartScheduler</h1>
            <p className="page-subtitle">
              Hybrid Agentic Multi-Agent System for hospital shift optimization
            </p>
          </div>
          <div className="header-tags">
            <span className="tag">LangGraph</span>
            <span className="tag">OR-Tools</span>
            <span className="tag">CP-SAT</span>
            <span className="tag">RAG</span>
          </div>
        </header>

        {/* ── Configuration & Controls ── */}
        <section className="config-panel">
          <div className="config-inputs">
            <div className="form-row">
              <label className="form-label"><UsersIcon size={14} /> Workers</label>
              <input type="number" className="form-input" value={numWorkers}
                min={4} max={30} onChange={e => setNumWorkers(Number(e.target.value))}
                disabled={running} />
            </div>

            <WorkersAvatarGroup count={numWorkers} />
          </div>
          
          <button
            className={`run-btn ${running ? 'run-btn--loading' : ''}`}
            onClick={runSimulation}
            disabled={running}
          >
            {running
              ? <><LoaderIcon size={16} className="spin" /> Generating...</>
              : <><PlayIcon size={16} fill="currentColor" /> {anyDone ? 'Run Again' : 'Start'}</>
            }
          </button>
        </section>

        {/* ── Central Pipeline ── */}
        <section className="pipeline-section">
          {activeAgents.length === 0 && !running && (
             <div className="empty-state">
                <CalendarIcon size={32} className="empty-icon" />
                <p>Click start to watch the agents optimize the schedule in real-time.</p>
             </div>
          )}
          
          <div className="agents-flow">
            {activeAgents.map((agent, index) => (
              <AgentNode 
                key={agent.id + agent.runs} 
                agent={agent} 
                logs={log.filter(l => l.agent === agent.id)} 
                isLast={index === activeAgents.length - 1}
              />
            ))}
          </div>
        </section>

        {/* ── Schedule grid ── */}
        {schedule && (
          <section className="schedule-section">
            <BlurText text="Optimization Complete!" delay={50} className="success-title" direction="bottom" />
            <ScheduleGrid schedule={schedule} numDays={numDays} />
          </section>
        )}

        {/* ── Footer ── */}
        <footer className="page-footer">
          <span>SmartScheduler — Academic Project</span>
          <span>Neuro-Symbolic AI · UNICAL 2025/26</span>
        </footer>

      </div>
    </main>
  )
}
