from datetime import datetime, timedelta

class VerificationAgent:
    """
    Agente (simbolico) per verificare la correttezza della turnazione.
    Non usa LLM, ma applica regole matematiche per assicurare che 
    nessun hard constraint sia stato violato.
    """
    def __init__(self):
        # Mappa i nomi dei turni ai loro "pesi" in termini di turni standard (1 turno standard = 6 ore)
        self.shift_weights = {
            "Morning": 1,
            "Afternoon": 1,
            "Night": 2
        }
        
    def verify_schedule(self, schedule_dict: dict, preferences: dict, num_days: int = 31, has_specialist: bool = False) -> dict:
        """
        Verifica che la turnazione sia valida.
        Ritorna un dizionario:
        {
            "is_valid": bool,
            "violations": [list of strings describing violations]
        }
        """
        violations = []
        assignments = schedule_dict.get("assignments", [])
        
        if not assignments:
            violations.append("La turnazione è vuota.")
            return {"is_valid": False, "violations": violations}
            
        # Organizziamo i dati per lavoratore e per giorno/turno per facilitare i controlli
        # worker_schedule[worker_id][day_index] = list of shifts
        worker_schedule = {}
        # day_coverage[date][shift] = list of worker_ids
        day_coverage = {}
        
        # Inizializziamo date fisse (giorno 0 = 2026-12-07)
        start_date = datetime(2026, 12, 7)
        date_to_index = {}
        for d in range(num_days):
            current_date = start_date + timedelta(days=d)
            date_str = current_date.strftime("%Y-%m-%d")
            date_to_index[date_str] = d
            day_coverage[date_str] = {"Morning": [], "Afternoon": [], "Night": []}
            
        # Costruiamo le strutture dati
        for a in assignments:
            w_id = a["worker_id"]
            date_str = a["date"]
            shift = a["shift"]
            
            if w_id not in worker_schedule:
                worker_schedule[w_id] = {d: [] for d in range(num_days)}
                
            day_idx = date_to_index.get(date_str)
            if day_idx is not None:
                worker_schedule[w_id][day_idx].append(shift)
                day_coverage[date_str][shift].append(w_id)
        
        # 1. Verifica Vincolo Copertura (Caso A: min 2, Caso B: min 3 con almeno 1 specialista)
        workers_dict = preferences.get("workers", preferences)
        for date_str, shifts in day_coverage.items():
            for shift_name, workers in shifts.items():
                if has_specialist:
                    min_workers = 3
                else:
                    min_workers = 2
                if len(workers) < min_workers:
                    violations.append(f"Copertura insufficiente: {date_str} {shift_name} ha solo {len(workers)} medici (minimo {min_workers}).")
                if has_specialist:
                    specialists = [w for w in workers if workers_dict.get(w, {}).get("role") == "specialist"]
                    if len(specialists) < 1:
                        violations.append(f"Manca specialista: {date_str} {shift_name} non ha specialisti assegnati.")
        
        for w_id, days_dict in worker_schedule.items():
            # Conta totale mensile
            total_monthly_shifts = 0
            
            for d in range(num_days):
                shifts_today = days_dict[d]
                
                # Un solo turno al giorno
                if len(shifts_today) > 1:
                    violations.append(f"{w_id} ha più di un turno il giorno {d} ({shifts_today}).")
                    
                for s in shifts_today:
                    total_monthly_shifts += self.shift_weights[s]
                    
                # 2. Riposo dopo la notte (2 giorni liberi)
                if "Night" in shifts_today:
                    # Giorno successivo
                    if d + 1 < num_days and len(days_dict[d+1]) > 0:
                        violations.append(f"{w_id} lavora il giorno {d+1} dopo un turno di Notte al giorno {d}.")
                    # Secondo giorno successivo
                    if d + 2 < num_days and len(days_dict[d+2]) > 0:
                        violations.append(f"{w_id} lavora il giorno {d+2} dopo un turno di Notte al giorno {d} (richiesti 2 gg di riposo).")
            
            # 3. Totale 25 turni (pesati) al mese
            if total_monthly_shifts != 25:
                violations.append(f"{w_id} ha svolto {total_monthly_shifts} turni invece di 25.")
                
            # 4. Massimo 36 ore (6 turni standard) ogni 7 giorni consecutivi
            for start_d in range(num_days - 6):
                rolling_sum = 0
                for offset in range(7):
                    curr_d = start_d + offset
                    for s in days_dict[curr_d]:
                        rolling_sum += self.shift_weights[s]
                if rolling_sum > 6:
                    violations.append(f"{w_id} supera 36 ore nella finestra dal giorno {start_d} al {start_d+6} ({rolling_sum} turni standard).")
                    
        # 5. Verifica Hard Constraints personali
        for w_id, prefs in workers_dict.items():
            if w_id not in worker_schedule:
                continue
            for hc in prefs.get("hard_constraints", []):
                if hc.get("type") == "free_date":
                    date_val = hc.get("value")
                    day_idx = date_to_index.get(date_val)
                    if day_idx is not None and len(worker_schedule[w_id][day_idx]) > 0:
                        violations.append(f"Violato hard constraint free_date: {w_id} lavora il {date_val}.")
                
                elif hc.get("type") == "free_weekday":
                    weekday_val = hc.get("value")
                    for date_str, d_idx in date_to_index.items():
                        # Controllo se il giorno della settimana corrisponde al giorno libero richiesto
                        date_obj = start_date + timedelta(days=d_idx)
                        if date_obj.strftime("%A") == weekday_val:
                            if len(worker_schedule[w_id][d_idx]) > 0:
                                violations.append(f"Violato hard constraint free_weekday: {w_id} lavora di {weekday_val} ({date_str}).")

        return {
            "is_valid": len(violations) == 0,
            "violations": violations
        }
