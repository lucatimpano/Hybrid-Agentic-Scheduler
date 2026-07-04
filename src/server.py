"""
server.py — FastAPI server che espone il pipeline LangGraph via Server-Sent Events (SSE).

La UI React si connette a GET /api/stream e riceve in tempo reale gli aggiornamenti
dei nodi del grafo (worker_node, rag_node, draft_node, verify_node, fairness_node, refine_node)
e lo schedule finale.
"""

import json
import os
import re
import asyncio
import sys
import io
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from src.agents.orchestrator import create_scheduler_graph
from src.models.schemas import NUM_DAYS

# ---------------------------------------------------------------------------
# Lifespan (carica il grafo una sola volta all'avvio del server)
# ---------------------------------------------------------------------------

graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    print("[server] Compilazione grafo LangGraph...")
    graph = create_scheduler_graph()
    print("[server] Grafo pronto.")
    yield

app = FastAPI(title="SmartScheduler API", lifespan=lifespan)

# CORS: permetti al dev server Vite (porta 5173) di connettersi
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse_event(event_type: str, data: dict) -> str:
    """Formatta un evento SSE conforme allo standard."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


# Pattern per riconoscere i messaggi di interesse dallo stdout degli agenti.
#   RAG verdict  -> "[RAG] Vincolo approved/bocciato per {worker_id}: '{text}'"
#   Codice CP-SAT -> riga di apertura "[CODE] BEGIN {worker_id} | {text} | ..."
#                    seguita da 0..N righe di codice e dalla riga di chiusura
#                    "[CODE] END"
_CODE_BEGIN_RE = re.compile(r"\[CODE\]\s+BEGIN\s+(?P<worker_id>\S+)\s*\|\s*(?P<text>.*?)(?:\s*\|\s*weight=(?P<weight>\S+))?\s*$")
_CODE_END_RE = re.compile(r"\[CODE\]\s+END")


# ---------------------------------------------------------------------------
# Endpoint: GET /api/stream
# ---------------------------------------------------------------------------

@app.get("/api/stream")
async def stream_scheduler():
    """
    Esegue il pipeline LangGraph e ne streama gli aggiornamenti come SSE.

    Ogni evento ha un tipo (event:) e un payload JSON (data:).

    Tipi di evento:
      - node_start  : un nodo del grafo sta per essere eseguito
      - node_done   : un nodo del grafo ha terminato l'esecuzione
      - rag_verdict : verdetto del RAG su un singolo vincolo custom (approved/bocciato)
      - code        : snippet di codice CP-SAT generato on-the-fly dal DraftingAgent
      - fairness    : metriche di equità calcolate
      - schedule    : la turnazione finale (completa di assignments)
      - error       : errore durante l'esecuzione
      - done        : fine dello stream

    Nota: dopo `refine_node` il grafo torna a `draft_node` per rigenerare la
    turnazione con i pesi boostati: la `node_start` emessa per `draft_node`
    rappresenta il "salto all'indietro" del loop di refinement.
    """

    input_file = "data/input/workers_preferences.txt"

    if not os.path.exists(input_file):
        return JSONResponse(
            status_code=404,
            content={"error": f"File di input '{input_file}' non trovato."}
        )

    with open(input_file, "r", encoding="utf-8") as f:
        raw_preferences = f.read()

    initial_state = {
        "preferences": raw_preferences,
        "violations": [],
        "error_count": 0,
        "iteration": 0,
        "prev_min_score": 0,
        "fairness_gap": 0
    }

    async def event_generator():
        """Generator asincrono che produce eventi SSE dal pipeline LangGraph."""
        try:
            yield _sse_event("node_start", {"node": "pipeline", "message": "Avvio Hybrid-Agentic-Scheduler..."})

            final_state = dict(initial_state)

            loop = asyncio.get_event_loop()
            queue = asyncio.Queue()

            # Variabile per tenere traccia del nodo attivo per i log.
            # threading.local non và bene qua dentro perché la write() del
            # StringIO viene chiamata dallo STESSO thread che esegue il grafo,
            # ma manteniamo l'approccio per retrocompatibilità.
            class LogContext:
                current_node = "worker_node"

            log_ctx = LogContext()

            class StreamToQueue(io.StringIO):
                """
                Cattura lo stdout degli agenti e filtra intelligentemente:
                  - RAG verdict  -> evento `rag_verdict`
                  - Codice CP-SAT (blocco multi-linea) -> evento `code`
                  - tutto il resto viene ignorato (rumore LLM).
                """

                def __init__(self_inner):
                    super().__init__()
                    # Buffer per catturare i blocchi di codice multi-riga
                    self_inner._code_buffer = []
                    self_inner._code_meta = None

                def write(self_inner, s):
                    try:
                        sys.__stdout__.write(s)
                    except Exception:
                        pass
                    text = s.strip()
                    if not text:
                        return

                    node = log_ctx.current_node

                    # ─── Cattura blocco codice CP-SAT ───
                    if self_inner._code_meta is not None:
                        # siamo dentro un blocco [CODE] BEGIN ... [CODE] END
                        if _CODE_END_RE.search(text):
                            code = "\n".join(self_inner._code_buffer).strip()
                            meta = self_inner._code_meta
                            self_inner._code_buffer = []
                            self_inner._code_meta = None
                            if code:
                                loop.call_soon_threadsafe(
                                    queue.put_nowait,
                                    ("code", (meta["node"], meta["worker_id"], meta["text"], code))
                                )
                            return
                        # riga di codice: accumula
                        self_inner._code_buffer.append(text)
                        return

                    begin = _CODE_BEGIN_RE.search(text)
                    if begin:
                        # Inizia un nuovo blocco codice
                        self_inner._code_meta = {
                            "node": node if node in ("draft_node", "refine_node") else "draft_node",
                            "worker_id": begin.group("worker_id"),
                            "text": begin.group("text").strip(),
                        }
                        self_inner._code_buffer = []
                        return

                    # ─── RAG verdict (structured JSON line) ───
                    if text.strip().startswith('{"event"'):
                        try:
                            payload = json.loads(text)
                            if payload.get("event") == "rag_verdict":
                                loop.call_soon_threadsafe(
                                    queue.put_nowait,
                                    ("rag_verdict", (
                                        payload.get("worker_id", ""),
                                        payload.get("natural_language", ""),
                                        bool(payload.get("approved")),
                                        payload.get("reason", ""),
                                        payload.get("law", ""),
                                    ))
                                )
                        except Exception:
                            pass
                        return

                    # Tutto il resto (rumore LLM, info, NODE markers) viene INGORATO
                    # dalla UI. Non emettiamo piu' l'evento `log` generico.

                def flush(self_inner):
                    try:
                        sys.__stdout__.flush()
                    except Exception:
                        pass

            def run_graph():
                """Esegue il grafo e spinge gli step nella coda man mano che arrivano."""
                original_stdout = sys.stdout
                sys.stdout = StreamToQueue()
                try:
                    for step_data in graph.stream(initial_state, {"recursion_limit": 50}):
                        for node_name in step_data.keys():
                            # Mappatura del prossimo nodo "attivo" per i log catturati
                            # dopo questo step. NOTA: dopo refine_node torniamo a draft_node.
                            if node_name == "worker_node":   log_ctx.current_node = "rag_node"
                            elif node_name == "rag_node":    log_ctx.current_node = "draft_node"
                            elif node_name == "draft_node":  log_ctx.current_node = "verify_node"
                            elif node_name == "verify_node": log_ctx.current_node = "fairness_node"
                            elif node_name == "fairness_node": log_ctx.current_node = "refine_node"
                            elif node_name == "refine_node": log_ctx.current_node = "draft_node"
                        loop.call_soon_threadsafe(queue.put_nowait, ("step", step_data))
                    loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
                except Exception as e:
                    loop.call_soon_threadsafe(queue.put_nowait, ("error", e))
                finally:
                    sys.stdout = original_stdout

            # Avvia il thread senza bloccare l'event loop
            loop.run_in_executor(None, run_graph)

            # Emetti evento di inizio per il primo nodo (worker_node)
            yield _sse_event("node_start", {
                "node": "worker_node",
                "message": _node_description("worker_node", final_state)
            })

            while True:
                msg_type, data = await queue.get()
                if msg_type == "done":
                    break
                elif msg_type == "error":
                    raise data
                elif msg_type == "rag_verdict":
                    worker_id, text, approved, reason, law = data
                    yield _sse_event("rag_verdict", {
                        "node": "rag_node",
                        "worker_id": worker_id,
                        "natural_language": text,
                        "approved": approved,
                        "reason": reason,
                        "law": law,
                    })
                elif msg_type == "code":
                    node, worker_id, text, code = data
                    yield _sse_event("code", {
                        "node": "draft_node",
                        "worker_id": worker_id,
                        "natural_language": text,
                        "code": code,
                    })
                elif msg_type == "step":
                    step_data = data
                    for node_name, node_state in step_data.items():
                        # Accumula stato
                        final_state.update(node_state)

                        # Emetti informazioni specifiche per nodo
                        if node_name == "fairness_node":
                            yield _sse_event("fairness", {
                                "worst_worker": node_state.get("worst_worker", ""),
                                "min_score": node_state.get("prev_min_score", 0),
                                "fairness_gap": node_state.get("fairness_gap", 0),
                                "scores": node_state.get("fairness_scores", {})
                            })

                        # Il nodo corrente ha completato la sua esecuzione
                        yield _sse_event("node_done", {
                            "node": node_name,
                            "message": f"{node_name} completato.",
                            "has_violations": bool(node_state.get("violations")),
                            "iteration": node_state.get("iteration", final_state.get("iteration", 0))
                        })

                        # Deduciamo il prossimo nodo per inviare il node_start corrispondente,
                        # in modo che la UI mostri "in esecuzione" durante l'attesa del prossimo step
                        next_node = None
                        violations = node_state.get("violations")

                        if node_name == "worker_node":
                            next_node = "rag_node" if not violations else "worker_node"
                        elif node_name == "rag_node":
                            next_node = "draft_node" if not violations else "rag_node"
                        elif node_name == "draft_node":
                            next_node = "verify_node" if not violations else "draft_node"
                        elif node_name == "verify_node":
                            next_node = "fairness_node" if not violations else None
                        elif node_name == "fairness_node":
                            worst = node_state.get("worst_worker")
                            gap = node_state.get("fairness_gap", 0)
                            it = node_state.get("iteration", final_state.get("iteration", 0))
                            if worst and gap > 10 and it < 3:
                                next_node = "refine_node"
                        elif node_name == "refine_node":
                            # Torniamo a draft_node per rigenerare con i pesi boostati
                            next_node = "draft_node" if not violations else "refine_node"

                        if next_node:
                            yield _sse_event("node_start", {
                                "node": next_node,
                                "message": _node_description(next_node, final_state)
                            })

            # Emetti lo schedule finale
            if final_state.get("schedule"):
                yield _sse_event("schedule", {
                    "schedule": final_state["schedule"],
                    "preferences": final_state.get("preferences", {}),
                    "worst_worker": final_state.get("worst_worker", ""),
                    "min_score": final_state.get("prev_min_score", 0),
                    "fairness_gap": final_state.get("fairness_gap", 0),
                    "fairness_scores": final_state.get("fairness_scores", {}),
                })

                # Salva su disco
                output_file = "data/output/final_schedule.json"
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(final_state["schedule"], f, indent=4, ensure_ascii=False)

            elif final_state.get("violations"):
                yield _sse_event("error", {
                    "message": "Il sistema ha terminato con violazioni.",
                    "violations": final_state["violations"]
                })

            yield _sse_event("done", {"message": "Pipeline terminato."})

        except Exception as e:
            yield _sse_event("error", {"message": str(e)})
            yield _sse_event("done", {"message": "Pipeline terminato con errore."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ---------------------------------------------------------------------------
# Endpoint: GET /api/schedule (carica lo schedule salvato su disco)
# ---------------------------------------------------------------------------

@app.get("/api/schedule")
async def get_schedule():
    """Restituisce lo schedule salvato su disco, se esiste."""
    output_file = "data/output/final_schedule.json"
    if not os.path.exists(output_file):
        return JSONResponse(status_code=404, content={"error": "Nessuno schedule trovato."})

    with open(output_file, "r", encoding="utf-8") as f:
        schedule = json.load(f)
    return schedule


# ---------------------------------------------------------------------------
# Helpers per le descrizioni dei nodi
# ---------------------------------------------------------------------------

def _node_description(node_name: str, state: dict) -> str:
    """Restituisce una descrizione leggibile per ogni nodo."""
    descriptions = {
        "worker_node": "Parsing delle preferenze dei lavoratori dal testo libero...",
        "rag_node": "Verifica di conformità dei vincoli custom con il regolamento ospedaliero...",
        "draft_node": "Costruzione del modello CP-SAT e generazione della turnazione...",
        "verify_node": "Validazione deterministica dei vincoli hard sulla turnazione...",
        "fairness_node": "Calcolo delle metriche di equità (Rawlsian Maximin)...",
        "refine_node": f"Boost dei pesi del worst_worker (iterazione {state.get('iteration', 0) + 1}) e ritorno a draft...",
    }
    return descriptions.get(node_name, f"Esecuzione di {node_name}...")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.server:app", host="0.0.0.0", port=8000, reload=False)
