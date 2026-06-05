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

    def add_single_shift_per_day(self):
        for w in range(self.num_workers):
            for d in range(self.num_days):
                days = []
                for s in range(self.num_shifts):
                    days.append(self.x[(w,d,s)])
                self.model.AddAtMostOne(days)    

    def check_month_sum(self):
        for w in range(self.num_workers):
            worker_var = []
            for d in range(self.num_days):
                for s in range(self.num_shifts):
                    worker_var.append(self.x[(w,d,s)])
            num_shifts_per_worker = sum(worker_var)
            self.model.Add(num_shifts_per_worker == 25)
    
    def add_coverage_constraint(self):
        for d in range(self.num_days):
            for s in range(self.num_shifts):
                shifts = []
                for w in range(self.num_workers):
                    shifts.append(self.x[(w,d,s)])
                num_workers_per_shift = sum(shifts)
                self.model.Add(num_workers_per_shift >= 2)

    def add_consecutive_shifts_constraint(self):
        #TODO

