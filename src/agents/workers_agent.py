from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
# Importiamo AllPreferences direttamente dal file centrale schemas.py
from src.models.schemas import AllPreferences

import src.agents.prompts as prompts

# IMPLEMENTAZIONE AGENTE (WorkersAgent)

class WorkersAgent:
    """
    Agente per il parsing e l'estrazione delle preferenze dei lavoratori.
    Utilizza il modello Gemini per convertire testo naturale in strutture Pydantic validate.
    """
    def __init__(self):
        # Inizializzazione del modello LLM (Gemini) con temperatura deterministica
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0) 
        
        # System prompt ottimizzato con le istruzioni e gli schemi corretti
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", prompts.WORKERS_SYSTEM),
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