from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import Literal, List, Dict, Optional

# MODELLI PYDANTIC (Il Contratto Dati)

class HardConstraint(BaseModel):
    type: Literal["free_date", "free_weekday"] = Field(
        ..., description="Tipo di vincolo rigido: 'free_date' per data singola, 'free_weekday' per giorno della settimana fisso."
    )
    value: str = Field(
        ..., description="Il valore del vincolo. Es: '2026-12-25' per free_date, oppure 'Monday' per free_weekday."
    )
    description: str = Field(
        ..., description="La motivazione o descrizione testuale originale fornita dal lavoratore."
    )

class SoftConstraint(BaseModel):
    type: Literal[
        "free_date", "free_weekday", "work_weekday",
        "avoid_shift_date", "max_shifts_per_week",
        "avoid_afternoon_and_night_same_week"
    ] = Field(..., description="Tipo di preferenza flessibile.")
    value: Optional[str] = Field(
        None, description="Valore associato (es. data '2026-12-31' o giorno della settimana 'Sunday')."
    )
    shift: Optional[Literal["Morning", "Afternoon", "Night"]] = Field(
        None, description="Turno specifico da evitare o cercare, se applicabile."
    )
    weight: int = Field(
        ..., ge=-10, le=10, 
        description="Peso della preferenza: positivo (da 1 a 10) se desiderato, negativo (da -10 a -1) se da evitare."
    )
    description: str = Field(
        ..., description="Descrizione testuale originale della preferenza flessibile."
    )

class WorkerPreferences(BaseModel):
    role: Literal["standard", "specialist"] = Field(
        "standard", description="Ruolo del lavoratore. Default è 'standard'."
    )
    shift_weights: List[int] = Field(
        ..., min_length=3, max_length=3,
        description="Lista di esattamente 3 interi con i pesi per [Morning, Afternoon, Night] da -10 a +10."
    )
    hard_constraints: List[HardConstraint] = Field(
        default_factory=list, description="Lista dei vincoli rigidi e inderogabili."
    )
    soft_constraints: List[SoftConstraint] = Field(
        default_factory=list, description="Lista delle preferenze soft e flessibili."
    )

class AllPreferences(BaseModel):
    workers: Dict[str, WorkerPreferences] = Field(
        ..., description="Dizionario con chiave l'ID del lavoratore (es. 'ID_0') e valore le sue preferenze."
    )


# IMPLEMENTAZIONE AGENTE (WorkersAgent)

class WorkersAgent:
    """
    Agente per il parsing e l'estrazione delle preferenze dei lavoratori.
    Utilizza il modello Gemini per convertire testo naturale in strutture Pydantic validate.
    """
    def __init__(self):
        # Modello reale ed esistente
        self.llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0) 
        
        # System prompt con parentesi graffe raddoppiate {{ }} negli esempi JSON per evitare errori di f-string
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "You are an agent for decomposing and parsing worker preferences (Phase 1).\n"
                "Your task is to analyze natural language text containing workers' requests and accurately map them "
                "into the required Pydantic structured model.\n\n"

                "=== HARD vs SOFT CONSTRAINTS DISTINCTION ===\n"
                "HARD CONSTRAINT (rigid, ABSOLUTE constraints):\n"
                "- Key phrases: 'Cannot', 'Impossible', 'Must', 'Always free', 'I require', 'I demand'\n"
                "- Examples: 'I cannot work on December 25' → HardConstraint\n"
                "            'I must have Monday free' → HardConstraint\n"
                "- Non-negotiable; the worker cannot work under those conditions.\n\n"

                "=== SOFT CONSTRAINT (flexible preferences, WISHES) ===\n"
                "- Key phrases: 'Preferably', 'If possible', 'I would like', 'I would avoid', 'I would prefer'\n"
                "- Examples: 'I would prefer not to work afternoon shifts' → SoftConstraint\n"
                "            'Maximum 3 shifts per week' → SoftConstraint with type: max_shifts_per_week\n"
                "- Negotiable; they guide optimization but are not rigid.\n\n"

                "=== WEIGHT SCALE (from -10 to +10) ===\n"
                "+10 / -10: Maximum intensity ('ESSENTIAL', 'ABSOLUTE', 'HATE', 'LOVE')\n"
                "+7 / -7:   High importance ('VERY', 'STRONGLY', 'AVOID')\n"
                "+5 / -5:   Medium importance ('IMPORTANT', 'PREFERABLY')\n"
                "+3 / -3:   Low importance ('A bit', 'Slight preference')\n"
                "+1 / -1:   Minimal importance ('If possible', 'Optional')\n\n"
                "Positive (+): The worker DESIRES that schedule/day/shift.\n"
                "Negative (-): The worker WANTS TO AVOID that schedule/day/shift.\n\n"

                "=== CRITICAL INSTRUCTIONS ===\n"
                "1. The scheduling horizon spans from 2026-12-07 to 2027-01-06 inclusive. Ensure extracted dates are coherent (2026 for December, 2027 for January).\n"
                "2. Weekdays ALWAYS in English and capitalized (Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday).\n"
                "3. Dates in ISO 8601 format: YYYY-MM-DD (e.g., 2026-12-25).\n"
                "4. ALWAYS maintain the original description in the 'description' field for traceability.\n"
                "5. If the worker explicitly states their role (e.g., specialist), map it to the 'role' field. Otherwise default='standard'.\n"
                "6. 'shift_weights' is a list of EXACTLY 3 integers [Morning, Afternoon, Night]. Use positive values for preferred shifts, negative for shifts to avoid, and 0 for neutral.\n\n"

                "=== EXAMPLES OF CORRECT PARSING ===\n"
                "INPUT: 'I am Dr. Rossi (ID_0). I cannot work on December 25. In general I prefer mornings, but I hate nights. I avoid afternoon-night combinations in the same week. Maximum 2 shifts per week.'\n\n"
                "OUTPUT:\n"
                "{{\n"
                "  'workers': {{\n"
                "    'ID_0': {{\n"
                "      'role': 'standard',\n"
                "      'shift_weights': [8, 0, -10],\n"
                "      'hard_constraints': [\n"
                "        {{'type': 'free_date', 'value': '2026-12-25', 'description': 'Cannot work on December 25'}}\n"
                "      ],\n"
                "      'soft_constraints': [\n"
                "        {{'type': 'avoid_afternoon_and_night_same_week', 'value': None, 'shift': None, 'weight': -7, 'description': 'Avoid afternoon-night combinations in the same week'}},\n"
                "        {{'type': 'max_shifts_per_week', 'value': '2', 'shift': None, 'weight': -6, 'description': 'Maximum 2 shifts per week'}}\n"
                "      ]\n"
                "    }}\n"
                "  }}\n"
                "}}\n\n"

                "=== EDGE CASES HANDLING ===\n"
                "- If the worker does NOT specify an ID in the text, use 'ID_0', 'ID_1', etc. sequentially.\n"
                "- If they don't mention their role, use 'standard' as default.\n"
                "- If there are conflicting constraints (e.g., 'I must be free on Monday' AND 'I prefer to work Monday'), prioritize the hard constraint and note it in the description.\n"
                "- Invalid dates or dates outside the temporal range: RECORD in description but DO NOT exclude the constraint.\n"
                "- Ambiguous weights: If intensity is unclear, assign 5 / -5 as standard medium importance weight.\n\n"

                "=== EXPECTED OUTPUT ===\n"
                "ALWAYS return a valid JSON conforming to the AllPreferences structure.\n"
                "Every field must be populated according to the Pydantic definitions.\n"
                "If critical information is missing, use reasonable default values but always annotate them in the 'description' field."
            )),
            ("human", "{text}")
        ])
        
        self.chain = self.prompt | self.llm.with_structured_output(AllPreferences) 

    def parse_preferences(self, text: str) -> dict:
        """
        Riceve il testo grezzo delle preferenze e restituisce il dizionario 
        mappato pronto per il modulo di ottimizzazione (DraftingAgent).
        """
        if not text or not text.strip():
            return {}
            
        try:
            result = self.chain.invoke({"text": text}) 
            return result.model_dump()["workers"] 
        except Exception as e:
            print(f"Errore critico durante il parsing del WorkersAgent: {e}")
            return {}