from datetime import datetime
from collections import defaultdict
from src.models.schemas import Schedule, AllPreferences, WorkerPreferences

class FairnessAgent:
    """
    Agente per il calcolo deterministico dell'equità della turnazione.
    Valuta la soddisfazione di ogni lavoratore in base alle sue preferenze e pesi.
    """

    def evaluate(self, schedule_dict: dict, preferences_dict: dict) -> tuple[str, dict]:
        """
        Calcola il livello di soddisfazione per ciascun lavoratore.
        Restituisce l'ID del lavoratore più penalizzato e un dizionario con i punteggi di tutti i lavoratori.
        """
        # Trasformiamo i dizionari grezzi negli oggetti Pydantic validati per lavorare in sicurezza
        schedule_obj = Schedule.model_validate(schedule_dict)
        preferences_obj = AllPreferences.model_validate(preferences_dict)
        
        scores = {}
        
        # Calcoliamo il punteggio per ogni lavoratore presente nelle preferenze
        for worker_id, prefs in preferences_obj.workers.items():
            scores[worker_id] = self._compute_score(worker_id, schedule_obj, prefs)
            
        if not scores:
            return "", {}
            
        # Trova il lavoratore più penalizzato
        worst_worker = min(scores, key=scores.get)
        
        return worst_worker, scores

    def _compute_score(self, worker_id: str, schedule: Schedule, prefs: WorkerPreferences) -> int:
        """
        Calcola il punteggio matematico di un singolo lavoratore.
        """
        score = 0
        
        # Prendiamo tutte le assegnazioni di questo lavoratore nel mese
        worker_assignments = schedule.for_worker(worker_id)
        
        # VALUTAZIONE DEI PESI GENERALI DEI TURNI
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

        # Strutture di supporto per i calcoli settimanali
        # Raggruppiamo i turni per numero di settimana (es. settimana 51, settimana 52...)
        shifts_by_week = defaultdict(list)
        for a in worker_assignments:
            # Converte la stringa "YYYY-MM-DD" in un oggetto datetime
            dt = datetime.strptime(a.date, "%Y-%m-%d")
            # dt.isocalendar() ritorna (anno, numero_settimana, giorno_settimana)
            week_number = dt.isocalendar()[1]
            shifts_by_week[week_number].append(a.shift)

        #VALUTAZIONE DEI SOFT CONSTRAINTS (PREFERENZE FLESSIBILI)
        for soft in prefs.soft_constraints:
            
            if soft.type == "free_date":
                # Preferisce essere libero in una data specifica (es. '2026-12-25')
                has_assignment_on_date = any(a.date == soft.value for a in worker_assignments)
                if not has_assignment_on_date:
                    score += abs(soft.weight)  # Premio se è rimasto libero
                else:
                    score -= abs(soft.weight)  # Penale se lavora

            elif soft.type == "avoid_shift_date":
                # Preferisce evitare un turno specifico in una data specifica
                has_bad_shift = any(a.date == soft.value and a.shift == soft.shift for a in worker_assignments)
                if has_bad_shift:
                    score -= abs(soft.weight)  # Penale se fa quel turno
                else:
                    score += abs(soft.weight)  # Premio se siamo riusciti a evitarglielo

            elif soft.type == "max_shifts_per_week":
                # Preferisce non superare N turni a settimana. soft.value è un intero (es. 3)
                max_allowed = int(soft.value)
                violated_weeks = 0
                
                for week_num, shifts in shifts_by_week.items():
                    if len(shifts) > max_allowed:
                        violated_weeks += 1
                
                if violated_weeks > 0:
                    # Moltiplichiamo la penale per il numero di settimane in cui ha sforato il limite
                    score -= abs(soft.weight) * violated_weeks
                else:
                    score += abs(soft.weight)

            elif soft.type == "avoid_afternoon_and_night_same_week":
                # Preferisce non avere turni di pomeriggio E notte nella stessa settimana
                combinations_violated = 0
                
                for week_num, shifts in shifts_by_week.items():
                    if "Afternoon" in shifts and "Night" in shifts:
                        combinations_violated += 1
                        
                if combinations_violated > 0:
                    score -= abs(soft.weight) * combinations_violated
                else:
                    score += abs(soft.weight)
                    
        return score