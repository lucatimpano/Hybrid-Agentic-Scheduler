from datetime import datetime, timedelta
from ortools.sat.python import cp_model
from .schemas import (
    SHIFT_HOURS,
    SHIFT_TYPES,
    SCHEDULE_START,
    MAX_WEEKLY_HOURS,
    REQUIRED_SHIFTS_PER_MONTH,
    REST_DAYS_AFTER_NIGHT
)


class SmartSchedulerWrapper:
    
    # Costruttore classe
    def __init__(self, num_workers, num_days):

        self.num_workers = num_workers
        self.num_days = num_days
        self.num_shifts = len(SHIFT_TYPES)

        # Inizializzo il modello di OR-Tools
        self.model = cp_model.CpModel()
        self.shift_hours = SHIFT_HOURS     # 0 = Mattina, 1 = Pomeriggio, 2 = Notte
        self.solver = None
        self.status = None
        
        # Inizializzo il dizionario per i ruoli dei lavoratori (utile per il Caso B)
        self.worker_roles = {}

        # Registro per i soft constraint custom generati dinamicamente dal DraftingAgent.
        # Struttura: { worker_idx (int): ["codice_python_str_1", "codice_python_str_2", ...] }
        # Ogni stringa viene eseguita con exec() dentro maximize_fairness_objective,
        # nel contesto corretto in cui satisfaction_terms è disponibile.
        self.custom_soft_terms: dict[int, list[str]] = {}
        
        #Inzializzo il dizionario vuoto per definire i turni
        self.x = {}
        for i in range(self.num_workers):
            for j in range(self.num_days):
                for k in range(self.num_shifts):
                    self.x[(i,j,k)] = self.model.new_bool_var(f"shift_w{i}_d{j}_sh{k}")

    # Aggiungo il vincolo che un lavoratore può lavorare al massimo un turno al giorno
    def add_single_shift_per_day(self):
        for w in range(self.num_workers):
            for d in range(self.num_days):
                days = []
                for s in range(self.num_shifts):
                    days.append(self.x[(w,d,s)])
                self.model.AddAtMostOne(days)    
    
    # Aggiungo il vincolo che un lavoratore deve lavorare esattamente un tot di turni al mese (Notte vale doppio)
    def check_month_sum(self, target_shifts=REQUIRED_SHIFTS_PER_MONTH):
        for w in range(self.num_workers):
            worker_var = []
            for d in range(self.num_days):
                for s in range(self.num_shifts):
                    weight = 2 if s == 2 else 1
                    worker_var.append(self.x[(w,d,s)] * weight)
            num_shifts_per_worker = sum(worker_var)
            self.model.Add(num_shifts_per_worker == target_shifts)
    
    # Aggiungo il vincolo che ogni turno deve essere coperto da almeno 2 lavoratori
    def add_coverage_constraint(self):
        for d in range(self.num_days):
            for s in range(self.num_shifts):
                shifts = []
                for w in range(self.num_workers):
                    shifts.append(self.x[(w,d,s)])
                num_workers_per_shift = sum(shifts)
                self.model.Add(num_workers_per_shift >= 2)

    # Aggiungo il vincolo che un lavoratore non può lavorare più di 2 turni consecutivi
    def add_consecutive_shifts_constraint(self):
        for w in range(self.num_workers):
            for d in range(self.num_days - 1):
                today_night = self.x[(w, d, 2)]
                tomorrow_morning = self.x[(w, d + 1, 0)]
                
                self.model.Add(today_night + tomorrow_morning <= 1)
    
    # Aggiungo il vincolo in cui un lavoratore non lavora dopo un turno di notte
    def add_no_work_after_night(self):
        for w in range(self.num_workers):
            for d in range(self.num_days):
                notte = self.x[(w, d, 2)]
                for offset in range(1, REST_DAYS_AFTER_NIGHT + 1):
                    if d + offset < self.num_days:
                        for s in range(self.num_shifts):
                            self.model.Add(self.x[(w, d + offset, s)] == 0).OnlyEnforceIf(notte)

    # Un lavoratore non può lavorare più delle ore massime settimanali in 7 giorni mobili
    def add_36_hours_a_week(self):
        for w in range(self.num_workers):
            for start_day in range(self.num_days - 7 + 1):
                sliding_window = []
                for d in range(start_day, start_day + 7):
                    for s in range(self.num_shifts):
                        shift_var = self.x[(w,d,s)]
                        hours = self.shift_hours[s]
                        sliding_window.append(shift_var * hours)
                self.model.Add(sum(sliding_window) <= MAX_WEEKLY_HOURS)

    '''
    Parte di soft constraints.
    '''

    def maximize_fairness_objective(self, preferences_dict: dict):
        """
        Imposta la funzione obiettivo Maximin per massimizzare la soddisfazione del medico più scontento.
        
        Parametri:
        ----------
        preferences_dict : dict
            Un dizionario strutturato che rappresenta le preferenze di tutti i medici.
            Corrisponde al campo 'workers' dello schema 'AllPreferences'.
            Esempio di struttura attesa:
            {
                "ID_0": {
                    "role": "standard",
                    "shift_weights": [10, 5, -5],
                    "soft_constraints": [
                        {"type": "free_date", "value": "2026-12-25", "weight": 8}
                    ]
                },
                "ID_1": { ... }
            }
        """
        # Imposto un range più ampio per supportare pesi multipli e penalità
        self.min_satisfaction = self.model.NewIntVar(-1000, 1000, "min_sat")
        start_date = datetime.strptime(SCHEDULE_START, "%Y-%m-%d")
        
        workers_dict = preferences_dict.get("workers", preferences_dict)

        for w in range(self.num_workers):
            worker_id = f"ID_{w}"
            # Estraiamo in modo sicuro le preferenze del medico
            worker_prefs = workers_dict.get(worker_id, {})
            weights = worker_prefs.get("shift_weights", [0, 0, 0])
            soft_constraints = worker_prefs.get("soft_constraints", [])
            
            # Lista in cui inseriamo il prodotto tra la variabile booleana del turno e il peso di quel turno
            satisfaction_terms = []
            
            # 1. Soddisfazione base dai pesi dei turni
            for d in range(self.num_days):
                for s in range(self.num_shifts):
                    shift_var = self.x[(w,d,s)]
                    shift_weight = weights[s]
                    satisfaction_terms.append(shift_var * shift_weight)
                    
            # 2. Elaborazione dei Soft Constraints
            for sc in soft_constraints:
                c_type = sc.get("type")
                weight = sc.get("weight", 0)
                val = sc.get("value")
                
                # PRIMO VINCOLO SOFT: free_date (Preferisce non lavorare in una certa data)
                if c_type == "free_date" and val:
                    try:
                        target_date = datetime.strptime(val, "%Y-%m-%d")
                        target_day_index = (target_date - start_date).days
                        
                        # Controlliamo che la data ricada nel periodo di pianificazione
                        if 0 <= target_day_index < self.num_days:
                            # Se lavora in qualsiasi turno di quel giorno, sottraiamo il peso
                            for s in range(self.num_shifts):
                                satisfaction_terms.append(self.x[(w, target_day_index, s)] * (-weight))
                    except ValueError:
                        pass # Formato data errato, proseguiamo
                        
                # SECONDO VINCOLO SOFT: free_weekday (Preferisce non lavorare in un giorno della settimana)
                elif c_type == "free_weekday" and val:
                    for d in range(self.num_days):
                        current_date = start_date + timedelta(days=d)
                        if current_date.strftime("%A") == val:
                            # Se lavora in qualsiasi turno di questo giorno, sottraiamo il peso
                            for s in range(self.num_shifts):
                                satisfaction_terms.append(self.x[(w, d, s)] * (-weight))
                                
                # TERZO VINCOLO SOFT: work_weekday (Preferisce lavorare in un giorno della settimana)
                # Uguale al precedente, ma al contrario, aggiungiamo il peso
                elif c_type == "work_weekday" and val:
                    for d in range(self.num_days):
                        current_date = start_date + timedelta(days=d)
                        if current_date.strftime("%A") == val:
                            # Se lavora in qualsiasi turno di questo giorno, AGGIUNGIAMO il peso (è un premio)
                            for s in range(self.num_shifts):
                                satisfaction_terms.append(self.x[(w, d, s)] * weight)
                                
                # QUARTO VINCOLO SOFT: avoid_shift_date (Preferisce evitare uno specifico turno in una certa data)
                elif c_type == "avoid_shift_date" and val:
                    shift_str = sc.get("shift")
                    if shift_str in SHIFT_TYPES:
                        try:
                            target_date = datetime.strptime(val, "%Y-%m-%d")
                            target_day_index = (target_date - start_date).days
                            
                            if 0 <= target_day_index < self.num_days:
                                shift_idx = SHIFT_TYPES.index(shift_str)
                                # Sottraiamo il peso solo se gli viene assegnato QUEL preciso turno in QUELLA precisa data
                                satisfaction_terms.append(self.x[(w, target_day_index, shift_idx)] * (-weight))
                        except ValueError:
                            pass # Formato data errato
                            
                # QUINTO VINCOLO SOFT: max_shifts_per_week (Preferisce non superare N turni a settimana)
                elif c_type == "max_shifts_per_week" and val is not None:
                    max_s = int(val)
                    # Suddividiamo il mese in blocchi di 7 giorni (settimane)
                    for start_d in range(0, self.num_days, 7):
                        week_days = min(7, self.num_days - start_d)
                        
                        # Raccogliamo tutte le variabili dei turni di questa settimana per questo medico
                        week_shifts = []
                        for d_off in range(week_days):
                            for s in range(self.num_shifts):
                                week_shifts.append(self.x[(w, start_d + d_off, s)])
                        
                        # Variabile booleana che vale 1 SOLO se supera il limite
                        exceeds_var = self.model.NewBoolVar(f"exceeds_{w}_{start_d}")
                        
                        # Variabile intera di supporto per la somma dei turni
                        sum_var = self.model.NewIntVar(0, 21, f"sum_shifts_{w}_{start_d}")
                        self.model.Add(sum_var == sum(week_shifts))
                        
                        # Colleghiamo exceeds_var al superamento del limite
                        self.model.Add(sum_var > max_s).OnlyEnforceIf(exceeds_var)
                        self.model.Add(sum_var <= max_s).OnlyEnforceIf(exceeds_var.Not())
                        
                        # Sottraiamo il peso se supera il limite
                        satisfaction_terms.append(exceeds_var * (-weight))
                        
                # SESTO VINCOLO SOFT: avoid_afternoon_and_night_same_week
                elif c_type == "avoid_afternoon_and_night_same_week":
                    for start_d in range(0, self.num_days, 7):
                        week_days = min(7, self.num_days - start_d)
                        
                        # Fa almeno un pomeriggio in settimana?
                        has_afternoon = self.model.NewBoolVar(f"has_aft_{w}_{start_d}")
                        afternoon_shifts = [self.x[(w, start_d + d_off, 1)] for d_off in range(week_days)]
                        self.model.AddMaxEquality(has_afternoon, afternoon_shifts) # 1 se almeno un turno è 1
                        
                        # Fa almeno una notte in settimana?
                        has_night = self.model.NewBoolVar(f"has_night_{w}_{start_d}")
                        night_shifts = [self.x[(w, start_d + d_off, 2)] for d_off in range(week_days)]
                        self.model.AddMaxEquality(has_night, night_shifts)
                        
                        # Li fa entrambi? (AND logico, si usa AddMinEquality per i booleani)
                        has_both = self.model.NewBoolVar(f"has_both_{w}_{start_d}")
                        self.model.AddMinEquality(has_both, [has_afternoon, has_night])
                        
                        # Sottraiamo il peso se li fa entrambi
                        satisfaction_terms.append(has_both * (-weight))

            # --- SOFT CONSTRAINT CUSTOM (generati dinamicamente dall'AI nel DraftingAgent) ---
            # Eseguiamo i codici registrati per questo worker nel contesto corretto.
            # Il codice generato ha accesso a: satisfaction_terms, w, self (wrapper), model, x
            for custom_code in self.custom_soft_terms.get(w, []):
                try:
                    exec(custom_code, {
                        "satisfaction_terms": satisfaction_terms,
                        "w": w,
                        "self": self,
                        "model": self.model,
                        "x": self.x,
                        "num_days": self.num_days,
                        "num_shifts": self.num_shifts,
                    })
                except Exception as e:
                    print(f"[WARN] Soft constraint custom per worker {w} fallito e ignorato: {e}")
            # ---------------------------------------------------------------------------

            # Garantiamo che il punteggio del medico sia maggiore o uguale al punteggio minimo globale
            self.model.Add(sum(satisfaction_terms) >= self.min_satisfaction)
            
        # Ora dobbiamo massimizzare la soddisfazione minima tra tutti i medici
        self.model.Maximize(self.min_satisfaction)

    def solve(self) -> int:
        self.solver = cp_model.CpSolver()
        self.solver.parameters.max_time_in_seconds = 60.0

        self.status = self.solver.Solve(self.model)

        if self.status == cp_model.OPTIMAL or self.status == cp_model.FEASIBLE:
            print("Soluzione ottimale o ammissibile trovata.")
            for w in range(self.num_workers):
                for d in range(self.num_days):
                    for s in range(self.num_shifts):
                        if self.solver.Value(self.x[(w,d,s)]) == 1:
                            print(f"Lavoratore {w} assegnato al giorno {d}, turno {s}")
        else:
            print("Nessuna soluzione ammissibile trovata")
        return self.status

    def export_schedule_as_dict(self) -> dict:
        """
        Estrae la turnazione risolta dal solver e la restituisce come dizionario
        compatibile con lo schema Schedule.
        """
        # Se il solutore non ha ancora girato o non ha trovato una soluzione valida, ritorna vuoto
        if self.solver is None or (self.status != cp_model.OPTIMAL and self.status != cp_model.FEASIBLE):
            return {"assignments": []}

        assignments = []
        start_date = datetime.strptime(SCHEDULE_START, "%Y-%m-%d")

        # Scorre ciascun giorno e ciascun turno per estrarre le assegnazioni del solver
        for d in range(self.num_days):
            # Calcola la data corrispondente all'indice del giorno d
            current_date_str = (start_date + timedelta(days=d)).strftime("%Y-%m-%d")

            for s in range(self.num_shifts):
                shift_name = SHIFT_TYPES[s]

                # Trova tutti i lavoratori assegnati a questo specifico turno
                assigned_workers = []
                for w in range(self.num_workers):
                    if self.solver.Value(self.x[(w, d, s)]) == 1:
                        assigned_workers.append(w)

                if not assigned_workers:
                    continue

                # Tiene traccia se abbiamo già assegnato lo specialista per questo turno (Caso B)
                specialist_assigned = False

                for w in assigned_workers:
                    worker_id = f"ID_{w}"
                    # Recupera il ruolo predefinito del lavoratore (default "standard" se non specificato)
                    role = self.worker_roles.get(worker_id, "standard")

                    if role == "specialist":
                        if not specialist_assigned:
                            # Il primo specialista assegnato ricopre il ruolo "specialist" richiesto
                            role_played = "specialist"
                            specialist_assigned = True
                        else:
                            # Eventuali altri specialisti in sovrannumero fungono da "standard"
                            role_played = "standard"
                    else:
                        # I lavoratori standard ricoprono sempre il ruolo "standard"
                        role_played = "standard"

                    assignments.append({
                        "date": current_date_str,
                        "shift": shift_name,
                        "worker_id": worker_id,
                        "role_played": role_played,
                        "original_role": role  # Tiene traccia del ruolo reale (es. "specialist" anche se gioca come "standard")
                    })

        return {"assignments": assignments}

    def add_hard_constraint_free_date(self, worker_id: str, date_str: str):
        """
        Forza a 0 la variabile del lavoratore specificato per la data indicata (es. '2026-12-25').
        """
        # Estrae l'indice numerico del lavoratore dall'ID stringa (es. da "ID_3" ricava l'intero 3)
        try:
            worker_idx = int(worker_id.split("_")[1])
        except (IndexError, ValueError) as e:
            raise ValueError(f"ID lavoratore non valido: '{worker_id}'. Deve essere nel formato 'ID_<numero>'.") from e
        
        # Converte le stringhe in oggetti datetime per calcolare la differenza in giorni
        try:
            start_date = datetime.strptime(SCHEDULE_START, "%Y-%m-%d")
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Formato data non valido: '{date_str}'. Deve essere nel formato 'YYYY-MM-DD'.") from e
            
        # Calcola l'indice del giorno relativo all'inizio del calendario (SCHEDULE_START -> giorno 0)
        day_idx = (target_date - start_date).days
        
        # Verifica che l'indice del lavoratore sia all'interno del range consentito
        if not (0 <= worker_idx < self.num_workers):
            raise ValueError(f"Indice lavoratore {worker_idx} fuori dai limiti (0-{self.num_workers - 1}).")
            
        # Verifica che il giorno calcolato rientri nel periodo coperto dalla turnazione
        if not (0 <= day_idx < self.num_days):
            raise ValueError(f"Data {date_str} (indice giorno {day_idx}) fuori dal periodo di pianificazione di {self.num_days} giorni a partire da {SCHEDULE_START}.")

        # Imposta a 0 tutte le variabili decisionali del lavoratore per quel giorno per tutti i turni (Morning, Afternoon, Night).
        # In questo modo il solutore non potrà assegnargli alcun turno in quella data.
        for s in range(self.num_shifts):
            self.model.Add(self.x[(worker_idx, day_idx, s)] == 0)

    def add_hard_constraint_free_weekday(self, worker_id: str, weekday: str):
        """
        Forza a 0 le variabili del lavoratore per tutti i giorni corrispondenti a un weekday (es. 'Sunday').
        """
        try:
            worker_idx = int(worker_id.split("_")[1])
        except (IndexError, ValueError) as e:
            raise ValueError(f"ID lavoratore non valido: '{worker_id}'.") from e
            
        if not (0 <= worker_idx < self.num_workers):
            raise ValueError(f"Indice lavoratore {worker_idx} fuori dai limiti.")

        start_date = datetime.strptime(SCHEDULE_START, "%Y-%m-%d")
        
        # Scorre tutti i giorni e blocca quelli che corrispondono al giorno della settimana richiesto
        for d in range(self.num_days):
            current_date = start_date + timedelta(days=d)
            # %A restituisce il nome del giorno in inglese (es. 'Sunday', 'Monday')
            if current_date.strftime("%A") == weekday:
                for s in range(self.num_shifts):
                    self.model.Add(self.x[(worker_idx, d, s)] == 0)

    def add_specialist_coverage_constraint(self, worker_id_roles: dict[str, str]):
        """
        Applica i vincoli del Caso B: almeno 2 standard e almeno 1 specialist per turno.
        (Equivale matematicamente a: totale lavoratori >= 3, di cui specialisti >= 1).
        """
        # Salviamo i ruoli nel wrapper
        self.worker_roles = worker_id_roles
        
        # Estraiamo gli indici numerici dei lavoratori specialisti
        specialist_indices = []
        for w in range(self.num_workers):
            if worker_id_roles.get(f"ID_{w}", "standard") == "specialist":
                specialist_indices.append(w)
        
        if not specialist_indices:
            raise ValueError("Impossibile applicare il vincolo: non ci sono medici specialisti definiti.")
                
        for d in range(self.num_days):
            for s in range(self.num_shifts):
                # 1. Almeno 3 medici in totale (2 standard + 1 specialista, oppure 3 specialisti, ecc.)
                total_workers_in_shift = []
                for w in range(self.num_workers):
                    total_workers_in_shift.append(self.x[(w, d, s)])
                self.model.Add(sum(total_workers_in_shift) >= 3)
                
                # 2. Almeno 1 medico specialista deve essere presente
                specialists_in_shift = []
                for w in specialist_indices:
                    specialists_in_shift.append(self.x[(w, d, s)])
                self.model.Add(sum(specialists_in_shift) >= 1)






