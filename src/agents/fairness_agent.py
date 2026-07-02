
import math
from datetime import datetime
from collections import defaultdict
from src.models.schemas import Schedule, AllPreferences, WorkerPreferences
class FairnessAgent:
    """
    Agente per il calcolo dell'equità basato su modelli della Teoria dei Giochi.
    Valuta la turnazione applicando concetti di Giustizia Distributiva (Rawls),
    Scelta Sociale (Nash Welfare) ed Envy-Freeness (Fairness Gap).
    """
    def evaluate(self, schedule_dict: dict, preferences_dict: dict) -> tuple[str, dict]:
        """
        Analizza la turnazione e restituisce il lavoratore critico, la mappa dei payoff 
        e i descrittori teorici di equità (Maximin, Nash Welfare, Fairness Gap).
        """
        # Validazione Pydantic per l'integrità dei dati dello schedule e delle preferenze
        schedule_obj = Schedule.model_validate(schedule_dict)
        preferences_obj = AllPreferences.model_validate(preferences_dict)
        
        # Dizionario dei Payoff dei singoli giocatori (lavoratori)
        scores = {}
        for worker_id, prefs in preferences_obj.workers.items():
            scores[worker_id] = self._compute_score(worker_id, schedule_obj, prefs)
            
        if not scores:
            return "", {}
            
        # 1. CRITERIO DEL MAXIMIN DI RAWLS (Giustizia Distributiva)
        worst_worker = min(scores, key=scores.get)
        worst_payoff = scores[worst_worker]
        
        # 2. FAIRNESS EQUILIBRIUM GAP (Distanza dall'Envy-Freeness)
        best_payoff = max(scores.values())
        fairness_gap = best_payoff - worst_payoff
        
        # 3. NASH WELFARE SCORE (Ottimizzazione Sociale Coerente)
        shifted_product = 1.0
        for s in scores.values():
            shifted_product *= max(1, s + 15) 
        nash_welfare = round(math.pow(shifted_product, 1 / len(scores)), 2)
        # Costruiamo un report esteso dei metadati teorici
        game_theory_metadata = {
            "individual_payoffs": scores,
            "rawlsian_maximin_worker": worst_worker,
            "rawlsian_minimum_payoff": worst_payoff,
            "fairness_envy_gap": fairness_gap,
            "nash_welfare_score": nash_welfare
        }
        
        print("\n=== GAME THEORY ANALYSIS REPORT ===")
        print(f"• Rawlsian Maximin (Worst Player Payoff): {worst_payoff} ({worst_worker})")
        print(f"• Envy-Free Fairness Gap (Delta Max-Min): {fairness_gap}")
        print(f"• Nash Social Welfare (Geometric Balance): {nash_welfare}")
        print("===================================\n")
        
        return worst_worker, game_theory_metadata
    def _compute_score(self, worker_id: str, schedule: Schedule, prefs: WorkerPreferences) -> int:
        """
        Calcola il payoff matematico (punteggio di utilità) di un singolo giocatore.
        """
        score = 0
        worker_assignments = schedule.for_worker(worker_id)
        
        # Valutazione della funzione di utilità lineare sui pesi dei turni
        morning_weight = prefs.shift_weights[0]
        afternoon_weight = prefs.shift_weights[1]
        night_weight = prefs.shift_weights[2]
        
        for assignment in worker_assignments:
            if assignment.shift == "Morning":
                score += morning_weight
            elif assignment.shift == "Afternoon":
                score += afternoon_weight
            elif assignment.shift == "Night":
                score += night_weight
        # Raggruppamento temporale in sotto-insiemi settimanali univoci per anno e settimana
        shifts_by_week = defaultdict(list)
        for a in worker_assignments:
            dt = datetime.strptime(a.date, "%Y-%m-%d")
            # FIX LUCA: Estraiamo anno e numero settimana per evitare collisioni interannuali
            year, week_number, _ = dt.isocalendar()
            shifts_by_week[(year, week_number)].append(a.shift)
        # Penalità e Premi sui Vincoli Flessibili (Soft Constraints)
        for soft in prefs.soft_constraints:
            if soft.type == "free_date":
                has_assignment_on_date = any(a.date == soft.value for a in worker_assignments)
                if not has_assignment_on_date:
                    score += abs(soft.weight)
                else:
                    score -= abs(soft.weight)
            elif soft.type == "avoid_shift_date":
                has_bad_shift = any(a.date == soft.value and a.shift == soft.shift for a in worker_assignments)
                if has_bad_shift:
                    score -= abs(soft.weight)
                else:
                    score += abs(soft.weight)
            elif soft.type == "max_shifts_per_week":
                max_allowed = int(soft.value)
                violated_weeks = 0
                #FIX CONSEGUENTE: Adesso week_key è una tupla (year, week_number)
                for week_key, shifts in shifts_by_week.items():
                    if len(shifts) > max_allowed:
                        violated_weeks += 1
                if violated_weeks > 0:
                    score -= abs(soft.weight) * violated_weeks
                else:
                    score += abs(soft.weight)
            elif soft.type == "avoid_afternoon_and_night_same_week":
                combinations_violated = 0
                # FIX CONSEGUENTE: Adesso week_key è una tupla (year, week_number)
                for week_key, shifts in shifts_by_week.items():
                    if "Afternoon" in shifts and "Night" in shifts:
                        combinations_violated += 1
                if combinations_violated > 0:
                    score -= abs(soft.weight) * combinations_violated
                else:
                    score += abs(soft.weight)
                    
        return score
