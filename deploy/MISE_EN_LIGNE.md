# Mise en ligne de Ghelia Finance sur PythonAnywhere

Adresse du site : **https://germainbob.pythonanywhere.com**
Compte : `germainbob` · Durée : environ 30 minutes.

---

## Étape 1 : copier le code sur PythonAnywhere

1. Connectez-vous sur https://www.pythonanywhere.com.
2. Onglet **Consoles** → **Bash** (une fenêtre noire s'ouvre).
3. Tapez ces commandes une par une (Entrée après chaque ligne) :

```bash
git clone https://github.com/mojou/tontine_app.git
cd tontine_app
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

L'installation prend 2 à 5 minutes.

## Étape 2 : créer la base et le compte super-admin

Toujours dans la console :

```bash
python setup_multitenant.py
```

Un **mot de passe super-admin** s'affiche **une seule fois** : notez-le tout de suite.

## Étape 3 : créer le site

1. Onglet **Web** → **Add a new web app** → **Next**.
2. Choisissez **Manual configuration** (pas « Flask »), puis **Python 3.13** → **Next**.
3. Dans la page Web qui s'affiche :
   - **Virtualenv** : cliquez sur le lien et collez `/home/germainbob/tontine_app/venv`.
   - **Static files** : URL `/static/`, Directory `/home/germainbob/tontine_app/app/static`.
   - **Force HTTPS** : activez-le (en bas de la page).

## Étape 4 : le fichier de démarrage (WSGI)

1. Dans l'onglet **Web**, cliquez sur le lien **WSGI configuration file**
   (`/var/www/germainbob_pythonanywhere_com_wsgi.py`).
2. **Effacez tout** son contenu.
3. Copiez-collez le contenu du fichier `deploy/pythonanywhere_wsgi.py` du projet.
4. Sur la ligne `BREVO_API_KEY`, remplacez `COLLEZ_ICI_LA_CLE_BREVO` par votre clé API Brevo
   (voir « E-mails : compte Brevo » ci-dessous).
5. **Save**.

> Cette clé ne doit apparaître que dans ce fichier, sur votre compte PythonAnywhere.
> Ne la mettez jamais dans GitHub ni dans un message.

### E-mails : compte Brevo

Le compte gratuit PythonAnywhere **bloque l'envoi par SMTP** (Gmail compris). Les e-mails passent donc
par **Brevo** (gratuit, environ 300 e-mails par jour), autorisé par PythonAnywhere.

1. Créez un compte sur https://www.brevo.com avec **ghelia.finance@gmail.com**.
2. **Expéditeurs** (Senders, Domains & Dedicated IPs → Senders) : ajoutez
   « Ghelia Finance » / ghelia.finance@gmail.com et validez le code reçu dans cette boîte.
3. **Clés API** (SMTP & API → API Keys) : « Generate a new API key », nommez-la « Ghelia Finance »,
   copiez la clé (elle commence par `xkeysib-`).

## Étape 5 : démarrer et vérifier

1. Onglet **Web** → bouton vert **Reload**.
2. Ouvrez https://germainbob.pythonanywhere.com : la page d'accueil, les tarifs, la FAQ et le guide s'affichent.
3. Connectez-vous en super-admin sur https://germainbob.pythonanywhere.com/administration (adresse réservée, non affichée sur le site) avec le mot de passe de l'étape 2.
4. Test de l'e-mail : créez une tontine d'essai avec votre adresse personnelle, vérifiez que l'e-mail
   de confirmation arrive (regardez aussi les indésirables), cliquez sur le lien.
   Puis supprimez cette tontine d'essai depuis l'espace super-admin.

En cas d'erreur : onglet **Web** → **Error log** (dernières lignes) : envoyez-les-moi.

---

## Ensuite

- **Tous les 3 mois** : onglet Web → **Run until 3 months from today** (un e-mail de rappel arrive avant).
  Astuce : cliquez-le à chaque réunion de fin de mois.
- **Mettre à jour le site** après une publication sur GitHub :

```bash
cd ~/tontine_app && source venv/bin/activate && git pull && pip install -r requirements.txt
```

  puis **Reload** dans l'onglet Web.
- **Sauvegarde quotidienne** (recommandé) : onglet **Tasks** → une tâche par jour :
  `cd ~/tontine_app && venv/bin/python backup.py`
- **Lien SasPay** : dans le fichier WSGI, ligne `SASPAY_PAYMENT_URL`, puis **Reload**.
