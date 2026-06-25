#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inicializa la base de datos del sistema RFID
Ejecutar una sola vez: python3 init_db.py
"""

import sqlite3
import os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rfid.db")

def init():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS estudiantes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre           TEXT NOT NULL,
            apellido_paterno TEXT NOT NULL,
            apellido_materno TEXT,
            matricula        TEXT UNIQUE NOT NULL,
            carrera          TEXT DEFAULT 'ITIC''s',
            semestre         INTEGER,
            grupo            TEXT DEFAULT '',
            correo           TEXT,
            estado           TEXT DEFAULT 'activo',
            foto             TEXT,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tarjetas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            uid           TEXT UNIQUE NOT NULL,
            id_estudiante INTEGER REFERENCES estudiantes(id) ON DELETE SET NULL,
            activa        INTEGER DEFAULT 1,
            asignada_en   DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS registros_asistencia (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            id_estudiante INTEGER REFERENCES estudiantes(id) ON DELETE SET NULL,
            uid           TEXT NOT NULL,
            timestamp     DATETIME DEFAULT CURRENT_TIMESTAMP,
            fecha_dia     TEXT NOT NULL,
            tipo_evento   TEXT NOT NULL,
            mensaje       TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_reg_fecha    ON registros_asistencia(fecha_dia);
        CREATE INDEX IF NOT EXISTS idx_reg_uid      ON registros_asistencia(uid);
        CREATE INDEX IF NOT EXISTS idx_reg_evento   ON registros_asistencia(tipo_evento);
        CREATE INDEX IF NOT EXISTS idx_tarj_uid     ON tarjetas(uid);
    """)

    conn.commit()
    conn.close()
    print(f"✅ Base de datos lista: {DB}")

if __name__ == "__main__":
    init()
