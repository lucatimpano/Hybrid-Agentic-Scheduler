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
    RAG Agent responsible for institutional compliance validation.
    It evaluates custom soft constraints to check if they violate hospital rules.
    """
    def __init__(self, pdf_path: str = "data/input/regolamento_ospedaliero.pdf"):
        docs = self._load_documents(pdf_path)
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            add_start_index=True
        )
        all_splits = text_splitter.split_documents(docs)
        
        embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2")
        self.vector_store = InMemoryVectorStore(embeddings)
        self.vector_store.add_documents(documents=all_splits)
        
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
        
        self.llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)  # Cambiare per testare con Gemini 2.5/3.5 Flash
        #self.llm = ChatOllama(model="qwen3.5:0.8b", temperature=0)
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
        Extracts custom constraints from preferences and verifies them against regulations.
        Returns a dictionary with verdicts (approved true/false and reason).
        """
        workers_dict = preferences.get("workers", preferences)
        
        custom_payload = {}
        for worker_id, data in workers_dict.items():
            custom_constraints = [
                sc for sc in data.get("soft_constraints", [])
                if sc.get("type") == "custom"
            ]
            if custom_constraints:
                custom_payload[worker_id] = custom_constraints

        if not custom_payload:
            print("[RagAgent] Nessun vincolo custom trovato. Verifica saltata.")
            return {"custom_constraint_verdicts": {}}

        payload_json = json.dumps({"workers_custom_constraints": custom_payload}, indent=2)
        
        response = self.agent.invoke({
            "messages": [
                ("user", f"Evaluate the compliance of these custom constraints:\n\n{payload_json}")
            ]
        })
        
        print("\n=== PASSAGGI DELL'AGENTE (REASONING & TOOLS) ===")
        for msg in response["messages"]:
            role = "USER" if msg.type == "human" else "AI"
            print(f"\n[{role}]:")
            print(msg.content)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                print(f"-> Chiamata Tool: {msg.tool_calls}")
        print("================================================\n")
        
        last_message = response["messages"][-1].content
        if isinstance(last_message, list):
            last_message = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in last_message
            )
        
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
                "custom_constraint_verdicts": {},
                "error": "Risposta non in formato JSON valido",
                "raw_response": last_message
            }

if __name__ == "__main__":
    print("=== AVVIO AGENTE RAG COMPLIANCE ===")
    agent = RagAgent()
    
    test_preferences = {
        "workers": {
            "ID_0": {
                "role": "standard",
                "hard_constraints": [],
                "soft_constraints": [
                    {
                        "type": "custom",
                        "value": None,
                        "shift": None,
                        "weight": -6,
                        "natural_language": "Vorrei evitare di fare turni notturni se possibile.",
                        "description": "Evitare notti"
                    }
                ]
            }
        }
    }
    
    print("\nEsecuzione della verifica di conformità...")
    report = agent.verify_compliance(test_preferences)
    print("\n=== REPORT DI CONFORMITÀ OTTENUTO ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))