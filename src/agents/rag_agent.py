import os
import json
import dotenv
from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.vectorstores import InMemoryVectorStore
from langchain.tools import tool
from langchain.agents import create_agent
from langchain_ollama import ChatOllama

import src.agents.prompts as prompts

dotenv.load_dotenv()

class RagAgent:
    """
    RAG Agent responsible for institutional compliance validation (Phase 1.5).
    It checks parsed worker preferences against hospital regulations PDF using an autonomous LLM ReAct agent.
    """
    def __init__(self, pdf_path: str = "data/input/regolamento_ospedaliero.pdf"):
        # 1. Carica e splitta il PDF del regolamento
        docs = self._load_documents(pdf_path)
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            add_start_index=True
        )
        all_splits = text_splitter.split_documents(docs)
        
        # 2. Inizializza il Vector Store con gli embedding di Gemini
        embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2")
        self.vector_store = InMemoryVectorStore(embeddings)
        self.vector_store.add_documents(documents=all_splits)
        
        # 3. Definisce il tool internamente per mantenere l'isolamento del vector store
        @tool
        def retrieve_context(query: str):
            """Retrieve relevant rules and articles from the hospital regulations PDF."""
            retrieved_docs = self.vector_store.similarity_search(query, k=2)
            serialized = "\n\n".join(
                f"Source: {doc.metadata}\nContent: {doc.page_content}"
                for doc in retrieved_docs
            )
            return serialized
            
        self.retrieve_tool = retrieve_context
        
        # 4. Inizializza il ReAct Agent di LangGraph
        # self.llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)      # cambiare a 3.5 flash
        self.llm = ChatOllama(model="qwen3.5:0.8b", temperature=0)
        self.agent = create_agent(
            self.llm,
            tools=[self.retrieve_tool],
            system_prompt=prompts.RAG_SYSTEM
        )

    def _load_documents(self, pdf_path: str) -> list[Document]:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"File PDF non trovato al percorso: {pdf_path}")
        reader = PdfReader(pdf_path)
        documents = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                documents.append(
                    Document(
                        page_content=text.strip(),
                        metadata={"source": os.path.basename(pdf_path), "page": i + 1}
                    )
                )
        return documents

    def verify_compliance(self, preferences: dict) -> dict:
        """
        Verifica a batch la conformità delle preferenze dei medici rispetto al regolamento.
        Ritorna un dizionario con il report di conformità strutturato.
        """
        # Formattiamo le preferenze in JSON da passare all'agente
        preferences_json = json.dumps(preferences, indent=2)
        
        # Eseguiamo il ciclo ReAct dell'agente
        response = self.agent.invoke({
            "messages": [
                ("user", f"Verify the compliance of these worker preferences:\n\n{preferences_json}")
            ]
        })
        
        # Stampa i passaggi intermedi dell'agente per visualizzare il ragionamento e le chiamate ai tool
        print("\n=== PASSAGGI DELL'AGENTE (REASONING & TOOLS) ===")
        for msg in response["messages"]:
            role = "USER" if msg.type == "human" else "AI"
            print(f"\n[{role}]:")
            print(msg.content)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                print(f"-> Chiamata Tool: {msg.tool_calls}")
        print("================================================\n")
        
        # Estraiamo la risposta finale
        last_message = response["messages"][-1].content
        
        # content può essere una lista (testo + artefatti) o una stringa semplice
        if isinstance(last_message, list):
            last_message = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in last_message
            )
        
        # Pulizia dell'output per rimuovere blocchi di codice markdown (es. ```json ... ```)
        clean_msg = last_message.strip()
        if clean_msg.startswith("```"):
            lines = clean_msg.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_msg = "\n".join(lines).strip()
            
        try:
            return json.loads(clean_msg)
        except json.JSONDecodeError as e:
            print(f"Errore di parsing JSON nella risposta dell'agente RAG: {e}")
            print(f"Risposta originale:\n{last_message}")
            return {
                "compliance_report": {},
                "error": "Risposta non in formato JSON valido",
                "raw_response": last_message
            }

if __name__ == "__main__":
    # Test della classe RagAgent con casi di conformità ed violazioni di prova
    print("=== AVVIO AGENTE RAG COMPLIANCE ===")
    agent = RagAgent()
    
    # Prepariamo un set di test per simulare le preferenze estratte da WorkersAgent:
    # - ID_0: Conforme
    # - ID_1: Viola la regola delle festività consecutive (Natale 25 Dic + Capodanno 1 Gen)
    # - ID_2: Vicedirettore con più di 1 turno di notte a settimana (viola Art 5.1)
    test_preferences = {
        "workers": {
            "ID_1": {
                "role": "standard",
                "shift_weights": [0, 0, 0],
                "hard_constraints": [
                    {"type": "free_date", "value": "2026-12-25", "description": "Giorno di Natale libero"},
                    {"type": "free_date", "value": "2027-01-01", "description": "Giorno di Capodanno libero"}
                ],
                "soft_constraints": []
            }
        }
    }
    
    print("\nEsecuzione della verifica di conformità...")
    report = agent.verify_compliance(test_preferences)
    print("\n=== REPORT DI CONFORMITÀ OTTENUTO ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))