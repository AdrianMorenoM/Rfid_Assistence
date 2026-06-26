#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RFID Dashboard Service - Puerto 5000"""

from flask import Flask, render_template, jsonify
import sqlite3, os, traceback
from datetime import datetime

app     = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB       = os.path.join(BASE_DIR, "..", "shared", "rfid.db")

def get_db():
    conn = sqlite3.connect(DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

# Detectar esquema una sola vez
_schema = {}
def schema(conn):
    if _schema: return _schema
    cols = {r[1] for r in conn.execute("PRAGMA table_info(registros_asistencia)").fetchall()}
    _schema['col'] = 'tipo_evento' if 'tipo_evento' in cols else 'estado' if 'estado' in cols else 'tipo_evento'
    _schema['ff']  = "fecha_dia = ?" if 'fecha_dia' in cols else "strftime('%Y-%m-%d',timestamp) = ?"
    return _schema

def norm(v):
    if not v: return 'rebote'
    v = v.lower()
    if v in ('aceptado','entrada'): return 'aceptado'
    if v == 'ya_escaneado':         return 'ya_escaneado'
    return 'rebote'

@app.route('/') 
@app.route('/dashboard')
def index(): return render_template('dashboard.html')

@app.route('/api/estado')
def api_estado():
    try:
        conn = get_db()
        s    = schema(conn)
        col  = s['col']
        ff   = s['ff']
        hoy  = datetime.now().strftime('%Y-%m-%d')

        def cnt(*vals):
            ph = ','.join('?'*len(vals))
            return conn.execute(
                f"SELECT COUNT(*) as t FROM registros_asistencia WHERE {ff} AND {col} IN ({ph})",
                (hoy,)+vals).fetchone()['t']

        stats = {
            'entradas_hoy':     cnt('aceptado','entrada'),
            'ya_escaneados':    cnt('ya_escaneado'),
            'rebotes_hoy':      cnt('rebote','desconocido'),
            'tarjetas_activas': conn.execute("SELECT COUNT(*) as t FROM tarjetas WHERE activa=1").fetchone()['t'],
        }

        reps = conn.execute(f"""
            SELECT ra.uid, COUNT(*) as veces,
                   COALESCE(e.nombre||' '||COALESCE(e.apellido_paterno,''),'') as nombre
            FROM registros_asistencia ra
            LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            WHERE {ff} AND ra.{col} IN ('aceptado','entrada')
            GROUP BY ra.uid HAVING COUNT(*)>1 ORDER BY veces DESC LIMIT 10
        """, (hoy,)).fetchall()

        # ← MEJORA: orden determinista añadiendo ra.id DESC
        evs = conn.execute(f"""
            SELECT ra.id, ra.uid, ra.timestamp, ra.{col} as tr,
                   COALESCE(ra.mensaje,'') as mensaje,
                   e.nombre, e.apellido_paterno, e.matricula, e.carrera, e.foto
            FROM registros_asistencia ra
            LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            WHERE {ff}
            ORDER BY ra.timestamp DESC, ra.id DESC
            LIMIT 30
        """, (hoy,)).fetchall()

        eventos = []
        for r in evs:
            r = dict(r)
            nombre = f"{r.get('nombre','')} {r.get('apellido_paterno','') or ''}".strip() or 'DESCONOCIDO'
            eventos.append({'id':r['id'],'uid':r['uid'],'timestamp':r['timestamp'],
                'estado':norm(r['tr']),'mensaje':r['mensaje'],'nombre':nombre,
                'matricula':r.get('matricula') or 'N/A','carrera':r.get('carrera') or 'N/A','foto':r.get('foto')})

        # Hourly accesses today (for chart)
        horas_raw = conn.execute(f"""
            SELECT CAST(strftime('%H', timestamp) AS INTEGER) as h, COUNT(*) as cnt
            FROM registros_asistencia
            WHERE {ff} AND {col} IN ('aceptado','entrada')
            GROUP BY h
        """, (hoy,)).fetchall()
        horas_map = {r['h']: r['cnt'] for r in horas_raw}
        hourly = [horas_map.get(h, 0) for h in range(24)]

        # Reader service status
        try:
            import subprocess
            res = subprocess.run(['systemctl','is-active','rfid-reader'],
                                 capture_output=True, text=True, timeout=2)
            reader_ok = res.stdout.strip() == 'active'
        except Exception:
            reader_ok = False

        conn.close()
        return jsonify({
            'success':True,'stats':stats,
            'uid_repetidos':[dict(r) for r in reps],
            'eventos':eventos,
            'hourly': hourly,
            'reader_ok': reader_ok,
        })
    except Exception as e:
        return jsonify({'success':False,'error':str(e),'trace':traceback.format_exc()}), 500

@app.route('/api/ultimo-evento')
def ultimo_evento():
    try:
        conn = get_db()
        s    = schema(conn)
        hoy  = datetime.now().strftime('%Y-%m-%d')
        row  = conn.execute(f"""
            SELECT ra.id,ra.uid,ra.timestamp,ra.{s['col']} as tr,
                   COALESCE(ra.mensaje,'') as mensaje,
                   e.nombre,e.apellido_paterno,e.matricula,e.carrera,e.foto
            FROM registros_asistencia ra
            LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            WHERE {s['ff']} ORDER BY ra.timestamp DESC LIMIT 1
        """, (hoy,)).fetchone()
        conn.close()
        if not row: return jsonify({'success':True,'evento':None})
        r = dict(row)
        nombre = f"{r.get('nombre','')} {r.get('apellido_paterno','') or ''}".strip() or 'DESCONOCIDO'
        return jsonify({'success':True,'evento':{'id':r['id'],'uid':r['uid'],'timestamp':r['timestamp'],
            'estado':norm(r['tr']),'mensaje':r['mensaje'],'nombre':nombre,
            'matricula':r.get('matricula') or 'N/A','carrera':r.get('carrera') or 'N/A','foto':r.get('foto')}})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
