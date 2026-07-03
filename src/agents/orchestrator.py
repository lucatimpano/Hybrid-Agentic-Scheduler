from datetime import datetime
from langgraph.graph import StateGraph, START, END

from src.models.schemas import SchedulerState, SCHEDULE_START, SCHEDULE_END
from src.agents.workers_agent import WorkersAgent
from src.agents.rag_agent import RagAgent
from src.agents.drafting_agent import DraftingAgent
from src.agents.verification_agent import VerificationAgent
from src.agents.fairness_agent import FairnessAgent

# Calcoliamo NUM_DAYS a partire dalle date definite in schemas.py
start_dt = datetime.strptime(SCHEDULE_START, "%Y-%m-%d")
end_dt = datetime.strptime(SCHEDULE_END, "%Y-%m-%d")
NUM_DAYS = (end_dt - start_dt).days + 1

# Inizializzazione globale degli agenti (una sola volta)
workers_agent = WorkersAgent()
rag_agent = RagAgent()
drafting_agent = DraftingAgent()
verification_agent = VerificationAgent()
fairness_agent = FairnessAgent()

# -----------------------------------------------------------------------------
# NODI
# -----------------------------------------------------------------------------

def parse_node(state: SchedulerState):
    """Estrae le preferenze dal testo libero usando WorkersAgent."""
    print("-> [NODE] parse_node")
    try:
        prefs = workers_agent.parse_preferences(state["preferences"])
        return {"preferences": prefs, "violations": [], "iteration": 0}
    except Exception as e:
        return {"violations": [str(e)]}


def rag_node(state: SchedulerState):
    """Verifica i vincoli custom contro il regolamento ospedaliero e rimuove quelli non conformi."""
    print("-> [NODE] rag_node")
    prefs = state["preferences"]
    report = rag_agent.verify_compliance(prefs)

    if report.get("error"):
        print(f"   [RAG] Errore LLM: {report['error']}")
        return {}  # Lo stato non cambia, il bivio gestirà il retry

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
            # Controlliamo il verdetto del RAG per questo vincolo
            approved = any(
                v.get("natural_language") == sc.get("natural_language") and v.get("approved")
                for v in verdicts.get(worker_id, [])
            )
            if approved:
                filtered.append(sc)
            else:
                print(f"   [RAG] Vincolo bocciato per {worker_id}: '{sc.get('natural_language')}'")
        data["soft_constraints"] = filtered

    return {"preferences": prefs}


def draft_node(state: SchedulerState):
    """Genera la turnazione usando DraftingAgent (OR-Tools + LLM)."""
    print("-> [NODE] draft_node")
    prefs = state["preferences"]
    workers_dict = prefs.get("workers", prefs)
    num_workers = len(workers_dict)
    has_specialist = any(w.get("role") == "specialist" for w in workers_dict.values())

    schedule = drafting_agent.draft(prefs, num_workers=num_workers, num_days=NUM_DAYS, has_specialist=has_specialist)
    return {"schedule": schedule, "violations": []}


def verify_node(state: SchedulerState):
    """Verifica deterministicamente i vincoli hard sulla turnazione generata."""
    print("-> [NODE] verify_node")
    prefs = state["preferences"]
    workers_dict = prefs.get("workers", prefs)
    has_specialist = any(w.get("role") == "specialist" for w in workers_dict.values())

    result = verification_agent.verify_schedule(
        state["schedule"], prefs, num_days=NUM_DAYS, has_specialist=has_specialist
    )

    if not result["is_valid"]:
        print(f"   [VERIFY] Violazioni rilevate: {len(result['violations'])}")

    return {"violations": result["violations"]}


def fairness_node(state: SchedulerState):
    """Valuta l'equità della turnazione e identifica il medico più svantaggiato."""
    print("-> [NODE] fairness_node")
    worst_worker, metrics = fairness_agent.evaluate(state["schedule"], state["preferences"])
    return {
        "fairness_scores": metrics.get("individual_payoffs", {}),
        "worst_worker": worst_worker,
        "prev_min_score": metrics.get("rawlsian_minimum_payoff", 0)
    }


def refine_node(state: SchedulerState):
    """Rigenera la turnazione favorendo il medico più svantaggiato."""
    print(f"-> [NODE] refine_node (iterazione {state.get('iteration', 0) + 1})")
    prefs = state["preferences"]
    workers_dict = prefs.get("workers", prefs)
    num_workers = len(workers_dict)
    has_specialist = any(w.get("role") == "specialist" for w in workers_dict.values())

    schedule = drafting_agent.refine(
        preferences=prefs,
        current_schedule=state["schedule"],
        worst_worker=state["worst_worker"],
        num_workers=num_workers,
        num_days=NUM_DAYS,
        has_specialist=has_specialist
    )
    return {"schedule": schedule, "violations": [], "iteration": state.get("iteration", 0) + 1}


# -----------------------------------------------------------------------------
# ROUTING (Bivi condizionali)
# -----------------------------------------------------------------------------

def should_retry_parse(state: SchedulerState) -> str:
    if state.get("violations"):
        print("   [FATAL] Parsing fallito. Termino.")
        return END
    return "rag_node"


def should_retry_rag(state: SchedulerState) -> str:
    # Il RAG non modifica le violations, proseguiamo sempre al draft
    return "draft_node"


def check_verification(state: SchedulerState) -> str:
    if state.get("violations"):
        print("   [FATAL] Violazioni hard irrisolvibili. Termino.")
        return END
    return "fairness_node"


def decide_refinement(state: SchedulerState) -> str:
    has_worst = bool(state.get("worst_worker"))
    under_limit = state.get("iteration", 0) < 3
    if has_worst and under_limit:
        return "refine_node"
    return END


# -----------------------------------------------------------------------------
# COSTRUZIONE DEL GRAFO
# -----------------------------------------------------------------------------

def create_scheduler_graph():
    workflow = StateGraph(SchedulerState)

    workflow.add_node("parse_node", parse_node)
    workflow.add_node("rag_node", rag_node)
    workflow.add_node("draft_node", draft_node)
    workflow.add_node("verify_node", verify_node)
    workflow.add_node("fairness_node", fairness_node)
    workflow.add_node("refine_node", refine_node)

    workflow.add_edge(START, "parse_node")
    workflow.add_conditional_edges("parse_node", should_retry_parse)
    workflow.add_conditional_edges("rag_node", should_retry_rag)
    workflow.add_edge("draft_node", "verify_node")
    workflow.add_conditional_edges("verify_node", check_verification)
    workflow.add_conditional_edges("fairness_node", decide_refinement)
    workflow.add_edge("refine_node", "verify_node")

    return workflow.compile()
