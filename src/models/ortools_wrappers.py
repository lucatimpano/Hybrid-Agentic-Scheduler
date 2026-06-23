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
    
    # Aggiungo il vincolo che un lavoratore deve lavorare esattamente un tot di turni al mese
    def check_month_sum(self, target_shifts=REQUIRED_SHIFTS_PER_MONTH):
        for w in range(self.num_workers):
            worker_var = []
            for d in range(self.num_days):
                for s in range(self.num_shifts):
                    worker_var.append(self.x[(w,d,s)])
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
            for d in range(self.num_days - REST_DAYS_AFTER_NIGHT):
                notte = self.x[(w, d, 2)]
                for offset in range(1, REST_DAYS_AFTER_NIGHT + 1):
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

    # L'IA ci restituirà un dizionari di pesi, per ogni medico asocia un puntaggio al turno
    # es +10 mattina -5notte ecc.
    def maximize_fairness_objective(self, preferences_dict):
        # TODO: Al momento questo metodo gestisce solo i pesi base dei turni (shift_weights).
        # Per gestire i "Soft Constraints" (es. avoid_shift_date, max_shifts_per_week, ecc.) 
        # dovrai leggere l'array "soft_constraints" dal dizionario e aggiungere 
        # premi o penalità algebriche alla lista 'satisfaction_terms'.
        # Es: Se c'è "free_date", aggiungi una penalità (-peso) se la variabile di quel giorno è a 1.
        
        # imposto il range possibile per la soddisfazione minima, in questo caso da -250 a 250
        self.min_satisfaction = self.model.NewIntVar(-250,250, "min_sat")

        for w in range(self.num_workers):
            worker_id = f"ID_{w}"
            weights = preferences_dict[worker_id]["shift_weights"]
            satisfaction_terms = []
            for d in range(self.num_days):
                for s in range(self.num_shifts):
                    shift_var = self.x[(w,d,s)]
                    shift_weight = weights[s]

                    satisfaction_terms.append(shift_var * shift_weight)
            # Dobbiamo garantire che ogni medico abbia un grado di soddisfazione piu alto possibile
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






