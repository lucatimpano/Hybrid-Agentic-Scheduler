import copy
import json
from langgraph.graph import StateGraph, START, END

from src.models.schemas import SchedulerState, NUM_DAYS
from src.agents.workers_agent import WorkersAgent
from src.agents.rag_agent import RagAgent
from src.agents.drafting_agent import DraftingAgent
from src.agents.verification_agent import VerificationAgent
from src.agents.fairness_agent import FairnessAgent

MAX_RETRIES = 3

# Inizializzazione globale degli agenti (una sola volta)
workers_agent = WorkersAgent()
rag_agent = RagAgent()
drafting_agent = DraftingAgent()
verification_agent = VerificationAgent()
fairness_agent = FairnessAgent()

# -----------------------------------------------------------------------------
# NODI
# -----------------------------------------------------------------------------

def worker_node(state: SchedulerState):
    """Estrae le preferenze dal testo libero usando WorkersAgent."""
    print("-> [NODE] worker_node")
    try:
        prefs = workers_agent.parse_preferences(state["preferences"])
        # Successo: resetta error_count per la fase successiva
        return {"preferences": prefs, "violations": [], "error_count": 0, "iteration": 0}
    except Exception as e:
        count = state.get("error_count", 0) + 1
        print(f"   [WORKER] Errore (tentativo {count}): {e}")
        return {"violations": [str(e)], "error_count": count}


def rag_node(state: SchedulerState):
    """Verifica i vincoli custom contro il regolamento ospedaliero e rimuove quelli non conformi."""
    print("-> [NODE] rag_node")
    prefs = state["preferences"]
    report = rag_agent.verify_compliance(prefs)

    if report.get("error"):
        count = state.get("error_count", 0) + 1
        print(f"   [RAG] Errore LLM (tentativo {count}): {report['error']}")
        return {"violations": [report["error"]], "error_count": count}

    verdicts = report.get("custom_constraint_verdicts", {})
    workers_dict = prefs.get("workers", prefs)

    for worker_id, data in workers_dict.items():
        if "soft_constraints" not in data:
            continue
        filtered = []
        for sc in data["soft_constraints"]:
            if sc.get("type") != "custom":
                filtered.append(sc)
                continue
            
            # Fallback se l'LLM ha salvato il testo in description invece di natural_language
            if not sc.get("natural_language") and sc.get("description"):
                sc["natural_language"] = sc["description"]

            # Controlliamo il verdetto del RAG per questo vincolo
            matched = None
            for v in verdicts.get(worker_id, []):
                v_text = v.get("natural_language") or v.get("description") or ""
                sc_text = sc.get("natural_language") or sc.get("description") or ""
                if v_text.strip() == sc_text.strip():
                    matched = v
                    break

            approved = bool(matched.get("approved")) if matched else False
            reason = matched.get("reason", "") if matched else ""
            law = matched.get("law", "") if matched else ""

            # Se la reason non cita esplicitamente la legge, la costruiamo noi
            if not approved and law and law not in reason:
                reason = f"Violates {law}: {reason}".strip(" :")

            sc_text = sc.get("natural_language") or sc.get("description") or ""
            verdict_payload = {
                "event": "rag_verdict",
                "worker_id": worker_id,
                "natural_language": sc_text,
                "approved": approved,
                "reason": reason,
                "law": law,
            }
            print(json.dumps(verdict_payload, ensure_ascii=False))

            if approved:
                filtered.append(sc)
        data["soft_constraints"] = filtered

    # Successo: resetta error_count per la fase successiva
    return {"preferences": prefs, "violations": [], "error_count": 0}


def draft_node(state: SchedulerState):
    """Genera la turnazione usando DraftingAgent (OR-Tools + LLM)."""
    print("-> [NODE] draft_node")
    prefs = state["preferences"]
    workers_dict = prefs.get("workers", prefs)
    num_workers = len(workers_dict)

    has_specialist = False
    for w in workers_dict.values():
        if w.get("role") == "specialist":
            has_specialist = True
            break

    try:
        schedule = drafting_agent.draft(prefs, num_workers=num_workers, num_days=NUM_DAYS, has_specialist=has_specialist)
    except Exception as e:
        count = state.get("error_count", 0) + 1
        print(f"   [DRAFT] Errore (tentativo {count}): {e}")
        return {"violations": [str(e)], "error_count": count}

    # Se il solver non trova una soluzione, è matematicamente impossibile
    if not schedule.get("assignments"):
        print("   [DRAFT] FATAL: Nessuna soluzione trovata (matematicamente impossibile).")
        return {"violations": ["INFEASIBLE"], "error_count": MAX_RETRIES}

    # Successo: resetta error_count per la fase successiva
    return {"schedule": schedule, "violations": [], "error_count": 0}


def verify_node(state: SchedulerState):
    """Verifica deterministicamente i vincoli hard sulla turnazione generata."""
    print("-> [NODE] verify_node")
    prefs = state["preferences"]
    workers_dict = prefs.get("workers", prefs)

    has_specialist = False
    for w in workers_dict.values():
        if w.get("role") == "specialist":
            has_specialist = True
            break

    result = verification_agent.verify_schedule(
        state["schedule"], prefs, num_days=NUM_DAYS, has_specialist=has_specialist
    )

    if not result["is_valid"]:
        print(f"   [VERIFY] FATAL: Violazioni deterministiche rilevate, impossibile risolvere.")
        return {"violations": result["violations"], "error_count": MAX_RETRIES}

    # Successo: resetta error_count per la fase successiva
    return {"violations": [], "error_count": 0}


def fairness_node(state: SchedulerState):
    """Valuta l'equità della turnazione e identifica il medico più svantaggiato."""
    print("-> [NODE] fairness_node")
    worst_worker, metrics = fairness_agent.evaluate(state["schedule"], state["preferences"])
    return {
        "fairness_scores": metrics.get("individual_payoffs", {}),
        "worst_worker": worst_worker,
        "prev_min_score": metrics.get("rawlsian_minimum_payoff", 0),
        "fairness_gap": metrics.get("fairness_envy_gap", 0)
    }


def refine_node(state: SchedulerState):
    """
    Fase di refinement: boosta i pesi del worst_worker (duplicandoli) senza
    rilanciare il solver. Il controllo torna a `draft_node`, che rigenera la
    turnazione con i nuovi pesi. Questo rende esplicito il loop:
        fairness -> refine -> draft -> verify -> fairness -> ...
    """
    print(f"-> [NODE] refine_node (iterazione {state.get('iteration', 0) + 1})")
    boosted_prefs = copy.deepcopy(state["preferences"])
    workers_dict = boosted_prefs.get("workers", boosted_prefs)
    worst_worker = state.get("worst_worker")

    if worst_worker and worst_worker in workers_dict:
        worker_data = workers_dict[worst_worker]
        if "shift_weights" in worker_data:
            # Clamp ai limiti dello schema Pydantic [-10, 10]
            worker_data["shift_weights"] = [
                max(min(w * 2, 10), -10) for w in worker_data["shift_weights"]
            ]
        for sc in worker_data.get("soft_constraints", []):
            if "weight" in sc:
                # Clamp ai limiti dello schema Pydantic [-10, 10]
                sc["weight"] = max(min(sc["weight"] * 2, 10), -10)
        print(f"   [REFINE] Pesi raddoppiati per worst_worker '{worst_worker}'.")
    else:
        print(f"   [REFINE] WARN: worst_worker '{worst_worker}' non trovato tra i workers.")

    # Non rilanciamo qui il solver: ritorniamo a draft_node per rigenerare.
    # Salviamo schedule e gap correnti per eventuale rollback se il refinement peggiora.
    return {
        "preferences": boosted_prefs,
        "violations": [],
        "error_count": 0,
        "iteration": state.get("iteration", 0) + 1,
        "prev_schedule": state.get("schedule"),
        "prev_fairness_gap": state.get("fairness_gap"),
    }


# -----------------------------------------------------------------------------
# ROUTING (Bivi condizionali)
# -----------------------------------------------------------------------------

def should_retry_parse(state: SchedulerState) -> str:
    if state.get("violations"):
        if state.get("error_count", 0) < MAX_RETRIES:
            print(f"   [RETRY] worker_node - tentativo {state['error_count']}")
            return "worker_node"
        print("   [FATAL] Parsing fallito dopo 3 tentativi. Termino.")
        return END
    return "rag_node"


def should_retry_rag(state: SchedulerState) -> str:
    if state.get("violations"):
        if state.get("error_count", 0) < MAX_RETRIES:
            print(f"   [RETRY] rag_node - tentativo {state['error_count']}")
            return "rag_node"
        print("   [FATAL] RAG fallito dopo 3 tentativi. Termino.")
        return END
    return "draft_node"


def should_retry_draft(state: SchedulerState) -> str:
    if state.get("violations"):
        if state.get("error_count", 0) < MAX_RETRIES:
            print(f"   [RETRY] draft_node - tentativo {state['error_count']}")
            return "draft_node"
        print("   [FATAL] Draft fallito dopo 3 tentativi. Termino.")
        return END
    return "verify_node"


def check_verification(state: SchedulerState) -> str:
    if state.get("violations"):
        print("   [FATAL] Violazioni hard irrisolvibili. Termino.")
        return END
    return "fairness_node"


def decide_refinement(state: SchedulerState) -> str:
    has_worst = bool(state.get("worst_worker"))
    under_limit = state.get("iteration", 0) < 3
    gap = state.get("fairness_gap", 0)
    prev_gap = state.get("prev_fairness_gap")
    
    # Se siamo in un ciclo di refinement e il gap è peggiorato, ripristina
    # la schedule precedente e fermati.
    if prev_gap is not None and gap > prev_gap:
        print(f"   [ROUTING] Fairness gap peggiorato ({prev_gap} → {gap}). Ripristino schedule precedente.")
        return "revert_node"
    
    # Se il gap tra il medico più soddisfatto e quello meno soddisfatto è maggiore di 10,
    # consideriamo la turnazione iniqua e proviamo a rifinirla.
    if has_worst and gap > 10 and under_limit:
        print(f"   [ROUTING] Fairness gap alto ({gap}). Avvio refinement.")
        return "refine_node"
        
    print(f"   [ROUTING] Fairness gap accettabile ({gap}) o limite raggiunto. Fine.")
    return END


def revert_node(state: SchedulerState):
    """Ripristina la schedule precedente quando il refinement peggiora il gap."""
    print(f"-> [NODE] revert_node: ripristino schedule pre-refinement")
    prev_schedule = state.get("prev_schedule")
    prev_gap = state.get("prev_fairness_gap")
    if prev_schedule:
        print(f"   [REVERT] Fairness gap ripristinato a {prev_gap}.")
        return {
            "schedule": prev_schedule,
            "fairness_gap": prev_gap,
        }
    print("   [REVERT] WARN: nessuna schedule precedente disponibile.")
    return {}


def should_retry_refine(state: SchedulerState) -> str:
    if state.get("violations"):
        if state.get("error_count", 0) < MAX_RETRIES:
            print(f"   [RETRY] refine_node - tentativo {state['error_count']}")
            return "refine_node"
        print("   [FATAL] Refine fallito dopo 3 tentativi. Termino.")
        return END
    # Torna a draft_node per rigenerare la turnazione con i pesi boostati
    return "draft_node"


# -----------------------------------------------------------------------------
# COSTRUZIONE DEL GRAFO
# -----------------------------------------------------------------------------

def create_scheduler_graph():
    workflow = StateGraph(SchedulerState)

    workflow.add_node("worker_node", worker_node)
    workflow.add_node("rag_node", rag_node)
    workflow.add_node("draft_node", draft_node)
    workflow.add_node("verify_node", verify_node)
    workflow.add_node("fairness_node", fairness_node)
    workflow.add_node("refine_node", refine_node)
    workflow.add_node("revert_node", revert_node)

    workflow.add_edge(START, "worker_node")
    workflow.add_conditional_edges("worker_node", should_retry_parse)
    workflow.add_conditional_edges("rag_node", should_retry_rag)
    workflow.add_conditional_edges("draft_node", should_retry_draft)      # Nuovo: retry su errore solver
    workflow.add_conditional_edges("verify_node", check_verification)     # Retry su violazioni hard → draft
    workflow.add_conditional_edges("fairness_node", decide_refinement)
    workflow.add_conditional_edges("refine_node", should_retry_refine)    # Nuovo: retry su errore refine
    workflow.add_edge("revert_node", END)

    return workflow.compile()
