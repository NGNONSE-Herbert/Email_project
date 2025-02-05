from flask import Flask, render_template, request, redirect, url_for, flash
import imaplib
import email
from email.header import decode_header
import os
import re
import unicodedata
import logging
from dotenv import load_dotenv
import sys

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# Initialiser Flask
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key')  # Clé secrète chargée depuis .env

# Configurer la journalisation
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

# Ajouter un gestionnaire de fichier pour la journalisation
file_handler = logging.FileHandler('app.log')
file_handler.setLevel(logging.INFO)  # Niveau d'info pour ne pas loguer des infos trop sensibles
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logging.getLogger().addHandler(file_handler)

# Dossier pour stocker les pièces jointes
ATTACHMENTS_FOLDER = "attachments"
if not os.path.isdir(ATTACHMENTS_FOLDER):
    os.makedirs(ATTACHMENTS_FOLDER, exist_ok=True)

# Fonction pour nettoyer les noms de fichiers
def clean_filename(filename):
    decoded_parts = decode_header(filename)
    decoded_filename = ''
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            if encoding is None:
                decoded_filename += part.decode('utf-8', errors='ignore')
            else:
                decoded_filename += part.decode(encoding, errors='ignore')
        else:
            decoded_filename += part
    filename = unicodedata.normalize('NFKD', decoded_filename).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)  # Remplacer les caractères non sécurisés

# Fonction pour obtenir les paramètres IMAP en fonction du fournisseur
def get_imap_settings(email_address):
    if '@' in email_address:
        domain = email_address.split('@')[-1]
        if "gmail.com" in domain:
            return "imap.gmail.com", 993
        elif "outlook.com" in domain or "office365.com" in domain:
            return "outlook.office365.com", 993
        elif "yahoo.com" in domain:
            return "imap.mail.yahoo.com", 993
        else:
            raise ValueError("Fournisseur de messagerie non pris en charge")
    else:
        raise ValueError("L'adresse fournie semble invalide.")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        email_address = request.form['email']
        password = request.form['password']
        sender = request.form['sender']  # Récupérer l'expéditeur
        subject = request.form['subject']  # Récupérer l'objet

        if not password:
            flash("Le mot de passe ne peut pas être vide.", "error")
            logging.error(f"Le mot de passe pour l'email {email_address} est vide.")
            return redirect(url_for('index'))

        logging.info(f"Connexion demandée pour l'email : {email_address}")

        # Masquer le mot de passe dans les logs et l'URL
        return redirect(url_for('fetch_emails', email=email_address, password='******', sender=sender, subject=subject))
    
    return render_template('index.html')

@app.route('/fetch_emails', methods=['GET', 'POST'])
def fetch_emails():
    if request.method == 'POST' or request.args:
        email_address = request.form['email'] if request.method == 'POST' else request.args.get('email')
        password = request.form['password'] if request.method == 'POST' else request.args.get('password')
        sender = request.form['sender'] if request.method == 'POST' else request.args.get('sender')
        subject = request.form['subject'] if request.method == 'POST' else request.args.get('subject')

        try:
            logging.info(f"Début de la récupération des e-mails pour {email_address}")
            imap_server, imap_port = get_imap_settings(email_address)

            # Connexion à l'IMAP
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
            mail.login(email_address, password)  # NE PAS loguer le mot de passe
            logging.info(f"Connexion IMAP réussie pour {email_address}")
            mail.select("inbox")

            # Créer un critère de recherche pour l'expéditeur et l'objet
            search_criteria = []
            if sender:
                search_criteria.append(f'FROM "{sender}"')
            if subject:
                search_criteria.append(f'SUBJECT "{subject}"')

            # Concaténer les critères de recherche (si présents)
            search_query = " ".join(search_criteria) if search_criteria else 'ALL'
            
            status, messages = mail.search(None, search_query)
            email_ids = messages[0].split()
            logging.info(f"Nombre d'e-mails trouvés : {len(email_ids)}")

            for e_id in email_ids:
                _, msg_data = mail.fetch(e_id, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding if encoding else 'utf-8')
                        logging.info(f"Sujet de l'email : {subject}")

                        # Traiter les pièces jointes
                        for part in msg.walk():
                            if part.get_content_maintype() == 'multipart':
                                continue
                            if part.get('Content-Disposition') is None:
                                continue

                            filename = part.get_filename()
                            if filename:
                                filename = clean_filename(filename)
                                filepath = os.path.join(ATTACHMENTS_FOLDER, filename)
                                with open(filepath, 'wb') as f:
                                    f.write(part.get_payload(decode=True))
                                logging.info(f"Pièce jointe sauvegardée : {filename}")

            mail.logout()
            flash("E-mails et pièces jointes récupérés avec succès!", "success")
            logging.info("E-mails et pièces jointes récupérés avec succès.")
            return redirect(url_for('index'))

        except imaplib.IMAP4.error as e:
            logging.error(f"Erreur de connexion IMAP : {str(e)}")
            flash("Erreur de connexion : e-mail ou mot de passe incorrect.", "error")
            return redirect(url_for('index'))
        except Exception as e:
            logging.error(f"Une erreur est survenue : {str(e)}")
            flash(f"Une erreur est survenue : {str(e)}", "error")
            return redirect(url_for('index'))

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
