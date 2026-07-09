import json
import os
from langchain_core.globals import set_debug

# Disabilita il debug mode
set_debug(False)

from src.agents.orchestrator import create_scheduler_graph

def main():
    # Seleziona il caso: "a" per Caso A (13 workers standard), "b" per Caso B (20 workers con specialisti)
    CASE = "a"

    input_file = f"data/input/workers_preferences{'_caso_b' if CASE == 'b' else ''}.txt"
    output_file = "data/output/final_schedule.json"
    
    if not os.path.exists(input_file):
        print(f"Errore: il file di input '{input_file}' non esiste.")
        return

    print("=== AVVIO HYBRID-AGENTIC-SCHEDULER ===")
    print(f"Lettura preferenze da: {input_file}")
    
    with open(input_file, "r", encoding="utf-8") as f:
        raw_preferences = f.read()

    # Creazione e compilazione del grafo LangGraph
    print("\nInizializzazione grafo...")
    graph = create_scheduler_graph()

    # Definizione dello stato iniziale
    # Nota: passiamo il testo grezzo nel campo "preferences".
    # Il worker_node si occuperà di fare il parsing e trasformarlo in dict.
    initial_state = {
        "preferences": raw_preferences,
        "violations": [],
        "error_count": 0,
        "iteration": 0,
        "prev_min_score": 0,
        "fairness_gap": 0
    }

    print("\nEsecuzione del grafo (può richiedere qualche minuto)...\n")
    
    final_state = dict(initial_state)
    for step_data in graph.stream(initial_state, {"recursion_limit": 50}):
        for node_name, node_state in step_data.items():
            print(f"--- Finito step: {node_name} ---")
            final_state.update(node_state)

    print("\n=== ESECUZIONE TERMINATA ===")
    
    # Se il grafo ha restituito un final_state, analizziamo il risultato
    if final_state:
        if final_state.get("violations"):
            print("\n[FALLIMENTO] Il sistema ha terminato con le seguenti violazioni:")
            for v in final_state["violations"]:
                print(f"- {v}")
        elif final_state.get("schedule"):
            print("\n[SUCCESSO] Turnazione generata correttamente!")
            
            # Creiamo la cartella di output se non esiste
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Salviamo lo schedule su file (estraendo gli assignments per pulizia)
            schedule_dict = final_state["schedule"]
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(schedule_dict, f, indent=4, ensure_ascii=False)
                
            print(f"Turnazione finale salvata in: {output_file}")
            
            # Stampiamo qualche metadato di fairness finale se presente
            if final_state.get("worst_worker"):
                print("\nMetriche di Equità Finali:")
                print(f"- Medico peggiore: {final_state['worst_worker']} (Punteggio: {final_state.get('prev_min_score')})")
                print(f"- Fairness Gap finale: {final_state.get('fairness_gap')}")
        else:
            print("\nNessuna turnazione generata e nessuna violazione registrata. Stato anomalo.")

if __name__ == "__main__":
    main()
