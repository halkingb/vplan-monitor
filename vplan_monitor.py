#!/usr/bin/env python3
"""
Vertretungsplan Monitor für iOS Push-Benachrichtigungen
Überwacht Stundenplan24.de XML-Dateien auf Änderungen
Optimiert für GitHub Actions (speichert Status persistent)
"""

import requests
import xml.etree.ElementTree as ET
import json
import os
from datetime import datetime, timedelta

# Konfiguration laden
CONFIG_FILE = "config.json"
STATUS_FILE = "last_status.json"

def load_config():
    """Lädt die Konfiguration aus config.json"""
    if not os.path.exists(CONFIG_FILE):
        print("Fehler: config.json nicht gefunden!")
        print("Bitte erstelle die config.json Datei mit deinen Zugangsdaten.")
        exit(1)
    
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_last_status():
    """Lädt den letzten Status aus Datei"""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None
    return None

def save_status(all_entries):
    """Speichert den aktuellen Status in Datei"""
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'entries': all_entries
        }, f, indent=2, ensure_ascii=False)

def send_push(title, message, config):
    """Sendet Push-Benachrichtigung via ntfy.sh"""
    topic = config.get('ntfy_topic', 'vplan_monitor')
    
    # Entferne alle Nicht-ASCII Zeichen aus Title
    title_clean = title.encode('ascii', 'ignore').decode('ascii')
    
    try:
        response = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode('utf-8'),
            headers={
                "Title": title_clean,
                "Priority": "high",
                "Tags": "school,calendar"
            }
        )
        if response.status_code == 200:
            print(f"Push gesendet: {title}")
        else:
            print(f"Push-Fehler: Status {response.status_code}")
    except Exception as e:
        print(f"Fehler beim Senden: {e}")

def get_next_schooldays(days=5):
    """Gibt die nächsten X Schultage zurück (Mo-Fr)"""
    dates = []
    current = datetime.now()
    
    while len(dates) < days:
        # Überspringe Wochenenden (5=Sa, 6=So)
        if current.weekday() < 5:  # Mo-Fr
            dates.append(current)
        current += timedelta(days=1)
    
    return dates

def date_to_filename(date):
    """Konvertiert Datum zu XML-Dateiname: 20251001"""
    return date.strftime("%Y%m%d")

def fetch_vplan_xml(base_url, username, password, date):
    """Ruft XML-Vertretungsplan für ein bestimmtes Datum ab"""
    filename = date_to_filename(date)
    url = f"{base_url}vdaten/VplanLe{filename}.xml"
    
    try:
        session = requests.Session()
        
        # Login mit Username und Passwort (Basic Auth)
        response = session.get(url, auth=(username, password), timeout=10)
        
        if response.status_code == 404:
            return None  # Keine Daten für diesen Tag
        
        if response.status_code != 200:
            print(f"Warnung beim Abrufen von {url}: Status {response.status_code}")
            return None
        
        return response.text
    except Exception as e:
        print(f"Fehler beim Abrufen von {url}: {e}")
        return None

def parse_vplan_xml(xml_content, teacher_short):
    """Parst XML und extrahiert Vertretungen für einen Lehrer"""
    if not xml_content:
        return []
    
    try:
        root = ET.fromstring(xml_content)
        entries = []
        
        # Finde alle <aktion> Elemente (Vertretungen)
        for aktion in root.findall('.//aktion'):
            # vlehrer ist der vertretende Lehrer
            vlehrer = aktion.find('vlehrer')
            if vlehrer is not None and vlehrer.text:
                lehrer = vlehrer.text.strip()
                
                # Prüfe ob es der gesuchte Lehrer ist
                if lehrer.lower() == teacher_short.lower():
                    entry = {
                        'lehrer': lehrer,
                        'stunde': aktion.find('stunde').text if aktion.find('stunde') is not None else '',
                        'klasse': aktion.find('klasse').text if aktion.find('klasse') is not None else '',
                        'fach_neu': aktion.find('vfach').text if aktion.find('vfach') is not None else '',
                        'raum_neu': aktion.find('vraum').text if aktion.find('vraum') is not None else '',
                        'fuer_fach': aktion.find('fach').text if aktion.find('fach') is not None else '',
                        'fuer_lehrer': aktion.find('lehrer').text if aktion.find('lehrer') is not None else '',
                        'info': aktion.find('info').text if aktion.find('info') is not None else '',
                        'geaendert': vlehrer.get('legeaendert') == 'ae'
                    }
                    entries.append(entry)
        
        return entries
    except ET.ParseError as e:
        print(f"XML Parse-Fehler: {e}")
        return []

def format_entry(entry, date):
    """Formatiert einen Eintrag für die Push-Nachricht"""
    weekday = date.strftime("%a, %d.%m")
    msg = f"{weekday} | Std. {entry['stunde']}: {entry['klasse']}"
    
    if entry['fach_neu']:
        msg += f" - {entry['fach_neu']}"
    if entry['raum_neu']:
        msg += f" in {entry['raum_neu']}"
    if entry['fuer_lehrer']:
        msg += f" (fuer {entry['fuer_lehrer']})"
    if entry['info']:
        msg += f" [{entry['info']}]"
    
    return msg

def main():
    """Hauptfunktion - optimiert für GitHub Actions"""
    config = load_config()
    
    teacher_short = config['teacher_short']
    base_url = config['vplan_url']
    username = config['username']
    password = config['password']
    days_ahead = config.get('days_ahead', 5)
    
    print(f"Vertretungsplan Monitor (GitHub Actions)")
    print(f"Ueberwache Lehrer: {teacher_short}")
    print(f"Tage voraus: {days_ahead}")
    print(f"Push-Topic: {config.get('ntfy_topic', 'vplan_monitor')}")
    print("-" * 60)
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now}] Pruefe Vertretungsplaene...")
    
    # Hole nächste Schultage
    schooldays = get_next_schooldays(days_ahead)
    all_entries = {}
    
    # Prüfe jeden Schultag
    for date in schooldays:
        date_str = date.strftime("%d.%m.%Y")
        print(f"  Pruefe {date_str}...", end=" ")
        
        xml_content = fetch_vplan_xml(base_url, username, password, date)
        
        if xml_content:
            entries = parse_vplan_xml(xml_content, teacher_short)
            if entries:
                all_entries[date_str] = entries
                print(f"OK {len(entries)} Vertretung(en)")
            else:
                print("OK keine Vertretungen")
        else:
            print("- keine Daten")
    
    total_count = sum(len(v) for v in all_entries.values())
    print(f"\nGesamt: {total_count} Vertretung(en) an {len(all_entries)} Tag(en)")
    
    # Lade letzten Status
    last_status = load_last_status()
    
    # Vergleiche mit letztem Status
    if last_status is None:
        # Erster Durchlauf überhaupt
        print("Erster Durchlauf - speichere initialen Status")
        save_status(all_entries)
        
        if all_entries:
            msg = f"Aktuell {total_count} Vertretung(en):\n\n"
            for date_str, entries in sorted(all_entries.items()):
                date_obj = datetime.strptime(date_str, "%d.%m.%Y")
                for entry in entries:
                    msg += format_entry(entry, date_obj) + "\n"
            send_push("Monitor gestartet", msg, config)
        else:
            send_push("Monitor gestartet", "Keine Vertretungen gefunden", config)
    
    elif all_entries != last_status.get('entries', {}):
        # Änderung erkannt!
        print("\nAENDERUNG ERKANNT!")
        save_status(all_entries)
        
        if not all_entries:
            send_push("Plan aktualisiert", "Alle Vertretungen entfernt!", config)
        else:
            msg = f"{total_count} Vertretung(en):\n\n"
            for date_str, entries in sorted(all_entries.items()):
                date_obj = datetime.strptime(date_str, "%d.%m.%Y")
                for entry in entries:
                    msg += format_entry(entry, date_obj) + "\n"
            send_push("PLAN GEAENDERT!", msg, config)
    else:
        print("OK Keine Aenderungen")

if __name__ == "__main__":
    main()
