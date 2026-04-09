"""
Spritzmittel Telegram Bot
=========================
Schick eine Nachricht wie:
  "Roundup 2.5l Weizen"
  "Folicur 1.5 Raps 4ha"
  "liste" → zeigt alle Einträge
  "hilfe" → zeigt Befehle

Der Bot trägt alles automatisch in die HTML-App ein.
"""

import json
import os
import re
from datetime import datetime, date
from pathlib import Path

try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError:
    print("FEHLER: Bitte zuerst install.bat ausführen!")
    input("Drücke Enter zum Beenden...")
    exit()

# ─── KONFIGURATION ────────────────────────────────────────────────────────────
# TOKEN wird aus config.json gelesen (wird beim ersten Start erstellt)
TOKEN_FILE = Path(__file__).parent / "token.txt"
DATA_FILE   = Path(__file__).parent / "eintraege.json"

# Spritzmittel-Datenbank (Wirkstoff + Wartefrist automatisch)
MITTEL_DB = {
    "roundup":        {"name": "Roundup PowerFlex",  "wirkstoff": "Glyphosat",           "einsatz": "Herbizid",    "wartefrist": 7},
    "rounduppowerflex":{"name":"Roundup PowerFlex",  "wirkstoff": "Glyphosat",           "einsatz": "Herbizid",    "wartefrist": 7},
    "amistar":        {"name": "Amistar Opti",        "wirkstoff": "Azoxystrobin",        "einsatz": "Fungizid",    "wartefrist": 0},
    "amisturopti":    {"name": "Amistar Opti",        "wirkstoff": "Azoxystrobin",        "einsatz": "Fungizid",    "wartefrist": 0},
    "folicur":        {"name": "Folicur EW 250",      "wirkstoff": "Tebuconazol",         "einsatz": "Fungizid",    "wartefrist": 14},
    "folicurew":      {"name": "Folicur EW 250",      "wirkstoff": "Tebuconazol",         "einsatz": "Fungizid",    "wartefrist": 14},
    "bravo":          {"name": "Bravo 500",            "wirkstoff": "Chlorothalonil",      "einsatz": "Fungizid",    "wartefrist": 28},
    "karate":         {"name": "Karate Zeon",          "wirkstoff": "Lambda-Cyhalothrin", "einsatz": "Insektizid",  "wartefrist": 3},
    "karatezeon":     {"name": "Karate Zeon",          "wirkstoff": "Lambda-Cyhalothrin", "einsatz": "Insektizid",  "wartefrist": 3},
    "decis":          {"name": "Decis forte",          "wirkstoff": "Deltamethrin",        "einsatz": "Insektizid",  "wartefrist": 7},
    "decisforte":     {"name": "Decis forte",          "wirkstoff": "Deltamethrin",        "einsatz": "Insektizid",  "wartefrist": 7},
    "stomp":          {"name": "Stomp Aqua",           "wirkstoff": "Pendimethalin",       "einsatz": "Herbizid",    "wartefrist": 56},
    "stompaqua":      {"name": "Stomp Aqua",           "wirkstoff": "Pendimethalin",       "einsatz": "Herbizid",    "wartefrist": 56},
    "select":         {"name": "Select 240 EC",        "wirkstoff": "Clethodim",           "einsatz": "Herbizid",    "wartefrist": 0},
    "select240":      {"name": "Select 240 EC",        "wirkstoff": "Clethodim",           "einsatz": "Herbizid",    "wartefrist": 0},
}

KULTUREN_ALIASES = {
    "weizen": "Weizen", "winterweizen": "Weizen",
    "gerste": "Gerste", "wintergerste": "Gerste", "sommergerste": "Gerste",
    "raps": "Raps", "winterraps": "Raps",
    "mais": "Mais",
    "zucker": "Zuckerrüben", "zuckerrüben": "Zuckerrüben", "rüben": "Zuckerrüben",
    "kartoffeln": "Kartoffeln", "erdäpfel": "Kartoffeln",
    "soja": "Soja",
    "grünland": "Grünland", "wiese": "Grünland", "gras": "Grünland",
    "obst": "Obstanlage", "obstanlage": "Obstanlage",
    "gemüse": "Gemüse",
}

# ─── HILFSFUNKTIONEN ──────────────────────────────────────────────────────────

def lade_token():
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""

def lade_eintraege():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []

def speichere_eintrag(eintrag):
    eintraege = lade_eintraege()
    eintraege.insert(0, eintrag)
    DATA_FILE.write_text(json.dumps(eintraege, ensure_ascii=False, indent=2), encoding="utf-8")
    aktualisiere_html_app(eintraege)
    return eintraege

def aktualisiere_html_app(eintraege):
    """Schreibt die Einträge als JavaScript-Variable in die HTML-App."""
    html_datei = Path(__file__).parent / "Spritzmittelerfassung.html"
    if not html_datei.exists():
        return  # HTML-Datei nicht vorhanden, nur JSON speichern

    inhalt = html_datei.read_text(encoding="utf-8")
    json_str = json.dumps(eintraege, ensure_ascii=False)
    marker_start = "// BOT_DATEN_START"
    marker_end   = "// BOT_DATEN_END"
    neuer_block  = f"{marker_start}\nentries = {json_str};\nlsSet('spritz_entries', entries);\n{marker_end}"

    if marker_start in inhalt:
        inhalt = re.sub(
            rf"{re.escape(marker_start)}.*?{re.escape(marker_end)}",
            neuer_block,
            inhalt,
            flags=re.DOTALL
        )
    else:
        inhalt = inhalt.replace("populateSelects();", f"populateSelects();\n{neuer_block}")

    html_datei.write_text(inhalt, encoding="utf-8")

def parse_nachricht(text):
    """
    Versucht aus einer freien Textnachricht die Felder zu extrahieren.
    Beispiele:
      "Roundup 2.5l Weizen"
      "Folicur 1.5 Raps 4ha"
      "Karate 0.1l Gerste Schlag-Nord 2.5ha"
    """
    text_clean = text.strip()
    tokens = text_clean.split()

    erkannt = {
        "datum": date.today().isoformat(),
        "mittel": None,
        "mittel_info": None,
        "kultur": None,
        "menge": None,
        "flaeche": None,
        "schlag": None,
    }

    rest_tokens = []

    for token in tokens:
        token_lower = re.sub(r'[^a-z0-9äöü]', '', token.lower())

        # Spritzmittel erkennen
        if erkannt["mittel"] is None and token_lower in MITTEL_DB:
            erkannt["mittel_info"] = MITTEL_DB[token_lower]
            erkannt["mittel"] = erkannt["mittel_info"]["name"]
            continue

        # Menge erkennen (z.B. "2.5l", "1,5", "2.5kg")
        if erkannt["menge"] is None:
            m = re.match(r'^(\d+[.,]\d+|\d+)\s*(?:l|kg|ml)?$', token.lower())
            if m:
                erkannt["menge"] = m.group(1).replace(',', '.')
                continue

        # Fläche erkennen (z.B. "4ha", "3.5ha")
        m = re.match(r'^(\d+[.,]\d+|\d+)\s*ha$', token.lower())
        if m:
            erkannt["flaeche"] = m.group(1).replace(',', '.')
            continue

        # Kultur erkennen
        if erkannt["kultur"] is None and token_lower in KULTUREN_ALIASES:
            erkannt["kultur"] = KULTUREN_ALIASES[token_lower]
            continue

        rest_tokens.append(token)

    # Schlag/Bemerkung aus Rest
    if rest_tokens:
        erkannt["schlag"] = " ".join(rest_tokens)

    return erkannt

def formatiere_wartefrist(wf, datum_str):
    if wf == 0:
        return "✅ Keine Wartefrist"
    try:
        spray_datum = date.fromisoformat(datum_str)
        heute = date.today()
        vergangen = (heute - spray_datum).days
        verbleibend = wf - vergangen
        if verbleibend > 0:
            ablauf = spray_datum.strftime("%d.%m.%Y")
            return f"⏳ {wf} Tage — noch {verbleibend} Tage ({ablauf})"
        else:
            return f"✅ {wf} Tage — bereits abgelaufen"
    except:
        return f"⏳ {wf} Tage"

# ─── BOT HANDLER ──────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌿 *Spritzmittelerfassung Bot*\n\n"
        "Schick mir einfach eine Nachricht, z.B.:\n"
        "`Roundup 2.5l Weizen`\n"
        "`Folicur 1.5 Raps 4ha`\n"
        "`Karate 0.1l Gerste Schlag-Nord`\n\n"
        "Befehle:\n"
        "/liste — letzte Einträge anzeigen\n"
        "/wartefristen — aktive Wartefristen\n"
        "/hilfe — alle Spritzmittel\n",
        parse_mode="Markdown"
    )

async def cmd_hilfe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mittel_liste = "\n".join([f"• {v['name']} ({v['einsatz']}, {v['wartefrist']}d WF)" 
                               for k, v in MITTEL_DB.items() if k == v['name'].lower().replace(' ','')])
    bekannte = sorted(set(v['name'] for v in MITTEL_DB.values()))
    text = "📋 *Bekannte Spritzmittel:*\n" + "\n".join(f"• {m}" for m in bekannte)
    text += "\n\n_Weitere Mittel einfach ausschreiben — ich lerne dazu!_"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    eintraege = lade_eintraege()
    if not eintraege:
        await update.message.reply_text("Noch keine Einträge vorhanden.")
        return
    letzte = eintraege[:5]
    text = "📊 *Letzte 5 Einträge:*\n\n"
    for e in letzte:
        text += f"📅 {e['datum']} — *{e['mittel']}*\n"
        text += f"   🌱 {e.get('kultur','?')}  |  💧 {e.get('menge','?')} l/kg/ha\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_wartefristen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    eintraege = lade_eintraege()
    heute = date.today()
    aktive = []
    for e in eintraege:
        wf = e.get("wartefrist")
        if wf and int(wf) > 0 and e.get("datum"):
            try:
                spray = date.fromisoformat(e["datum"])
                rem = int(wf) - (heute - spray).days
                if rem > 0:
                    aktive.append((rem, e))
            except:
                pass
    if not aktive:
        await update.message.reply_text("✅ Keine aktiven Wartefristen.")
        return
    aktive.sort(key=lambda x: x[0])
    text = "⚠️ *Aktive Wartefristen:*\n\n"
    for rem, e in aktive:
        text += f"🔴 *{e['mittel']}* — {rem} Tage verbleibend\n"
        text += f"   {e.get('kultur','?')} | gespritzt am {e['datum']}\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_nachricht(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Kurzbefehle abfangen
    if text.lower() in ["liste", "einträge"]:
        await cmd_liste(update, context)
        return
    if text.lower() in ["hilfe", "help", "?"]:
        await cmd_hilfe(update, context)
        return
    if text.lower() in ["wartefristen", "wf"]:
        await cmd_wartefristen(update, context)
        return

    # Eintrag parsen
    erkannt = parse_nachricht(text)

    if not erkannt["mittel"]:
        await update.message.reply_text(
            "❓ Spritzmittel nicht erkannt.\n\n"
            "Beispiel: `Roundup 2.5l Weizen`\n"
            "Oder /hilfe für alle bekannten Mittel.",
            parse_mode="Markdown"
        )
        return

    # Eintrag zusammenbauen
    info = erkannt["mittel_info"]
    eintrag = {
        "id": int(datetime.now().timestamp() * 1000),
        "datum": erkannt["datum"],
        "mittel": erkannt["mittel"],
        "wirkstoff": info["wirkstoff"],
        "einsatz": info["einsatz"],
        "wartefrist": str(info["wartefrist"]),
        "kultur": erkannt["kultur"] or "",
        "menge": erkannt["menge"] or "",
        "flaeche": erkannt["flaeche"] or "",
        "wasser": "",
        "witterung": "",
        "temp": "",
        "anwender": update.message.from_user.first_name or "",
        "bemerkung": erkannt["schlag"] or "",
    }

    speichere_eintrag(eintrag)

    # Bestätigung
    wf_text = formatiere_wartefrist(info["wartefrist"], erkannt["datum"])
    antwort = (
        f"✅ *Eintrag gespeichert!*\n\n"
        f"📋 *{eintrag['mittel']}*\n"
        f"🧪 Wirkstoff: {info['wirkstoff']}\n"
        f"🎯 Einsatz: {info['einsatz']}\n"
    )
    if eintrag["kultur"]:
        antwort += f"🌱 Kultur: {eintrag['kultur']}\n"
    if eintrag["menge"]:
        antwort += f"💧 Menge: {eintrag['menge']} l/kg/ha\n"
    if eintrag["flaeche"]:
        antwort += f"📐 Fläche: {eintrag['flaeche']} ha\n"
    antwort += f"📅 Datum: {erkannt['datum']}\n"
    antwort += f"⏱ Wartefrist: {wf_text}\n\n"
    antwort += "_Eintrag wurde in der App gespeichert._"

    await update.message.reply_text(antwort, parse_mode="Markdown")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    token = lade_token()

    if not token:
        print("\n" + "="*50)
        print("  SPRITZMITTEL BOT - ERSTE EINRICHTUNG")
        print("="*50)
        print("\nDu brauchst einen Telegram Bot Token.")
        print("Anleitung:")
        print("1. Oeffne Telegram, suche: @BotFather")
        print("2. Schreibe: /newbot")
        print("3. Befolge die Schritte, du bekommst einen Token")
        print("   Sieht so aus: 1234567890:ABCdefGHIjklMNO\n")
        token = input("Token einfuegen und Enter druecken: ").strip()
        TOKEN_FILE.write_text(token, encoding="utf-8")
        print("Token gespeichert!\n")

    print("\n" + "="*50)
    print("  🌿 SPRITZMITTELERFASSUNG BOT LÄUFT")
    print("="*50)
    print(f"\n✅ Bot gestartet — warte auf Nachrichten...")
    print("   (Fenster offen lassen — zum Beenden: Strg+C)\n")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("hilfe", cmd_hilfe))
    app.add_handler(CommandHandler("liste", cmd_liste))
    app.add_handler(CommandHandler("wartefristen", cmd_wartefristen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_nachricht))
    app.run_polling()

if __name__ == "__main__":
    main()
