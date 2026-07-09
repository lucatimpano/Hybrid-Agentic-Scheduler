import { useState, useRef, useCallback, useEffect } from 'react'
import {
  CheckIcon, LoaderIcon, CircleIcon, CalendarIcon,
  UsersIcon, ChevronDownIcon, RotateCcwIcon, AlertCircleIcon, PlayIcon,
  ShieldCheckIcon, ScaleIcon, PenToolIcon, ClipboardCheckIcon,
  SquareIcon, CheckCircleIcon
} from 'lucide-react'
import './App.css'
import BlurText from './BlurText'
import { Select } from './components/base/select/select'

// ─── Types ───────────────────────────────────────────────────────────────────

type AgentId = 'worker_node' | 'rag_node' | 'draft_node' | 'verify_node' | 'fairness_node' | 'refine_node' | 'revert_node' | 'quality_gate'
type AgentStatus = 'idle' | 'running' | 'done' | 'error' | 'waiting'

interface LogEntry {
  ts: number
  type: 'start' | 'done' | 'error' | 'info'
  message: string
  kind?: 'rag_verdict' | 'code' | 'text'
  approved?: boolean
  worker_id?: string
  code?: string
  reason?: string
  law?: string
}

interface PreferencesData {
  workers: Record<string, {
    role?: string
    shift_weights?: number[]
    hard_constraints?: Array<{
      type: string
      value?: string | number
      description?: string
    }>
    soft_constraints?: Array<{
      type: string
      value?: string | number
      shift?: string
      weight?: number
      natural_language?: string
      description?: string
    }>
  }>
}

interface Step {
  key: string
  agentId: AgentId
  label: string
  description: string
  status: AgentStatus
  logs: LogEntry[]
  detail?: string
  subSteps?: Step[]
  reverted?: boolean
}

interface Assignment {
  date: string
  shift: 'Morning' | 'Afternoon' | 'Night'
  worker_id: string
  role_played?: string
  original_role?: string
}

interface Schedule { assignments: Assignment[] }

interface FairnessData {
  worst_worker: string
  min_score: number
  fairness_gap: number
  scores: Record<string, number>
}

// ─── Constants ───────────────────────────────────────────────────────────────

const API_BASE = 'http://localhost:8000'

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

const SHIFT_COLORS: Record<string, string> = {
  Morning: '#d4d4d4', Afternoon: '#737373', Night: '#404040',
}
const SHIFT_LABEL: Record<string, string> = {
  Morning: 'M', Afternoon: 'A', Night: 'N',
}

const AGENT_META: Record<AgentId, { label: string; description: string }> = {
  worker_node:   { label: 'Workers Agent',      description: 'Parsing preferenze dal testo libero' },
  rag_node:      { label: 'RAG Compliance',      description: 'Verifica regolamento ospedaliero' },
  draft_node:    { label: 'Drafting Agent',      description: 'Costruzione e risoluzione modello CP-SAT' },
  verify_node:   { label: 'Verification Agent',  description: 'Validazione vincoli hard' },
  fairness_node: { label: 'Fairness Agent',       description: 'Analisi equità Rawlsian Maximin' },
  refine_node:   { label: 'Refinement',           description: 'Boost pesi worst worker e rigenerazione' },
  revert_node:   { label: 'Revert',                description: 'Ripristino schedule pre-refinement' },
  quality_gate:  { label: 'Quality Gate',         description: 'Validazione e equità della turnazione' },
}

const AGENT_ORDER: AgentId[] = ['worker_node', 'rag_node', 'draft_node', 'quality_gate']

const AGENT_ICONS: Record<AgentId, React.ReactNode> = {
  worker_node:   <UsersIcon size={16} />,
  rag_node:      <ShieldCheckIcon size={16} />,
  draft_node:    <PenToolIcon size={16} />,
  verify_node:   <ClipboardCheckIcon size={16} />,
  fairness_node: <ScaleIcon size={16} />,
  refine_node:   <RotateCcwIcon size={16} />,
  revert_node:   <RotateCcwIcon size={16} />,
  quality_gate:  <CheckCircleIcon size={16} />,
}

// ─── Sub-components ──────────────────────────────────────────────────────────

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

function StatusIcon({ status }: { status: AgentStatus }) {
  if (status === 'done')    return <CheckIcon size={16} strokeWidth={2.5} />
  if (status === 'running') return <LoaderIcon size={16} className="spin" />
  if (status === 'error')   return <AlertCircleIcon size={16} />
  if (status === 'waiting') return <RotateCcwIcon size={14} className="pulse" />
  return <CircleIcon size={16} strokeWidth={1.5} />
}

function AgentNode({ step, isLast }: { step: Step; isLast: boolean }) {
  const isError = step.status === 'error'
  const isDone = step.status === 'done'

  return (
    <div className={`agent-node ${isError ? 'agent-node--error' : ''} ${isDone ? 'agent-node--done' : ''}`}>
      <div className={`agent-node-icon status-${step.status}`}>
        {step.status === 'idle'
          ? <CircleIcon size={16} strokeWidth={1.5} />
          : AGENT_ICONS[step.agentId] || <StatusIcon status={step.status} />}
      </div>

      {!isLast && <div className={`agent-node-line ${isDone ? 'line-done' : ''} ${isError ? 'line-error' : ''}`} />}

      <div className="agent-node-content">
        <div className="agent-node-header">
          <h3 className="agent-label">{step.label}</h3>
          {step.status === 'running' && (
            <span className="status-badge status-badge--running">
              <LoaderIcon size={10} className="spin" /> In esecuzione
            </span>
          )}
          {step.status === 'done' && (
            <span className="status-badge status-badge--done">
              <CheckIcon size={10} /> Completato
            </span>
          )}
          {step.status === 'error' && (
            <span className="status-badge status-badge--error">
              <AlertCircleIcon size={10} /> Errore
            </span>
          )}
          {step.reverted && (
            <span className="status-badge status-badge--reverted">
              <RotateCcwIcon size={10} /> Ripristinato
            </span>
          )}
        </div>
        <p className="agent-desc">{step.description}</p>

        {step.subSteps && step.subSteps.length > 0 && (
          <div className="substeps">
            {step.subSteps.map(sub => (
              <div key={sub.key} className={`substep status-${sub.status}`}>
                <span className="substep-icon">
                  {AGENT_ICONS[sub.agentId] || <StatusIcon status={sub.status} />}
                </span>
                <span className="substep-label">{sub.label}</span>
                <span className="substep-status">
                  <StatusIcon status={sub.status} />
                </span>
              </div>
            ))}
          </div>
        )}

        {step.logs.length > 0 && (
          <div className="agent-logs">
            {step.logs.map((log, i) => {
              // ─── Verdetto RAG (senza icone, con regola infranta) ───
              if (log.kind === 'rag_verdict') {
                return (
                  <div key={i} className={`log-entry log-verdict ${log.approved ? 'verdict-approved' : 'verdict-rejected'}`}>
                    <span className="verdict-text">
                      <strong>{log.approved ? 'Approvato' : 'Bocciato'}</strong>
                      {' '}<code className="verdict-worker">{(log.worker_id || '').replace('ID_', 'Dr. ')}</code>
                      {log.message && <span className="verdict-rule"> — “{log.message}”</span>}
                      {log.law && <span className="verdict-law">{log.law}</span>}
                      {log.reason && <span className="verdict-reason">{log.reason}</span>}
                    </span>
                  </div>
                )
              }

              // ─── Blocco codice CP-SAT generato on-the-fly ───
              if (log.kind === 'code' && log.code) {
                return (
                  <div key={i} className="log-entry log-code">
                    <div className="code-header">
                      <span className="code-dots">•••</span>
                      <code className="code-worker">
                        CP-SAT · {(log.worker_id || '').replace('ID_', 'Dr. ')}
                        {log.message ? ` — “${log.message}”` : ''}
                      </code>
                    </div>
                    <pre className="code-block"><code>{log.code}</code></pre>
                  </div>
                )
              }

              // Log testuale generico (info/done/error/start)
              return (
                <div key={i} className={`log-entry type-${log.type}`}>
                  <BlurText
                    text={log.message}
                    delay={20}
                    animateBy="words"
                    direction="top"
                    className="log-message"
                  />
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Fairness Card ───────────────────────────────────────────────────────────

function FairnessCard({ data }: { data: FairnessData }) {
  return (
    <div className="fairness-card panel">
      <div className="fairness-header">
        <ScaleIcon size={18} />
        <h3>Analisi di Equità (Game Theory)</h3>
      </div>
      <div className="fairness-grid">
        <div className="fairness-metric">
          <span className="fairness-label">Rawlsian Maximin</span>
          <span className="fairness-value">{data.min_score}</span>
        </div>
        <div className="fairness-metric">
          <span className="fairness-label">Fairness Gap</span>
          <span className="fairness-value">{data.fairness_gap}</span>
        </div>
        <div className="fairness-metric">
          <span className="fairness-label">Medico Peggiore</span>
          <span className="fairness-value fairness-worker">{data.worst_worker.replace('ID_', 'Dr. ')}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Worker Detail Panel ─────────────────────────────────────────────────────

function WorkerDetailPanel({ workerId, prefs }: { workerId: string; prefs?: PreferencesData['workers'][string] }) {
  if (!prefs) return <div className="worker-detail-panel">Nessuna preferenza disponibile.</div>

  const hard = prefs.hard_constraints || []
  const soft = prefs.soft_constraints || []
  const weights = prefs.shift_weights || []

  return (
    <div className="worker-detail-panel">
      <div className="worker-detail-header">
        <span className="worker-detail-role">{prefs.role || 'standard'}</span>
        {weights.length === 3 && (
          <span className="worker-detail-weights">
            Pesi turni: M {weights[0]} · A {weights[1]} · N {weights[2]}
          </span>
        )}
      </div>

      {hard.length > 0 && (
        <div className="worker-detail-section">
          <h5>Vincoli obbligatori</h5>
          <ul>
            {hard.map((c, i) => (
              <li key={`h-${i}`}>
                <code>{c.type}</code>
                {c.value !== undefined && c.value !== null && <span> → {String(c.value)}</span>}
                {c.description && <span className="worker-detail-desc"> — {c.description}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {soft.length > 0 && (
        <div className="worker-detail-section">
          <h5>Preferenze (soft constraints)</h5>
          <ul>
            {soft.map((c, i) => (
              <li key={`s-${i}`}>
                <code>{c.type}</code>
                {c.natural_language && <span className="worker-detail-desc"> — “{c.natural_language}”</span>}
                {c.value !== undefined && c.value !== null && !c.natural_language && <span> → {String(c.value)}</span>}
                {c.shift && <span> ({c.shift})</span>}
                {c.weight !== undefined && <span className="worker-detail-weight"> · peso {c.weight}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {hard.length === 0 && soft.length === 0 && (
        <p className="worker-detail-empty">Nessun vincolo o preferenza specificata.</p>
      )}
    </div>
  )
}

// ─── Schedule Grid ───────────────────────────────────────────────────────────

function ScheduleGrid({ schedule, numDays, preferences }: { schedule: Schedule; numDays: number; preferences: PreferencesData | null }) {
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
          Turnazione — {schedule.assignments.length} assegnazioni · {workers.length} medici · {numDays} giorni
        </p>
      </div>
      <div className="schedule-grid-inner">
        <div className="schedule-header">
          <div className="schedule-worker-col" />
          {days.map(d => <div key={d} className="schedule-day-label">{d + 1}</div>)}
          <div className="schedule-totals-col">Tot</div>
        </div>

        {workers.map(w => (
          <div key={w}>
            <div
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

            {expanded === w && (
              <WorkerDetailPanel workerId={w} prefs={preferences?.workers?.[w]} />
            )}
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
  const [steps, setSteps] = useState<Step[]>([])
  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [preferences, setPreferences] = useState<PreferencesData | null>(null)
  const [running, setRunning] = useState(false)
  const [fairness, setFairness] = useState<FairnessData | null>(null)
  const [scenario, setScenario] = useState<"a" | "b">("a")
  const numWorkers = scenario === "a" ? 13 : 20
  const [numDays] = useState(31)
  const [elapsed, setElapsed] = useState(0)
  const eventSourceRef = useRef<EventSource | null>(null)
  const stepCounters = useRef<Record<string, number>>({})

  useEffect(() => {
    if (!running) {
      return
    }
    const startedAt = Date.now()
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 500)
    return () => clearInterval(timer)
  }, [running])

  useEffect(() => {
    if (!running) {
      setSchedule(null)
      setPreferences(null)
      setFairness(null)
      setSteps([])
      stepCounters.current = {}
    }
  }, [scenario])

  // Autoscroll
  useEffect(() => {
    if (running || schedule) {
      window.scrollTo({
        top: document.body.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, [steps, schedule, running]);

  const nextStepKey = useCallback((agentId: AgentId) => {
    stepCounters.current[agentId] = (stepCounters.current[agentId] || 0) + 1
    return `${agentId}-${stepCounters.current[agentId]}`
  }, [])

  const addStep = useCallback((agentId: AgentId, message: string) => {
    const key = nextStepKey(agentId)
    const meta = AGENT_META[agentId]
    const count = stepCounters.current[agentId] || 0
    const isRefinement = agentId === 'draft_node' && count > 1
    const label = isRefinement ? `${meta.label} (Refinement #${count - 1})` : meta.label
    const newStep: Step = {
      key,
      agentId,
      label,
      description: meta.description,
      status: 'running',
      logs: [{ ts: Date.now(), type: 'start', message }],
      detail: message,
    }
    setSteps(prev => [...prev, newStep])
    return key
  }, [nextStepKey])

  const pushAgentLog = useCallback((agentId: AgentId, type: LogEntry['type'], message: string, extra?: Partial<LogEntry>) => {
    setSteps(prev => {
      const revIdx = [...prev].reverse().findIndex(s => s.agentId === agentId)
      if (revIdx === -1) return prev
      const idx = prev.length - 1 - revIdx
      const updated = [...prev]
      updated[idx] = {
        ...updated[idx],
        logs: [...updated[idx].logs, { ts: Date.now(), type, message, ...extra }],
      }
      return updated
    })
  }, [])

  const updateLastStepStatus = useCallback((agentId: AgentId, status: AgentStatus, message: string) => {
    setSteps(prev => {
      const revIdx = [...prev].reverse().findIndex(s => s.agentId === agentId && s.status === 'running')
      if (revIdx === -1) return prev
      const idx = prev.length - 1 - revIdx
      const updated = [...prev]
      updated[idx] = { ...updated[idx], status, detail: message }
      return updated
    })
    pushAgentLog(agentId, status === 'error' ? 'error' : 'done', message)
  }, [pushAgentLog])

  const stopStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }, [])

  const runPipeline = useCallback(() => {
    if (running) return
    stopStream()
    setRunning(true)
    setElapsed(0)
    setSchedule(null)
    setPreferences(null)
    setFairness(null)
    setSteps([])
    stepCounters.current = {}

    const es = new EventSource(`${API_BASE}/api/stream?case=${scenario}`)
    eventSourceRef.current = es

    es.addEventListener('node_start', (e) => {
      const data = JSON.parse(e.data) as { node: string; message: string }
      const nodeId = data.node as AgentId
      if (nodeId === 'pipeline') return

      // Refinement non è un nodo separato nella UI: aggiungiamo un log
      // al Quality Gate per segnalare l'inizio del refinamento.
      if (nodeId === 'refine_node' || nodeId === 'revert_node') {
        setSteps(prev => {
          const qIdx = prev.findLastIndex(s => s.agentId === 'quality_gate')
          if (qIdx === -1) return prev
          const next = [...prev]
          next[qIdx] = {
            ...next[qIdx],
            reverted: nodeId === 'revert_node' ? true : next[qIdx].reverted,
            logs: [...next[qIdx].logs, { ts: Date.now(), type: 'info',
              message: nodeId === 'refine_node'
                ? `Refinement: ${data.message}`
                : `Revert: ${data.message}`,
            }],
          }
          return next
        })
        return
      }

      // Verify e Fairness vengono raggruppati sotto un unico Quality Gate
      if (nodeId === 'verify_node' || nodeId === 'fairness_node') {
        setSteps(prev => {
          const qIdx = prev.findLastIndex(s => s.agentId === 'quality_gate' && s.status === 'running')
          let next = [...prev]
          let parent: Step

          if (qIdx !== -1) {
            parent = next[qIdx]
          } else {
            const key = nextStepKey('quality_gate')
            parent = {
              key,
              agentId: 'quality_gate',
              label: AGENT_META.quality_gate.label,
              description: AGENT_META.quality_gate.description,
              status: 'running',
              logs: [{ ts: Date.now(), type: 'start', message: 'Quality Gate aperto...' }],
              detail: 'Validazione vincoli hard e analisi equità...',
              subSteps: [],
            }
            next.push(parent)
          }

          const meta = AGENT_META[nodeId]
          const subKey = `${parent.key}-${nodeId}-${Date.now()}`
          const subStep: Step = {
            key: subKey,
            agentId: nodeId,
            label: meta.label,
            description: meta.description,
            status: 'running',
            logs: [{ ts: Date.now(), type: 'start', message: data.message }],
            detail: data.message,
          }

          next = next.map(s => s.key === parent.key
            ? { ...s, subSteps: [...(s.subSteps || []), subStep] }
            : s
          )
          return next
        })
        return
      }

      addStep(nodeId, data.message)
    })

    es.addEventListener('rag_verdict', (e) => {
      const data = JSON.parse(e.data) as {
        worker_id: string
        natural_language: string
        approved: boolean
        reason: string
        law: string
      }
      pushAgentLog('rag_node', 'info', data.natural_language, {
        kind: 'rag_verdict',
        approved: data.approved,
        worker_id: data.worker_id,
        reason: data.reason,
        law: data.law,
      })
    })

    es.addEventListener('code', (e) => {
      const data = JSON.parse(e.data) as {
        worker_id: string
        natural_language: string
        code: string
      }
      pushAgentLog('draft_node', 'info', data.natural_language, {
        kind: 'code',
        worker_id: data.worker_id,
        code: data.code,
      })
    })

    es.addEventListener('node_done', (e) => {
      const data = JSON.parse(e.data) as {
        node: string
        message: string
        has_violations: boolean
      }
      const nodeId = data.node as AgentId

      // Refinement e revert sono incorporati nel Quality Gate, nessun step UI separato
      if (nodeId === 'refine_node' || nodeId === 'revert_node') return

      // Chiudi il sub-step dentro il Quality Gate
      if (nodeId === 'verify_node' || nodeId === 'fairness_node') {
        setSteps(prev => {
          const qIdx = prev.findLastIndex(s => s.agentId === 'quality_gate')
          if (qIdx === -1) return prev
          const parent = prev[qIdx]
          if (!parent.subSteps) return prev

          const subRevIdx = [...parent.subSteps].reverse().findIndex(s => s.agentId === nodeId && s.status === 'running')
          if (subRevIdx === -1) return prev
          const sIdx = parent.subSteps.length - 1 - subRevIdx

          const newSubSteps = [...parent.subSteps]
          newSubSteps[sIdx] = {
            ...newSubSteps[sIdx],
            status: data.has_violations ? 'error' : 'done',
            detail: data.message,
            logs: [...newSubSteps[sIdx].logs, { ts: Date.now(), type: data.has_violations ? 'error' : 'done', message: data.message }],
          }

          let parentStatus: AgentStatus = parent.status
          if (data.has_violations) {
            parentStatus = 'error'
          } else if (nodeId === 'fairness_node') {
            parentStatus = 'done'
          }

          const next = [...prev]
          next[qIdx] = { ...parent, status: parentStatus, subSteps: newSubSteps }
          return next
        })
        return
      }

      updateLastStepStatus(nodeId, data.has_violations ? 'error' : 'done', data.message)
    })

    es.addEventListener('fairness', (e) => {
      const data = JSON.parse(e.data) as FairnessData
      setFairness(data)
      const msg = `Maximin: ${data.min_score} (${data.worst_worker}) · Gap: ${data.fairness_gap}`
      // Il log di fairness va nel Quality Gate, non più in un nodo flat
      setSteps(prev => {
        const qIdx = prev.findLastIndex(s => s.agentId === 'quality_gate' && s.status === 'running')
        if (qIdx === -1) return prev
        const next = [...prev]
        next[qIdx] = { ...next[qIdx], logs: [...next[qIdx].logs, { ts: Date.now(), type: 'info', message: msg }] }
        return next
      })
    })

    es.addEventListener('schedule', (e) => {
      const data = JSON.parse(e.data) as {
        schedule: Schedule
        preferences: PreferencesData
        worst_worker: string
        min_score: number
        fairness_gap: number
        fairness_scores: Record<string, number>
      }
      setSchedule(data.schedule)
      setPreferences(data.preferences)
      setFairness({
        worst_worker: data.worst_worker,
        min_score: data.min_score,
        fairness_gap: data.fairness_gap,
        scores: data.fairness_scores,
      })
    })

    es.addEventListener('error', (e) => {
      try {
        const data = JSON.parse(e.data) as { message: string; violations?: string[] }
        pushAgentLog('draft_node', 'error', data.message)
      } catch {
        pushAgentLog('worker_node', 'error', 'Connessione al server persa.')
      }
    })

    es.addEventListener('done', () => {
      setRunning(false)
      stopStream()
    })

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setRunning(false)
        stopStream()
      }
    }
  }, [running, addStep, pushAgentLog, updateLastStepStatus, stopStream, scenario])

  // Cleanup on unmount
  useEffect(() => {
    return () => stopStream()
  }, [stopStream])

  const anyDone = steps.some(s => s.status !== 'idle')

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
          <div className="config-row">
            <div className="config-inputs">
              <Select
                label="Scenario"
                placeholder="Seleziona scenario"
                items={[
                  { id: 'a', label: 'Caso A', supportingText: '13 workers standard' },
                  { id: 'b', label: 'Caso B', supportingText: '20 workers con specialisti' },
                ]}
                selectedKey={scenario}
                onSelectionChange={(key) => setScenario(key as 'a' | 'b')}
                isDisabled={running}
              />
              <div className="form-row">
                <label className="form-label"><UsersIcon size={14} /> Workers</label>
                <span className="form-value">{numWorkers}</span>
              </div>
              <div className="form-row">
                <label className="form-label"><CalendarIcon size={14} /> Days</label>
                <span className="form-value">{numDays}</span>
              </div>

              <WorkersAvatarGroup count={numWorkers} />
            </div>

            <div className="run-controls">
              <button
                className={`run-btn ${running ? 'run-btn--loading' : ''}`}
                onClick={runPipeline}
                disabled={running}
              >
                {running
                  ? <><LoaderIcon size={16} className="spin" /> Generating...</>
                  : <><PlayIcon size={16} fill="currentColor" /> {anyDone ? 'Run Again' : 'Start'}</>
                }
              </button>
              {running && (
                <button
                  className="stop-btn"
                  onClick={() => {
                    stopStream()
                    setRunning(false)
                  }}
                  title="Interrompi il pipeline"
                >
                  <SquareIcon size={14} fill="currentColor" /> Stop
                </button>
              )}
            </div>
          </div>
        </section>

        {/* ── Central Pipeline ── */}
        <section className="pipeline-section">
          {steps.length === 0 && !running && (
             <div className="empty-state">
                <CalendarIcon size={32} className="empty-icon" />
                <p>Premi Start per avviare il pipeline multi-agente e generare la turnazione in tempo reale.</p>
             </div>
          )}

          <div className="agents-flow">
            {steps.map((step, index) => (
              <AgentNode
                key={step.key}
                step={step}
                isLast={index === steps.length - 1}
              />
            ))}
          </div>
        </section>

        {/* ── Fairness metrics ── */}
        {fairness && (
          <section className="fairness-section" style={{ animation: 'fadeIn 0.6s ease-out forwards' }}>
            <FairnessCard data={fairness} />
          </section>
        )}

        {/* ── Schedule grid ── */}
        {schedule && (
          <section className="schedule-section">
            <BlurText text="Turnazione:" delay={50} className="success-title" direction="bottom" />
            <ScheduleGrid schedule={schedule} numDays={numDays} preferences={preferences} />
          </section>
        )}

        {/* ── Footer ── */}
        <footer className="page-footer">
          <span>SmartScheduler — Academic Project</span>
          <span>Neuro-Symbolic AI · UNICAL 2025/26</span>
        </footer>

        {elapsed > 0 && (
          <div className="floating-timer">
            {String(Math.floor(elapsed / 60)).padStart(2, '0')}:{String(elapsed % 60).padStart(2, '0')}
          </div>
        )}

      </div>
    </main>
  )
}
