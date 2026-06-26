# Homeapp — Familien-Koordinations-App

Telegram-Erinnerungen, Kalenderbot und Küchen-Dashboard für die Familie.

## Features

- **Tägliche Telegram-Erinnerung** um 06:00 mit den heutigen Terminen
- **Wöchentliche Telegram-Erinnerung** jeden Montag um 06:00 mit allen Terminen der Woche
- **Telegram-Bot `/neuesevent`** zum Erstellen neuer Kalendereinträge
- **Küchen-Dashboard** (Tablet) mit Terminen und Einkaufsliste

---

## Voraussetzungen

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- Google-Konto mit Familien-Kalender
- Telegram-Accounts (beide Erwachsenen)
- [Todoist](https://todoist.com)-Konto

---

## 1. Google Calendar einrichten (~15 min)

1. [console.cloud.google.com](https://console.cloud.google.com) → Neues Projekt `homeapp`
2. **APIs & Dienste → Bibliothek** → **Google Calendar API** aktivieren
3. **Anmeldedaten → OAuth-Client-ID erstellen** → Typ: **Desktop App**
4. JSON herunterladen → als `credentials.json` im Projektverzeichnis speichern
5. OAuth-Einwilligungsbildschirm → Testbenutzer: deine Gmail-Adresse hinzufügen
6. Einmalig lokal ausführen um `token.json` zu erzeugen:
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/python3 app/gcalendar.py
   ```
   Ein Browser-Fenster öffnet sich → anmelden → Zugriff gewähren.
7. Kalender-ID des Familienkalenders ermitteln:
   Google Calendar → ⚙️ Kalendereinstellungen → **Kalender einbinden** → **Kalender-ID** kopieren

---

## 2. Telegram Bot einrichten (~5 min)

1. Telegram → **@BotFather** → `/newbot` → Name und Username wählen
2. Token kopieren (Format: `1234567890:AAH...`)
3. Chat-ID herausfinden: Bot eine Nachricht schicken, dann:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Die `"id"` unter `"chat"` ist die Chat-ID.

---

## 3. Todoist einrichten (~5 min)

1. [todoist.com](https://todoist.com) → **Einstellungen → Integrationen → Entwickler** → API-Token kopieren
2. Neues Projekt **Einkauf** erstellen

---

## 4. `.env` befüllen

```bash
cp .env.example .env
```

Alle Werte in `.env` eintragen:

| Variable | Beschreibung |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token von @BotFather |
| `TELEGRAM_CHAT_ID_1` | Deine Telegram Chat-ID |
| `TELEGRAM_CHAT_ID_2` | Chat-ID deiner Frau |
| `GOOGLE_CREDENTIALS_FILE` | `credentials.json` |
| `GOOGLE_TOKEN_FILE` | `token.json` |
| `GOOGLE_CALENDAR_ID` | Kalender-ID des Familienkalenders |
| `TODOIST_API_TOKEN` | Todoist API-Token |
| `TODOIST_PROJECT_NAME` | `Einkauf` |
| `OPENAI_API_KEY` | API-Key für natürliche Sprache im Telegram-Bot |
| `OPENAI_MODEL` | Optionales Modell, z.B. `gpt-4o-mini` |
| `OPENAI_BASE_URL` | Optionaler OpenAI-kompatibler API-Endpunkt |

---

## 5. Starten

```bash
docker compose up -d
```

Dashboard öffnen: `http://<IP-des-Servers>:8000`

Logs anzeigen:
```bash
docker compose logs -f
```

Stoppen:
```bash
docker compose down
```

---

## Auf dem Raspberry Pi deployen

```bash
# Repository klonen
git clone https://github.com/lstaehle/homeapp.git
cd homeapp

# credentials.json und token.json kopieren (z.B. via scp)
scp credentials.json token.json pi@raspberrypi:~/homeapp/

# .env befüllen
cp .env.example .env && nano .env

# Starten
docker compose up -d
```

Das Küchen-Tablet im Browser öffnen: `http://raspberrypi:8000`  
Für Kiosk-Modus (Vollbild, kein Browser-Chrome): **Fully Kiosk Browser** (Android) oder **Guided Access** (iPad).

---

## Telegram-Bot Befehle

| Befehl | Funktion |
|---|---|
| `/event` | Neuen Termin im Familienkalender erstellen |
| `/eventnl <Text>` | Termin aus natürlicher Sprache erstellen |
| `/abbrechen` | Aktuellen Dialog abbrechen |
| `/skip` | Beschreibungsschritt überspringen |

---

## Tests

```bash
make test-unit    # Unit- und Integrationstests (kein Docker nötig)
make test-system  # Systemtests (Docker erforderlich)
make test         # Alle Tests
```
