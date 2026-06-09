# Classe per gli agenti che accettano in input l'input testuale e traduce le richieste in un json strutturato

import json
from google import genai
from google.genai import types


class WorkersAgent:
    def __init__(self):
        
        self.client = genai.Client()

        self.system_prompt = """
        You are an AI parsing agent responsible for converting unstructured text preferences from healthcare workers into a structured JSON format for an optimization solver.
        Output ONLY a valid JSON object. Do not include any conversational filler or explanation.
        The JSON keys must represent the worker IDs in the format "ID_w" (e.g., "ID_0", "ID_1").

        Each worker object must have the following keys:
        1. "shift_weights": A list of exactly 3 integers representing preferences for shifts: Index 0 (Morning), Index 1 (Afternoon), Index 2 (Night).
           Values must be between -10 (strongly avoid) and 10 (strongly prefer). Neutral is 0.
        
        2. "hard_constraints": A list of objects representing absolute requirements ("necessità assoluta", "devo per forza", "chiedo obbligatoriamente").
           Allowed constraint structures:
           - {"type": "free_date", "value": "YYYY-MM-DD", "description": "text"}
           - {"type": "free_weekday", "value": "Monday" | "Tuesday" | "Wednesday" | "Thursday" | "Friday" | "Saturday" | "Sunday", "description": "text"}

        3. "soft_constraints": A list of objects representing flexible preferences ("preferirei", "vorrei evitare se possibile", "gradirei").
           Allowed constraint structures:
           - {"type": "free_date", "value": "YYYY-MM-DD", "weight": integer, "description": "text"}
           - {"type": "free_weekday", "value": "Monday" | ... | "Sunday", "weight": integer, "description": "text"}
           - {"type": "work_weekday", "value": "Monday" | ... | "Sunday", "weight": integer, "description": "text"}
           - {"type": "avoid_shift_date", "shift": "Morning" | "Afternoon" | "Night", "value": "YYYY-MM-DD", "weight": integer, "description": "text"}
           - {"type": "max_shifts_per_week", "shift": "Morning" | "Afternoon" | "Night", "value": integer, "weight": integer, "description": "text"}
           - {"type": "avoid_afternoon_and_night_same_week", "weight": integer, "description": "text"}

        All dates must be formatted as YYYY-MM-DD. The scheduling period is from 2026-12-07 to 2027-01-06 (inclusive).
        Weights in soft_constraints should be positive (1 to 10) for preferences they want to satisfy, and negative (-10 to -1) for things they want to avoid.
        """

    def parse_preferences(self, doctors_raw_text):
        # Configuriamo la richiesta per forzare l'output in formato JSON
        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            response_mime_type="application/json"
        )
        
        # Effettuiamo la chiamata al modello
        response = self.client.models.generate_content(
            model="gemini-3.5-flash",
            contents=doctors_raw_text,
            config=config
        )
        
        # Convertiamo la stringa JSON ricevuta in un dizionario Python
        preferences_dict = json.loads(response.text)
        return preferences_dict