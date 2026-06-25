#!/usr/bin/env python3
import sqlite3, os, time, signal, sys
from datetime import datetime

try:
    from mfrc522 import SimpleMFRC522
    import RPi.GPIO as GPIO
    RFID_OK = True
except ImportError:
    RFID_OK = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "rfid.db")
DEBOUNCE = 2

def get_db():
    conn = sqlite3.connect(DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def procesar(uid):
    conn = get_db()
    hoy = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c = conn.cursor()
    c.execute("SELECT t.activa, t.id_estudiante, e.nombre, e.apellido_paterno, e.estado FROM tarjetas t LEFT JOIN estudiantes e ON t.id_estudiante=e.id WHERE t.uid=?", (uid,))
    t = c.fetchone()
    if not t:
        c.execute("INSERT INTO registros_asistencia (id_estudiante,uid,timestamp,fecha_dia,tipo_evento,mensaje) VALUES (NULL,?,?,?,'rebote','UID no registrado')", (uid, ts, hoy))
        conn.commit()
        conn.close()
        return "rebote", "DESCONOCIDO", "UID no registrado"
    nombre = ((t["nombre"] or "") + " " + (t["apellido_paterno"] or "")).strip()
    if not t["activa"] or t["estado"] != "activo":
        c.execute("INSERT INTO registros_asistencia (id_estudiante,uid,timestamp,fecha_dia,tipo_evento,mensaje) VALUES (?,?,?,?,'rebote','Inactivo')", (t["id_estudiante"], uid, ts, hoy))
        conn.commit()
        conn.close()
        return "rebote", nombre, "Inactivo"
    c.execute("SELECT COUNT(*) as n FROM registros_asistencia WHERE uid=? AND fecha_dia=? AND tipo_evento='aceptado'", (uid, hoy))
    veces = c.fetchone()["n"]
    tipo = "ya_escaneado" if veces > 0 else "aceptado"
    msg = "Ya registrado " + str(veces+1) + "a vez" if veces > 0 else "Acceso permitido"
    c.execute("INSERT INTO registros_asistencia (id_estudiante,uid,timestamp,fecha_dia,tipo_evento,mensaje) VALUES (?,?,?,?,?,?)", (t["id_estudiante"], uid, ts, hoy, tipo, msg))
    conn.commit()
    conn.close()
    return tipo, nombre, msg

def cleanup(sig=None, frame=None):
    if RFID_OK:
        GPIO.cleanup()
    sys.exit(0)

def main():
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    print("Lector RFID iniciado")
    print("DB: " + DB)
    if not RFID_OK:
        print("Sin hardware")
        while True:
            time.sleep(60)
    reader = SimpleMFRC522()
    reader.READER.spi.max_speed_hz = 100000
    ultimo_uid = None
    ultimo_t = 0
    print("Listo — acerca una tarjeta...")
    while True:
        try:
            uid, _ = reader.read_no_block()
            if uid is None:
                time.sleep(0.1)
                continue
            uid_s = str(uid).strip()
            ahora = time.time()
            if uid_s == ultimo_uid and (ahora - ultimo_t) < DEBOUNCE:
                time.sleep(0.1)
                continue
            ultimo_uid = uid_s
            ultimo_t = ahora
            tipo, nombre, msg = procesar(uid_s)
            print(tipo + " | " + nombre + " | " + uid_s)
        except Exception as e:
            time.sleep(1)

if __name__ == "__main__":
    main()
