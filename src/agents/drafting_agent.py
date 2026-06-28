from dataclasses import dataclass
from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langchain_google_genai import ChatGoogleGenerativeAI
from src.models.ortools_wrappers import SmartSchedulerWrapper
from src.models.schemas import REQUIRED_SHIFTS_PER_MONTH

@dataclass
class SchedulerContext:
    """Contesto immutabile passato all'agente durante ogni invocazione."""
    preferences: dict
    num_workers: int
    num_days: int
    has_specialist: bool

def build_scheduler_tools(wrapper: SmartSchedulerWrapper) -> list:
    
    @tool
    def apply_general_hard_constraints() -> str:
        """Applica i vincoli rigidi (hard) di base (singolo turno, 36 ore massime, 15 turni mensili, riposo)."""
        wrapper.add_single_shift_per_day()
        wrapper.check_month_sum(REQUIRED_SHIFTS_PER_MONTH)
        wrapper.add_consecutive_shifts_constraint()
        wrapper.add_no_work_after_night()
        wrapper.add_36_hours_a_week()
        return "Vincoli hard generali applicati."

    @tool
    def apply_coverage_constraint(runtime: ToolRuntime[SchedulerContext]) -> str:
        """Applica il vincolo di copertura per i turni."""
        if runtime.context.has_specialist:
            worker_roles = {}
            for w_id, p in runtime.context.preferences.items():
                worker_roles[w_id] = p.get("role", "standard")
            
            wrapper.add_specialist_coverage_constraint(worker_roles)
            return "Copertura specialistica (minimo 1 specialista per turno) applicata."
        else:
            wrapper.add_coverage_constraint()
            return "Copertura standard (minimo 2 medici per turno) applicata."

    @tool
    def apply_personal_hard_constraints(runtime: ToolRuntime[SchedulerContext]) -> str:
        """Applica i vincoli rigidi personali (es. ferie e giorni liberi fissi) richiesti dai medici."""
        for worker_id, data in runtime.context.preferences.items():
            for hc in data.get("hard_constraints", []):
                if hc.get("type") == "free_date":
                    wrapper.add_hard_constraint_free_date(worker_id, hc.get("value"))
                elif hc.get("type") == "free_weekday":
                    wrapper.add_hard_constraint_free_weekday(worker_id, hc.get("value"))
        return "Vincoli hard personali applicati."

    @tool
    def apply_soft_constraints(runtime: ToolRuntime[SchedulerContext]) -> str:
        """Applica i vincoli flessibili (soft) e imposta la funzione obiettivo."""
        wrapper.maximize_fairness_objective(runtime.context.preferences)
        return "Vincoli soft e funzione obiettivo Maximin applicati."

    @tool(return_direct=True)
    def solve_and_export() -> dict:
        """Risolve il modello CP-SAT e ritorna la turnazione finale."""
        wrapper.solve()
        return wrapper.export_schedule_as_dict()

    return [
        apply_general_hard_constraints,
        apply_coverage_constraint,
        apply_personal_hard_constraints,
        apply_soft_constraints,
        solve_and_export
    ]

class DraftingAgent:
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)

    def draft(self, preferences: dict, num_workers: int, num_days: int, has_specialist: bool = False) -> dict:
        """
        Fase 2: Genera la bozza iniziale della turnazione.
        """
        wrapper = SmartSchedulerWrapper(num_workers, num_days)
        tools = build_scheduler_tools(wrapper)
        context = SchedulerContext(preferences, num_workers, num_days, has_specialist)
        
        system_prompt = (
            "You are an expert hospital schedule optimization agent.\n"
            "Your task is to construct and solve a CP-SAT scheduling model by calling tools.\n"
            "You MUST call these tools in the following EXACT logical order:\n"
            "1. apply_general_hard_constraints\n"
            "2. apply_coverage_constraint\n"
            "3. apply_personal_hard_constraints\n"
            "4. apply_soft_constraints\n"
            "5. solve_and_export\n"
        )
        
        agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            context_schema=SchedulerContext
        )
        
        result = agent.invoke(
            {"messages": [{"role": "user", "content": "Genera la prima bozza della turnazione."}]},
            context=context
        )
        
        # Grazie a @tool(return_direct=True) su solve_and_export, result contiene direttamente il dict della turnazione
        # sotto forma di stringa JSON nell'ultimo ToolMessage
        last_msg = result["messages"][-1]
        import json
        if hasattr(last_msg, "content") and isinstance(last_msg.content, str):
            try:
                return json.loads(last_msg.content)
            except:
                pass
        return result

    def refine(self, preferences: dict, current_schedule: dict, worst_worker: str, num_workers: int, num_days: int, has_specialist: bool = False) -> dict:
        """
        Fase 4: Migliora la turnazione cercando di favorire il medico più scontento (worst_worker).
        """
        import copy
        boosted_prefs = copy.deepcopy(preferences)
        
        # Aumentiamo artificialmente i pesi del medico più scontento per forzare il solutore a dargli priorità
        if worst_worker in boosted_prefs:
            worker_data = boosted_prefs[worst_worker]
            
            if "shift_weights" in worker_data:
                worker_data["shift_weights"] = [w * 2 for w in worker_data["shift_weights"]]
                
            for sc in worker_data.get("soft_constraints", []):
                if "weight" in sc:
                    sc["weight"] = max(min(sc["weight"] * 2, 100), -100)
                    
        wrapper = SmartSchedulerWrapper(num_workers, num_days)
        tools = build_scheduler_tools(wrapper)
        context = SchedulerContext(boosted_prefs, num_workers, num_days, has_specialist)
        
        system_prompt = (
            f"You are an expert hospital schedule optimization agent.\n"
            f"We need to refine the schedule because worker {worst_worker} is unsatisfied.\n"
            "You MUST call these tools in the following EXACT logical order to regenerate the schedule:\n"
            "1. apply_general_hard_constraints\n"
            "2. apply_coverage_constraint\n"
            "3. apply_personal_hard_constraints\n"
            "4. apply_soft_constraints\n"
            "5. solve_and_export\n"
        )
        
        agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            context_schema=SchedulerContext
        )
        
        result = agent.invoke(
            {"messages": [{"role": "user", "content": f"Rifai la turnazione dando priorità a {worst_worker}."}]},
            context=context
        )
        
        last_msg = result["messages"][-1]
        import json
        if hasattr(last_msg, "content") and isinstance(last_msg.content, str):
            try:
                return json.loads(last_msg.content)
            except:
                pass
        return result
