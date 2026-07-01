import os
from fpdf import FPDF

class HospitalRegulationsPDF(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 16)
        self.cell(0, 10, 'Azienda Ospedaliera Universitaria - Regolamento Interno', border=False, new_x="LMARGIN", new_y="NEXT", align='C')
        self.set_font('helvetica', 'I', 10)
        self.cell(0, 8, 'Direzione Sanitaria - Protocollo 2026/A-4421', border=False, new_x="LMARGIN", new_y="NEXT", align='C')
        self.ln(5)
        # Draw a horizontal line
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}/{{nb}} - Riservato ad uso interno', align='C')

def generate_pdf():
    pdf = HospitalRegulationsPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # Title
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 10, 'REGOLAMENTO GENERALE PER LA PIANIFICAZIONE DEI TURNI DI GUARDIA MEDICA', new_x="LMARGIN", new_y="NEXT", align='L')
    pdf.ln(3)

    pdf.set_font('helvetica', '', 10)
    pdf.multi_cell(0, 6, "Il presente documento definisce le direttive istituzionali e i vincoli contrattuali per la pianificazione dei turni di guardia medica all'interno dei reparti ospedalieri. Ciascun dipendente e l'algoritmo di pianificazione automatica sono tenuti a rispettare tassativamente le norme qui riportate.")
    pdf.ln(5)

    sections = [
        ("Articolo 1 - Orizzonte Temporale e Struttura dei Turni",
         "1.1. La pianificazione dei turni copre un orizzonte temporale standard mensile (31 giorni), con decorrenza dal 7 Dicembre 2026 al 6 Gennaio 2027.\n"
         "1.2. La giornata lavorativa e suddivisa in tre turni principali:\n"
         "  - Turno Mattutino (M): dalle ore 08:00 alle ore 14:00 (durata 6 ore, valore di calcolo turnazione: 1 turno).\n"
         "  - Turno Pomeridiano (P): dalle ore 14:00 alle ore 20:00 (durata 6 ore, valore di calcolo turnazione: 1 turno).\n"
         "  - Turno Notturno (N): dalle ore 20:00 alle ore 08:00 del giorno successivo (durata 12 ore, valore di calcolo turnazione: 2 turni)."),
        
        ("Articolo 2 - Limiti Orari e Riposo Obbligatorio",
         "2.1. Al fine di garantire la sicurezza dei pazienti e prevenire la fatica del personale medico, il limite massimo di ore lavorative per ciascun medico e fissato a 36 ore settimanali mobili su una finestra di 7 giorni consecutivi.\n"
         "2.2. A seguito dello svolgimento di un turno Notturno (N), e obbligatorio concedere al medico un periodo di riposo continuativo di almeno 48 ore prima dell'assegnazione di un nuovo turno (corrispondente a 2 giorni liberi consecutivi).\n"
         "2.3. Ciascun medico non puo svolgere piu di un turno all'interno della stessa giornata solare (massimo 1 turno al giorno)."),

        ("Articolo 3 - Fabbisogno Minimo e Copertura dei Servizi (Caso A e B)",
         "3.1. Ciascun turno di guardia (Mattina, Pomeriggio, Notte) deve essere coperto da un numero minimo di medici per garantire la continuita assistenziale.\n"
         "3.2. Configurazione Standard (Caso A - Medici Omogenei):\n"
         "  - Per ciascun turno (M, P, N) e richiesta la presenza contemporanea di almeno 2 medici generici/strutturati.\n"
         "3.3. Configurazione Specialistica (Caso B - Medici con Ruoli):\n"
         "  - Oltre alla copertura standard, in ogni turno e obbligatoria la presenza di almeno 1 medico con qualifica di Specialista o Vicedirettore."),

        ("Articolo 4 - Obblighi Mensili di Servizio",
         "4.1. Ogni medico in organico ha l'obbligo contrattuale di svolgere almeno 25 turni mensili equivalenti nel periodo considerato, salvo ferie precedentemente approvate o esenzioni certificate dalla direzione sanitaria."),

        ("Articolo 5 - Norme di Tutela e Direttive Speciali (RAG Constraints)",
         "5.1. Al fine di preservare l'equita e la salute, i medici con ruolo di Vicedirettore non possono in nessun caso svolgere piu di 1 turno di Notte a settimana.\n"
         "5.2. E severamente vietato richiedere la concessione di ferie o esenzioni consecutive che coprano contemporaneamente sia il giorno di Natale (25 Dicembre) sia il giorno di Capodanno (1 Gennaio). I medici devono garantire la presenza in almeno una delle due festivita.\n"
         "5.3. Le richieste di preferenza per giorni liberi specifici inserite dai medici (soft constraints) non possono superare un limite massimo di 4 giorni al mese per singolo operatore, per evitare la paralisi del sistema di turnazione.\n"
         "5.4. Qualsiasi richiesta di preferenza dei medici che entri in conflitto diretto con le norme del presente regolamento sara automaticamente considerata non conforme, segnalata all'amministratore del sistema e ignorata durante la fase di ottimizzazione matematica.")
    ]

    for title, content in sections:
        pdf.set_font('helvetica', 'B', 11)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT", align='L')
        pdf.set_font('helvetica', '', 9)
        pdf.multi_cell(0, 5, content)
        pdf.ln(3)

    # Save directory verification
    os.makedirs('data/input', exist_ok=True)
    pdf.output('data/input/regolamento_ospedaliero.pdf')
    print("PDF delle regole ospedaliere generato con successo in data/input/regolamento_ospedaliero.pdf")

if __name__ == '__main__':
    generate_pdf()
