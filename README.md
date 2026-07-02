# SmartScheduler: Hybrid Multi-Agent Scheduling System

<div align="center">

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![React](https://img.shields.io/badge/react-%2320232a.svg?style=for-the-badge&logo=react&logoColor=%2361DAFB)
![TypeScript](https://img.shields.io/badge/typescript-%23007ACC.svg?style=for-the-badge&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/vite-%23646CFF.svg?style=for-the-badge&logo=vite&logoColor=white)

![Google Gemini](https://img.shields.io/badge/Google%20Gemini-8E75C2?style=for-the-badge&logo=googlegemini&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=for-the-badge&logo=chainlink&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=for-the-badge&logo=ollama&logoColor=white)
![Google OR-Tools](https://img.shields.io/badge/Google%20OR--Tools-4285F4?style=for-the-badge&logo=google&logoColor=white)
![RAG Compliance](https://img.shields.io/badge/RAG-Compliance-FF6F61?style=for-the-badge&logo=read-the-docs&logoColor=white)

</div>

---

SmartScheduler is a hybrid system designed to automate and optimize the scheduling of hospital guard shifts for medical staff. 

By combining the mathematical precision of **Constraint Programming (Google OR-Tools CP-SAT)** with the cognitive capabilities of **Large Language Models (Gemini, LangChain/LangGraph, Ollama)**, the project aims to solve complex scheduling tasks. It allows for the processing of unstructured user requests (natural language preferences) and auditing compliance against hospital rules, while maintaining strict mathematical feasibility.

---

## 🛠️ Tech Stack & Key Technologies

*   **Optimization Engine**: `Google OR-Tools (CP-SAT Solver)` - Used to enforce hard schedule requirements and maximize equity/fairness in shift distribution.
*   **Orchestration & Agents**: `LangGraph` & `LangChain` - Used to structure the multi-agent reasoning flow.
*   **LLM Providers**:
    *   **Cloud API**: `Google Gemini` (`gemini-2.5-flash`, `gemini-3.5-flash`) for advanced parsing and orchestration.
    *   **Local Execution**: `Ollama` (`qwen3.5:0.8b` / `llama3.2`) for local private execution and cost optimization.
*   **Vector Database**: `InMemoryVectorStore` with `GoogleGenerativeAIEmbeddings` for auditing compliance against PDF documents.
*   **Frontend UI**: `React` + `Vite` + `TypeScript` - Interactive dashboard for schedule visualization.

---

## 🚀 Getting Started

### Prerequisites
*   Python 3.10+
*   Node.js & npm (for the UI)
*   Ollama (optional, for running local models)

### Backend Setup
1.  Clone the repository.
2.  Create and activate a virtual environment:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```
3.  Install backend dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Configure the environment variables in a `.env` file at the root of the project:
    ```env
    GEMINI_API_KEY=your_gemini_api_key_here
    ```

### Running the Tests
To verify the pipeline execution:
```bash
PYTHONPATH=. .venv/bin/python3 test/test_pipeline.py
```
