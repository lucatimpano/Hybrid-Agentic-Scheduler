import json
import copy
from dataclasses import dataclass
from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langchain_google_genai import ChatGoogleGenerativeAI
from src.models.ortools_wrappers import SmartSchedulerWrapper
from src.models.schemas import REQUIRED_SHIFTS_PER_MONTH
from src.agents import prompts


@dataclass
class SchedulerContext:
    """Contesto immutabile passato all'agente durante ogni invocazione."""
    preferences: dict
    num_workers: int
    num_days: int
    has_specialist: bool


class DraftingAgent:
    """
    Agente responsabile della Fase 2 (draft) e della Fase 4 (refine) del ciclo di scheduling.

    Usa un LLM come orchestratore ReAct per applicare i vincoli al modello CP-SAT e risolvere.
    I vincoli soft custom (type='custom') vengono gestiti tramite generazione di codice on-demand.
    """


    #  INITIALIZER                                                         


    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0)
        self.custom_constraints_cache = {}  # Cache: (worker_idx, natural_language_text) -> generated_code


    #  PRIVATE: TOOL BUILDER                                               


    def _build_scheduler_tools(self, wrapper: SmartSchedulerWrapper) -> list:
        """
        Builds the list of LangChain tools for the scheduling agent.
        """
        # Capture `self` (the DraftingAgent instance) in the closure so the inner
        # tools can call self._apply_custom_soft_constraints without scope issues.
        agent = self

        @tool(return_direct=False)
        def apply_all_constraints(runtime: ToolRuntime[SchedulerContext]) -> str:
            """
            Applies ALL constraints to the CP-SAT model in a single call:
            - General hard constraints (one shift/day, max 36h/week, post-night rest, 25 shifts/month)
            - Coverage constraint (2 workers per shift, or 1 specialist if has_specialist=True)
            - Personal hard constraints (fixed days off requested by workers)
            - Custom soft constraints generated on-demand by the LLM
            - Soft constraints and Maximin fairness objective
            """
            print("[DraftingAgent LLM -> Tool] Invoking apply_all_constraints...")

            # General hard constraints
            print("  Applying general system constraints (rest, max hours, monthly shifts)...")
            wrapper.add_single_shift_per_day()
            wrapper.check_month_sum(REQUIRED_SHIFTS_PER_MONTH)
            wrapper.add_consecutive_shifts_constraint()
            wrapper.add_no_work_after_night()
            wrapper.add_36_hours_a_week()

            # Coverage constraint (Case A: standard only, Case B: with specialists)
            print("  Applying shift coverage constraints...")
            if runtime.context.has_specialist:
                workers_dict = runtime.context.preferences.get("workers", runtime.context.preferences)
                worker_roles = {
                    w_id: p.get("role", "standard")
                    for w_id, p in workers_dict.items()
                }
                wrapper.add_specialist_coverage_constraint(worker_roles)
            else:
                wrapper.add_coverage_constraint()

            # Personal hard constraints (fixed days off, weekday restrictions)
            print("  Applying personal hard constraints (days off, vacations)...")
            workers_dict = runtime.context.preferences.get("workers", runtime.context.preferences)
            for worker_id, data in workers_dict.items():
                for hc in data.get("hard_constraints", []):
                    if hc.get("type") == "free_date":
                        wrapper.add_hard_constraint_free_date(worker_id, hc.get("value"))
                    elif hc.get("type") == "free_weekday":
                        wrapper.add_hard_constraint_free_weekday(worker_id, hc.get("value"))

            # Custom soft constraints: generate OR-Tools code on-demand for non-standard preferences.
            # MUST be called BEFORE maximize_fairness_objective so generated terms are included.
            agent._apply_custom_soft_constraints(wrapper, runtime.context.preferences)

            # Soft constraints + Maximin fairness objective
            print("  Building Maximin fairness objective...")
            wrapper.maximize_fairness_objective(runtime.context.preferences)

            print("[DraftingAgent Tool -> LLM] All constraints applied to OR-Tools model.")
            return (
                "All constraints applied: general hard, coverage, personal hard, "
                "standard soft, custom soft, and Maximin fairness objective."
            )

        @tool(return_direct=True)
        def solve_and_export() -> dict:
            """Solves the CP-SAT model with all constraints already applied and returns the final schedule."""
            print("\n[DraftingAgent LLM -> Tool] Invoking solve_and_export...")
            print("  Running CP-SAT solver (this may take a few seconds)...")
            wrapper.solve()
            print("[DraftingAgent Tool -> LLM] Model solved. Returning schedule to orchestrator.")
            return wrapper.export_schedule_as_dict()

        return [apply_all_constraints, solve_and_export]


    #  PRIVATE: CUSTOM SOFT CONSTRAINT GENERATOR                          


    def _apply_custom_soft_constraints(self, wrapper: SmartSchedulerWrapper, preferences: dict) -> None:
        """
        Scans worker preferences for soft constraints of type 'custom'.
        For each one found, calls the LLM to generate the corresponding OR-Tools Python
        snippet and registers it in the wrapper for execution inside maximize_fairness_objective.

        The generated code is executed via exec() with the following variables in scope:
          - satisfaction_terms : list  → append penalty/reward terms here
          - w                  : int   → current worker index
          - self               : SmartSchedulerWrapper (access to self.x, self.model)
          - num_days           : int
          - num_shifts         : int
        """
        workers_dict = preferences.get("workers", preferences)
        for worker_id, data in workers_dict.items():
            try:
                worker_idx = int(worker_id.split("_")[1])
            except (IndexError, ValueError):
                continue

            custom_constraints = [
                sc for sc in data.get("soft_constraints", [])
                if sc.get("type") == "custom"
            ]

            if not custom_constraints:
                continue

            for sc in custom_constraints:
                natural_language = sc.get("natural_language") or sc.get("description") or ""
                weight = sc.get("weight", 1)

                if not natural_language:
                    continue

                cache_key = (worker_idx, natural_language)
                if cache_key in self.custom_constraints_cache:
                    generated_code = self.custom_constraints_cache[cache_key]
                    print(f"  [CustomConstraint] Using cached code for {worker_id}: '{natural_language}'")
                    print(f"  [CODE] BEGIN {worker_id} | {natural_language} | weight={weight} | cached")
                    print(generated_code)
                    print("  [CODE] END")
                    # Prepende la definizione del peso corrente (potenzialmente raddoppiato)
                    code_with_weight = f"weight = {weight}\n{generated_code}"
                    wrapper.custom_soft_terms.setdefault(worker_idx, []).append(code_with_weight)
                    continue

                print(f"  [CustomConstraint] Generating code for {worker_id}: '{natural_language}'")

                try:
                    response = self.llm.invoke([
                        ("system", prompts.CUSTOM_CONSTRAINT_SYSTEM),
                        ("human", prompts.custom_constraint_user(worker_idx, natural_language, weight))
                    ])
                    content = response.content
                    if isinstance(content, list):
                        content = content[0].get("text", str(content[0])) if isinstance(content[0], dict) else str(content[0])
                    generated_code = content.strip()

                    # Salva il codice generato grezzo in cache
                    self.custom_constraints_cache[cache_key] = generated_code

                    # Registra il codice con il peso corrente prependato
                    code_with_weight = f"weight = {weight}\n{generated_code}"
                    wrapper.custom_soft_terms.setdefault(worker_idx, []).append(code_with_weight)
                    print(f"  [CustomConstraint] Code registered and cached for {worker_id}.")
                    print(f"  [CODE] BEGIN {worker_id} | {natural_language} | weight={weight}")
                    print(generated_code)
                    print("  [CODE] END")

                except Exception as e:
                    print(f"  [WARN] Custom constraint generation for {worker_id} failed: {e}")


    #  PUBLIC: DRAFT (Phase 2)                                            


    def draft(
        self,
        preferences: dict,
        num_workers: int,
        num_days: int,
        has_specialist: bool = False,
        worst_worker: str | None = None,
    ) -> dict:
        """
        Phase 2 / 4: Generates or refines the schedule draft.
        If worst_worker is provided (refinement), boosts that worker's
        preference weights to orient the Maximin objective toward them.
        """
        boosted_prefs = preferences
        system_prompt = prompts.SCHEDULER_SYSTEM
        user_msg = "Generate the initial schedule draft."

        if worst_worker:
            print(f"   [DRAFT] Refinement mode: boosting weights for '{worst_worker}'")
            boosted_prefs = copy.deepcopy(preferences)
            workers_dict = boosted_prefs.get("workers", boosted_prefs)
            if worst_worker in workers_dict:
                worker_data = workers_dict[worst_worker]
                if "shift_weights" in worker_data:
                    clamped_weights = []
                    for w in worker_data["shift_weights"]:
                        doubled = w * 2
                        if doubled > 10:
                            doubled = 10
                        elif doubled < -10:
                            doubled = -10
                        clamped_weights.append(doubled)
                    worker_data["shift_weights"] = clamped_weights
                for sc in worker_data.get("soft_constraints", []):
                    if "weight" in sc:
                        sc["weight"] = max(min(sc["weight"] * 2, 10), -10)
            system_prompt = prompts.refine_system(worst_worker)
            user_msg = f"Regenerate the schedule prioritizing {worst_worker}."

        wrapper = SmartSchedulerWrapper(num_workers, num_days)
        tools = self._build_scheduler_tools(wrapper)
        context = SchedulerContext(boosted_prefs, num_workers, num_days, has_specialist)

        agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            context_schema=SchedulerContext
        )

        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_msg}]},
            context=context
        )

        last_msg = result["messages"][-1]
        if hasattr(last_msg, "content") and isinstance(last_msg.content, str):
            try:
                return json.loads(last_msg.content)
            except Exception:
                pass
        return result
