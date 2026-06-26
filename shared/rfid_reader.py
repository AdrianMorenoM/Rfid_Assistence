#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lector RFID — ITSOEH  (reader_service/reader.py)
Hardware: Raspberry Pi 4 + RC522 vía SPI
"""

import sqlite3, os, time, signal, sys, logging
from datetime import datetime

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reader.log')),
    ]
)
log = logging.getLogger('rfid-reader')

# ── Hardware ────────────────────────────────────────────────────
try:
    from mfrc522 import SimpleMFRC522
    import RPi.GPIO as GPIO
    RFID_OK = True
    log.info("Hardware RC522 detectado")
except ImportError:
    RFID_OK = False
    log.warning("mfrc522 / RPi.GPIO no disponibles — modo simulación")

# ── Config ──────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB         = os.path.join(BASE_DIR, "..", "shared", "rfid.db")
DEBOUNCE_S = 2          # segundos mínimos entre escaneos del mismo UID
SPI_SPEED  = 100_000    # Hz — velocidad estable para RC522
POLL_MS    = 0.08       # pausa entre lecturas (80 ms → ~12 fps)

# ── DB helper ───────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

# ── Lógica de acceso ────────────────────────────────────────────
def procesar(uid_s: str) -> tuple[str, str, str]:
    """
    Evalúa el UID y registra el evento en la DB.
    Retorna (tipo_evento, nombre_display, mensaje).
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    try:
        c = conn.cursor()

        # 1. ¿La tarjeta existe?
        c.execute("""
            SELECT t.activa, t.id_estudiante,
                   e.nombre, e.apellido_paterno, e.estado
            FROM tarjetas t
            LEFT JOIN estudiantes e ON t.id_estudiante = e.id
            WHERE t.uid = ?
        """, (uid_s,))
        tarjeta = c.fetchone()

        if tarjeta is None:
            c.execute("""
                INSERT INTO registros_asistencia
                    (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje)
                VALUES (NULL, ?, ?, ?, 'rebote', 'UID no registrado')
            """, (uid_s, ts, hoy))
            conn.commit()
            return "rebote", "DESCONOCIDO", "UID no registrado"

        nombre = (
            (tarjeta["nombre"] or "") + " " + (tarjeta["apellido_paterno"] or "")
        ).strip() or "Sin nombre"

        # 2. ¿Tarjeta o estudiante inactivo?
        if not tarjeta["activa"] or tarjeta["estado"] != "activo":
            motivo = "Tarjeta inactiva" if not tarjeta["activa"] else "Estudiante inactivo"
            c.execute("""
                INSERT INTO registros_asistencia
                    (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje)
                VALUES (?, ?, ?, ?, 'rebote', ?)
            """, (tarjeta["id_estudiante"], uid_s, ts, hoy, motivo))
            conn.commit()
            return "rebote", nombre, motivo

        # 3. ¿Ya registrado hoy?
        c.execute("""
            SELECT COUNT(*) as n FROM registros_asistencia
            WHERE uid = ? AND fecha_dia = ? AND tipo_evento = 'aceptado'
        """, (uid_s, hoy))
        veces = c.fetchone()["n"]

        tipo = "ya_escaneado" if veces > 0 else "aceptado"
        if veces > 0:
            msg = f"Ya registrado ({veces + 1}ª vez hoy)"
        else:
            msg = "Acceso permitido"

        c.execute("""
            INSERT INTO registros_asistencia
                (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tarjeta["id_estudiante"], uid_s, ts, hoy, tipo, msg))
        conn.commit()
        return tipo, nombre, msg

    finally:
        conn.close()

# ── Signal handler ──────────────────────────────────────────────
def cleanup(sig=None, _frame=None):
    log.info("Cerrando lector RFID…")
    if RFID_OK:
        try:
            GPIO.cleanup()
        except Exception:
            pass
    sys.exit(0)

# ── Main loop ───────────────────────────────────────────────────
def main():
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT,  cleanup)

    log.info("═══ Lector RFID iniciado ═══")
    log.info(f"DB: {DB}")

    if not RFID_OK:
        log.warning("Sin hardware RFID — proceso en espera (simulación). DB disponible.")
        while True:
            time.sleep(60)

    reader = SimpleMFRC522()
    reader.READER.spi.max_speed_hz = SPI_SPEED

    ultimo_uid = None
    ultimo_t   = 0.0

    log.info("Listo — acerca una tarjeta…")

    while True:
        try:
            uid, _ = reader.read_no_block()

            if uid is None:
                time.sleep(POLL_MS)
                continue

            uid_s = str(uid).strip()
            ahora = time.time()

            # Debounce: ignorar el mismo UID dentro de la ventana
            if uid_s == ultimo_uid and (ahora - ultimo_t) < DEBOUNCE_S:
                time.sleep(POLL_MS)
                continue

            ultimo_uid = uid_s
            ultimo_t   = ahora

            tipo, nombre, msg = procesar(uid_s)

            # Feedback visual en terminal
            colores = {
                "aceptado":     "\033[92m",   # verde
                "ya_escaneado": "\033[93m",   # amarillo
                "rebote":       "\033[91m",   # rojo
            }
            reset = "\033[0m"
            c = colores.get(tipo, "")
            log.info(f"{c}[{tipo.upper():13s}]{reset}  {nombre:<30s}  UID: {uid_s}")

        except Exception as exc:
            log.error(f"Error en loop: {exc}", exc_info=True)
            time.sleep(1)

if __name__ == "__main__":
    main()
