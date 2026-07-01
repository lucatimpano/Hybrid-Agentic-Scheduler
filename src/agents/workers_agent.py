from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
# Importiamo AllPreferences direttamente dal file centrale schemas.py
from src.models.schemas import AllPreferences

# IMPLEMENTAZIONE AGENTE (WorkersAgent)

class WorkersAgent:
    """
    Agente per il parsing e l'estrazione delle preferenze dei lavoratori.
    Utilizza il modello Gemini per convertire testo naturale in strutture Pydantic validate.
    """
    def __init__(self):
        # Inizializzazione del modello LLM (Gemini) con temperatura deterministica
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0) 
        
        # System prompt ottimizzato con le istruzioni e gli schemi corretti
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
                "        {{'type': 'max_shifts_per_week', 'value': 2, 'shift': None, 'weight': -6, 'description': 'Maximum 2 shifts per week'}}\n"
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
            return result.model_dump()
        except Exception as e:
            print(f"Errore critico durante il parsing del WorkersAgent: {e}")
            
            raise e