import { useState, useRef, useCallback } from 'react'
import {
  CheckIcon, LoaderIcon, CircleIcon, CalendarIcon,
  UsersIcon, ChevronDownIcon, RotateCcwIcon, AlertCircleIcon
} from 'lucide-react'
import './App.css'

// ─── Types ───────────────────────────────────────────────────────────────────

type AgentId = 'workers' | 'drafting' | 'verification' | 'fairness'
type AgentStatus = 'idle' | 'running' | 'done' | 'error'

interface AgentState {
  id: AgentId
  label: string
  description: string
  status: AgentStatus
  runs: number          // how many times this agent was invoked
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

  // Simple round-robin: each day assign 2 workers per shift
  for (let d = 0; d < numDays; d++) {
    const date = new Date(start)
    date.setDate(start.getDate() + d)
    const dateStr = date.toISOString().split('T')[0]

    for (const shift of shifts) {
      // Pick 2 workers per shift, rotated
      const base = (d * 3 + shifts.indexOf(shift) * 5) % numWorkers
      for (let i = 0; i < 2; i++) {
        const wid = `ID_${(base + i) % numWorkers}`
        // Skip if worker already has a shift today
        if (!assignments.find(a => a.date === dateStr && a.worker_id === wid)) {
          assignments.push({ date: dateStr, shift, worker_id: wid })
        }
      }
    }
  }
  return { assignments }
}

// ─── Graph simulation script ───────────────────────────────────────────────
// Each step: [delay_ms, agent, event, message]
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
  if (status === 'done')    return <CheckIcon size={13} strokeWidth={2.5} />
  if (status === 'running') return <LoaderIcon size={13} className="spin" />
  if (status === 'error')   return <AlertCircleIcon size={13} />
  return <CircleIcon size={13} strokeWidth={1.5} />
}

function AgentStepper({ agents }: { agents: AgentState[] }) {
  return (
    <div className="stepper">
      {agents.map((agent, i) => (
        <div key={agent.id} className={`stepper-item stepper-item--${agent.status}`}>
          {i < agents.length - 1 && (
            <div className={`stepper-line ${agents[i + 1].status !== 'idle' ? 'stepper-line--active' : ''}`} />
          )}

          <div className="stepper-icon">
            <StatusIcon status={agent.status} />
          </div>

          <div className="stepper-content">
            <div className="stepper-label-row">
              <span className="stepper-label">{agent.label}</span>
              {agent.runs > 1 && (
                <span className="run-badge">
                  <RotateCcwIcon size={9} /> run {agent.runs}
                </span>
              )}
            </div>
            <span className="stepper-desc">{agent.description}</span>
            {agent.detail && (
              <span className={`stepper-detail ${agent.status === 'error' ? 'stepper-detail--error' : ''}`}>
                {agent.detail}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function ExecutionLog({ entries }: { entries: LogEntry[] }) {
  const endRef = useRef<HTMLDivElement>(null)

  return (
    <div className="exec-log">
      <p className="section-label">Execution Log</p>
      <div className="log-entries">
        {entries.length === 0 && (
          <span className="log-empty">No events yet.</span>
        )}
        {entries.map((e, i) => (
          <div key={i} className={`log-entry log-entry--${e.type}`}>
            <span className="log-ts">{formatTs(e.ts)}</span>
            <span className="log-agent">{AGENT_META[e.agent].label}</span>
            <span className="log-msg">{e.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}

function formatTs(ts: number) {
  const d = new Date(ts)
  return `${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}.${String(d.getMilliseconds()).padStart(3,'0').slice(0,2)}`
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
    <div className="schedule-wrap">
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
            <span className="worker-id">{w}</span>
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
            runs: 0,          // will be incremented below
            detail: undefined,
          })
          // increment run count separately so it stacks correctly
          setAgents(prev => prev.map(a =>
            a.id === agent ? { ...a, status: 'running', runs: a.runs + 1 } : a
          ))
        } else if (type === 'done') {
          updateAgent(agent, { status: 'done', detail: message })
        } else if (type === 'error') {
          updateAgent(agent, { status: 'error', detail: message })
        }
        // 'redirect' entries only go to the log
      }, elapsed)

      timeoutsRef.current.push(t)
    }

    // Final: emit schedule
    const totalElapsed = elapsed + 800
    const finalT = setTimeout(() => {
      setSchedule(generateMockSchedule(numWorkers, numDays))
      setRunning(false)
    }, totalElapsed)
    timeoutsRef.current.push(finalT)
  }

  const anyDone = agents.some(a => a.status !== 'idle')
  const doneCount = agents.filter(a => a.status === 'done').length

  return (
    <main>
      <div className="container">

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
            <span className="tag">Neuro-Symbolic</span>
          </div>
        </header>

        <div className="layout">

          {/* ── Left: config + stepper ── */}
          <aside className="panel panel--left">

            <section className="section">
              <p className="section-label">Configuration</p>
              <div className="form-row">
                <label className="form-label"><UsersIcon size={12} /> Workers</label>
                <input type="number" className="form-input" value={numWorkers}
                  min={4} max={30} onChange={e => setNumWorkers(Number(e.target.value))}
                  disabled={running} />
              </div>
              <div className="form-row">
                <label className="form-label"><CalendarIcon size={12} /> Days</label>
                <input type="number" className="form-input" value={numDays}
                  min={7} max={31} onChange={e => setNumDays(Number(e.target.value))}
                  disabled={running} />
              </div>
            </section>

            <div className="divider" />

            <section className="section">
              <p className="section-label">Agent Pipeline</p>
              <AgentStepper agents={agents} />
            </section>

            <div className="divider" />

            {/* Progress indicator */}
            {anyDone && (
              <div className="progress-wrap">
                <div className="progress-bar" style={{ width: `${(doneCount / 4) * 100}%` }} />
              </div>
            )}

            <button
              className={`run-btn ${running ? 'run-btn--loading' : ''}`}
              onClick={runSimulation}
              disabled={running}
            >
              {running
                ? <><LoaderIcon size={13} className="spin" /> Running…</>
                : anyDone ? 'Run Again' : 'Generate Schedule'
              }
            </button>

          </aside>

          {/* ── Right: log + schedule ── */}
          <div className="right-col">

            {/* Execution log */}
            <div className="panel">
              <ExecutionLog entries={log} />
            </div>

            {/* Schedule grid */}
            {schedule && (
              <div className="panel">
                <div style={{ padding: '16px 20px 0' }}>
                  <p className="section-label">
                    Generated Schedule — {schedule.assignments.length} assignments · {numWorkers} workers · {numDays} days
                  </p>
                </div>
                <ScheduleGrid schedule={schedule} numDays={numDays} />
              </div>
            )}

            {!schedule && !running && !anyDone && (
              <div className="panel">
                <div className="empty-state">
                  <CalendarIcon size={22} className="empty-icon" />
                  <p>Configure and run the scheduler to see the generated timetable.</p>
                </div>
              </div>
            )}

          </div>
        </div>

        {/* ── Footer ── */}
        <footer className="page-footer">
          <span>SmartScheduler — Academic Project</span>
          <span>Neuro-Symbolic AI · UNICAL 2025/26</span>
        </footer>

      </div>
    </main>
  )
}
