from ortools.sat.python import cp_model


class SmartSchedulerWrapper:
    
    # Costruttore classe
    def __init__(self, num_workers, num_days):

        self.num_workers = num_workers
        self.num_days = num_days
        self.num_shifts = 3

        # Inizializzo il modello di OR-Tools
        self.model = cp_model.CpModel()
        self.shift_hours = [6,6,12]     # 0 = Mattina, 1 = Pomeriggio, 2 = Notte
        
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
    def check_month_sum(self, target_shifts=25):
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
    
    # Aggiungo il vincolo in cui un lavoratore non lavora per due giorni dopo una notte
    def add_no_work_after_night(self):
        for w in range(self.num_workers):
            for d in range(self.num_days - 2):
                notte = self.x[(w,d,2)]
                for s in range(self.num_shifts):
                    self.model.Add(self.x[(w, d + 1,  s)] == 0).OnlyEnforceIf(notte)
                    self.model.Add(self.x[(w, d + 2,  s)] == 0).OnlyEnforceIf(notte)

    # Un lavoratore non può lavorare piu di 36 ore a settimana
    def add_36_hours_a_week(self):
        for w in range(self.num_workers):
            for start_day in range(self.num_days - 7 + 1):
                sliding_window = []
                for d in range(start_day, start_day + 7):
                    for s in range(self.num_shifts):
                        shift_var = self.x[(w,d,s)]
                        hours = self.shift_hours[s]
                        sliding_window.append(shift_var * hours)
                self.model.Add(sum(sliding_window) <= 36)

    '''
    Parte di soft constraints.
    '''

    # L'IA ci restituirà un dizionari di pesi, per ogni medico asocia un puntaggio al turno
    # es +10 mattina -5notte ecc.
    def set_preferences_and_objective(self, preferences_dict):
        #imposto il range possibile per la soddisfazione minima, in questo caso da -250 a 250
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

    def solve(self):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0

        status = solver.Solve(self.model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print("Soluzione ottimale o ammissibile trovata.")
            for w in range(self.num_workers):
                for d in range(self.num_days):
                    for s in range(self.num_shifts):
                        if solver.Value(self.x[(w,d,s)]) == 1:
                            print(f"Lavoratore {w} assegnato al giorno {d}, turno {s}")
        else:
            print("Nessuna soluzione ammissibile trovata")






