"""
schemas.py — Modelli di dati condivisi tra gli agenti di SmartScheduler.

Formato date        : ISO 8601, es. "2026-12-25"
Formato giorni sett.: inglese,  es. "Monday" … "Sunday"
"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field


# ============================================================
# COSTANTI GLOBALI
# ============================================================

SCHEDULE_START = "2026-12-07"   # Primo giorno della turnazione
SCHEDULE_END   = "2027-01-06"   # Ultimo giorno della turnazione
NUM_DAYS       = 31             # Numero di giorni totali della turnazione

# Turni supportati e relative ore (in ordine: Morning, Afternoon, Night)
SHIFT_TYPES: list[str] = ["Morning", "Afternoon", "Night"]
SHIFT_HOURS: list[int] = [6, 6, 12]


MAX_WEEKLY_HOURS          = 36   # Ore massime in qualsiasi finestra mobile di 7 giorni
REQUIRED_SHIFTS_PER_MONTH = 25   # Turni obbligatori per ogni lavoratore nel mese
REST_DAYS_AFTER_NIGHT     = 2    # Giorni liberi obbligatori dopo un turno notturno

# Type alias riusabili
ShiftType   = Literal["Morning", "Afternoon", "Night"]
RoleType    = Literal["standard", "specialist"]
WeekdayType = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]



class HardConstraint(BaseModel):
    """
    Vincolo OBBLIGATORIO espresso da un lavoratore.
    Se violato, il VerificationAgent rigetta la turnazione e la rimanda al DraftingAgent.

    Tipi supportati
    ---------------
    "free_date"
        Il lavoratore deve essere libero in una data specifica.
        → value: stringa ISO 8601, es. "2026-12-25"

    "free_weekday"
        Il lavoratore deve essere libero in TUTTI i giorni di un certo giorno della settimana.
        → value: nome del giorno in inglese, es. "Sunday"
    """

    type: Literal["free_date", "free_weekday"]

    value: str = Field(
        description=(
            "Per 'free_date'   : data ISO 8601, es. '2026-12-25'. "
            "Per 'free_weekday': giorno della settimana in inglese, es. 'Sunday'."
        )
    )

    description: str | None = Field(
        default=None,
        description=(
            "Testo libero opzionale. Inserire la frase originale del lavoratore "
            "o la motivazione del vincolo. Utile per debug e relazione finale."
        )
    )



class SoftConstraint(BaseModel):
    """
    Preferenza FLESSIBILE espressa da un lavoratore.
    Se violata, il punteggio di soddisfazione del lavoratore scende, ma la turnazione
    non viene rigettata.

    Tipi supportati
    ---------------
    "free_date"
        Preferisce essere libero in una data specifica.
        → value: stringa ISO 8601, es. "2026-12-31"

    "free_weekday"
        Preferisce essere libero in tutti i giorni di un certo giorno della settimana.
        → value: nome del giorno in inglese, es. "Saturday"

    "work_weekday"
        Preferisce lavorare in un certo giorno della settimana.
        → value: nome del giorno in inglese, es. "Monday"

    "avoid_shift_date"
        Preferisce evitare un tipo di turno specifico in una data specifica.
        → value: data ISO 8601, es. "2026-12-31"
        → shift: il turno da evitare, es. "Night"

    "max_shifts_per_week"
        Preferisce non superare N turni in una singola settimana.
        → value: intero, es. 4

    "avoid_afternoon_and_night_same_week"
        Preferisce non avere turni di pomeriggio E notte nella stessa settimana.
        → value e shift: non utilizzati, lasciare None

    Il campo `weight` indica l'intensità della preferenza:
        Positivo (+1 … +10) → vuole che venga soddisfatta
        Negativo (-1 … -10) → vuole evitare quella situazione
    """

    type: Literal[
        "free_date",
        "free_weekday",
        "work_weekday",
        "avoid_shift_date",
        "max_shifts_per_week",
        "avoid_afternoon_and_night_same_week",
        "custom",
    ]

    natural_language: str | None = Field(
        default=None,
        description="Testo libero in linguaggio naturale per spiegare il vincolo custom al DraftingAgent."
    )

    value: str | int | None = Field(
        default=None,
        description=(
            "Dipende dal tipo: "
            "stringa ISO per *_date, "
            "nome del giorno per *_weekday, "
            "intero per max_shifts_per_week, "
            "None per avoid_afternoon_and_night_same_week."
        )
    )

    shift: ShiftType | None = Field(
        default=None,
        description="Usato solo per 'avoid_shift_date'. Indica il turno da evitare."
    )

    weight: int = Field(
        ge=-10,
        le=10,
        description=(
            "Intensità della preferenza: "
            "positivo = vuole, negativo = vuole evitare. "
            "Usato da FairnessAgent per il calcolo del punteggio di equità."
        )
    )

    description: str | None = Field(
        default=None,
        description=(
            "Testo libero opzionale. Inserire la frase originale del lavoratore. "
            "Utile per debug e relazione finale."
        )
    )



class WorkerPreferences(BaseModel):
    """
    Tutte le preferenze di UN singolo lavoratore.

    Campi
    -----
    role
        "standard" (default) o "specialist".
        Nel Caso A tutti i lavoratori sono "standard" e questo campo si ignora.
        Nel Caso B distingue chi può svolgere solo turni standard da chi può farne di entrambi.

    shift_weights
        Lista di 3 interi: [Morning, Afternoon, Night].
        Indica quanto il lavoratore gradisce ogni tipo di turno IN GENERALE.
        Es. [8, 2, -5] = ama i mattini, tollera i pomeriggi, odia le notti.
        Range: da -10 a +10 per ogni valore.

    hard_constraints
        Lista di HardConstraint. Vuota se il lavoratore non ha vincoli obbligatori.

    soft_constraints
        Lista di SoftConstraint. Vuota se il lavoratore non ha preferenze specifiche.
    """

    role: RoleType = Field(
        default="standard",
        description="Ruolo del lavoratore. Rilevante solo nel Caso B."
    )

    shift_weights: list[int] = Field(
        min_length=3,
        max_length=3,
        description="Pesi generali [Morning, Afternoon, Night], da -10 a +10 ciascuno."
    )

    hard_constraints: list[HardConstraint] = Field(
        default_factory=list,
        description="Vincoli obbligatori del lavoratore. Rigettano la turnazione se violati."
    )

    soft_constraints: list[SoftConstraint] = Field(
        default_factory=list,
        description="Preferenze flessibili del lavoratore. Incidono sul punteggio di equità."
    )



class AllPreferences(BaseModel):
    """
    Preferenze di TUTTI i lavoratori raccolte dal WorkersAgent.

    Struttura JSON di esempio
    -------------------------
    {
      "workers": {
        "ID_0": {
          "role": "standard",
          "shift_weights": [8, 2, -5],
          "hard_constraints": [
            {"type": "free_date", "value": "2026-12-25", "description": "Natale in famiglia"}
          ],
          "soft_constraints": [
            {"type": "avoid_shift_date", "value": "2026-12-31", "shift": "Night",
             "weight": -10, "description": "Capodanno con i figli"}
          ]
        },
        "ID_1": { ... }
      }
    }

    Le chiavi del dizionario sono gli ID dei lavoratori nel formato "ID_<numero>".
    """

    workers: dict[str, WorkerPreferences] = Field(
        description="Dizionario worker_id → preferenze. Chiavi nel formato 'ID_<numero>'."
    )



class ShiftAssignment(BaseModel):
    """
    Rappresenta l'assegnazione di UN lavoratore a UN turno in UNA data specifica.
    È il mattone atomico della turnazione.

    Campi
    -----
    date        Data nel formato ISO 8601, es. "2026-12-07".
    shift       Tipo di turno: "Morning", "Afternoon" o "Night".
    worker_id   ID del lavoratore, es. "ID_5".
    role_played Ruolo effettivo svolto in questo turno specifico.
                Rilevante nel Caso B: uno specialist può coprire un posto "standard".
                Default "standard" — nel Caso A si lascia sempre così.
    """

    date: str = Field(description="Data in formato ISO 8601, es. '2026-12-07'.")
    shift: ShiftType = Field(description="Tipo di turno: 'Morning', 'Afternoon' o 'Night'.")
    worker_id: str = Field(description="ID del lavoratore assegnato, es. 'ID_5'.")
    role_played: RoleType = Field(
        default="standard",
        description=(
            "Ruolo effettivo in questo turno. "
            "Nel Caso A sempre 'standard'. "
            "Nel Caso B può essere 'specialist' se lo specialist copre un posto specializzato."
        )
    )



class Schedule(BaseModel):
    """
    La turnazione mensile completa, rappresentata come lista piatta di assegnazioni.

    Struttura JSON di esempio
    -------------------------
    {
      "assignments": [
        {"date": "2026-12-07", "shift": "Morning",   "worker_id": "ID_0", "role_played": "standard"},
        {"date": "2026-12-07", "shift": "Afternoon",  "worker_id": "ID_1", "role_played": "standard"},
        {"date": "2026-12-07", "shift": "Night",      "worker_id": "ID_2", "role_played": "standard"},
        {"date": "2026-12-07", "shift": "Night",      "worker_id": "ID_3", "role_played": "standard"},
        ...
      ]
    }

    Perché lista piatta?
    - Facile da filtrare per data, per lavoratore o per turno.
    - Convertibile direttamente in tabella Pandas/DataFrame per la UI.
    - Semplice da iterare in entrambe le direzioni (per lavoratore e per giorno).
    """

    assignments: list[ShiftAssignment] = Field(
        description="Lista di tutte le assegnazioni lavoratore-turno-data del mese."
    )


    def for_worker(self, worker_id: str) -> list[ShiftAssignment]:
        """Tutte le assegnazioni di un lavoratore specifico."""
        return [a for a in self.assignments if a.worker_id == worker_id]

    def for_date(self, date: str) -> list[ShiftAssignment]:
        """Tutte le assegnazioni in una data specifica."""
        return [a for a in self.assignments if a.date == date]

    def for_date_and_shift(self, date: str, shift: str) -> list[ShiftAssignment]:
        """Assegnazioni per un turno specifico in una data specifica."""
        return [a for a in self.assignments if a.date == date and a.shift == shift]

    def worker_ids(self) -> list[str]:
        """Lista degli ID di tutti i lavoratori presenti nella turnazione."""
        return list({a.worker_id for a in self.assignments})



class SchedulerState(TypedDict):
    """Stato condiviso del grafo LangGraph. Transita tra i nodi del pipeline."""

    preferences    : dict       # AllPreferences serializzata.
    schedule       : dict       # Schedule serializzata.
    violations     : list[str]  # Violazioni hard rilevate dal VerificationAgent.
    fairness_scores: dict       # {"ID_0": 42, "ID_1": 38, ...}
    worst_worker   : str        # worker_id del lavoratore con punteggio minimo.
    prev_min_score : int        # Punteggio minimo dell'iterazione precedente.
    iteration      : int        # Contatore del ciclo di refinement.
