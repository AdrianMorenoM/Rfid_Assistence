#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RFID CRUD Service - Puerto 5001"""

from flask import Flask, render_template, jsonify, request
import sqlite3, os, traceback
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

app      = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB       = os.path.join(BASE_DIR, "..", "shared", "rfid.db")
FOTOS    = os.path.join(BASE_DIR, "static", "fotos")
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
os.makedirs(FOTOS, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

_schema = {}
def schema(conn):
    if _schema: return _schema
    cols = {r[1] for r in conn.execute("PRAGMA table_info(registros_asistencia)").fetchall()}
    _schema['col'] = 'tipo_evento' if 'tipo_evento' in cols else 'estado' if 'estado' in cols else 'tipo_evento'
    _schema['ff']  = "fecha_dia = ?" if 'fecha_dia' in cols else "strftime('%Y-%m-%d',timestamp) = ?"
    return _schema

# ── PÁGINAS ──────────────────────────────────────────────────────
@app.route('/')
def index(): return render_template('crud_dashboard.html')

# ── ESTADÍSTICAS ─────────────────────────────────────────────────
@app.route('/api/estadisticas')
def estadisticas():
    try:
        conn = get_db()
        s    = schema(conn)
        hoy  = datetime.now().strftime('%Y-%m-%d')

        def cnt_reg(*vals):
            ph = ','.join('?'*len(vals))
            return conn.execute(
                f"SELECT COUNT(*) as t FROM registros_asistencia WHERE {s['ff']} AND {s['col']} IN ({ph})",
                (hoy,)+vals).fetchone()['t']

        data = {
            'total_estudiantes':  conn.execute("SELECT COUNT(*) as t FROM estudiantes").fetchone()['t'],
            'estudiantes_activos':conn.execute("SELECT COUNT(*) as t FROM estudiantes WHERE estado='activo'").fetchone()['t'],
            'total_tarjetas':     conn.execute("SELECT COUNT(*) as t FROM tarjetas").fetchone()['t'],
            'tarjetas_activas':   conn.execute("SELECT COUNT(*) as t FROM tarjetas WHERE activa=1").fetchone()['t'],
            'registros_hoy':      conn.execute(f"SELECT COUNT(*) as t FROM registros_asistencia WHERE {s['ff']}", (hoy,)).fetchone()['t'],
            'total_registros':    conn.execute("SELECT COUNT(*) as t FROM registros_asistencia").fetchone()['t'],
            'aceptados_hoy':      cnt_reg('aceptado','entrada'),
        }
        conn.close()
        return jsonify({'success':True,'stats':data})
    except Exception as e:
        return jsonify({'success':False,'error':str(e),'trace':traceback.format_exc()}), 500

# ── ANALÍTICA ────────────────────────────────────────────────────
@app.route('/api/analytics')
def analytics():
    try:
        conn = get_db()
        s    = schema(conn)
        col  = s['col']
        ff   = s['ff']
        hoy  = datetime.now().strftime('%Y-%m-%d')

        # 7 días
        dias = []
        for i in range(6,-1,-1):
            d = (datetime.now()-timedelta(days=i)).strftime('%Y-%m-%d')
            t = conn.execute(
                f"SELECT COUNT(*) as t FROM registros_asistencia WHERE {ff} AND {col} IN ('aceptado','entrada')",
                (d,)).fetchone()['t']
            dias.append({'fecha':d,'total':t})

        por_carrera = [dict(r) for r in conn.execute("""
            SELECT carrera, COUNT(*) as alumnos FROM estudiantes
            WHERE estado='activo' GROUP BY carrera ORDER BY alumnos DESC
        """).fetchall()]

        por_semestre = [dict(r) for r in conn.execute("""
            SELECT semestre, COUNT(*) as alumnos FROM estudiantes
            WHERE estado='activo' GROUP BY semestre ORDER BY CAST(semestre AS INTEGER)
        """).fetchall()]

        por_hora = [dict(r) for r in conn.execute(f"""
            SELECT CAST(strftime('%H',timestamp) AS INTEGER) as hora, COUNT(*) as total
            FROM registros_asistencia WHERE {ff} AND {col} IN ('aceptado','entrada')
            GROUP BY hora ORDER BY hora
        """, (hoy,)).fetchall()]

        top = [dict(r) for r in conn.execute(f"""
            SELECT e.nombre||' '||COALESCE(e.apellido_paterno,'') as nombre,
                   e.matricula, e.carrera, e.semestre, COUNT(ra.id) as visitas
            FROM estudiantes e JOIN registros_asistencia ra ON ra.id_estudiante=e.id
            WHERE ra.{col} IN ('aceptado','entrada')
            GROUP BY e.id ORDER BY visitas DESC LIMIT 10
        """).fetchall()]

        conn.close()
        return jsonify({'success':True,'analytics':{
            'asistencia_7dias':dias,'por_carrera':por_carrera,
            'por_semestre':por_semestre,'por_hora':por_hora,'top_estudiantes':top}})
    except Exception as e:
        return jsonify({'success':False,'error':str(e),'trace':traceback.format_exc()}), 500

# ── ESTUDIANTES ──────────────────────────────────────────────────
@app.route('/api/estudiantes', methods=['GET'])
def get_estudiantes():
    try:
        conn = get_db()
        q    = """SELECT e.*, COUNT(DISTINCT t.id) as tarjetas_asignadas,
                         COUNT(DISTINCT ra.id) as total_registros
                  FROM estudiantes e
                  LEFT JOIN tarjetas t ON e.id=t.id_estudiante
                  LEFT JOIN registros_asistencia ra ON e.id=ra.id_estudiante
                  WHERE 1=1"""
        p = []
        sem = request.args.get('semestre')
        car = request.args.get('carrera')
        bus = request.args.get('buscar','').strip()
        if sem: q += " AND e.semestre=?";          p.append(sem)
        if car: q += " AND e.carrera=?";           p.append(car)
        if bus:
            q += " AND (e.nombre LIKE ? OR e.apellido_paterno LIKE ? OR e.matricula LIKE ?)"
            p += [f'%{bus}%']*3
        q += " GROUP BY e.id ORDER BY CAST(e.semestre AS INTEGER), e.apellido_paterno, e.nombre"
        rows = [dict(r) for r in conn.execute(q,p).fetchall()]
        conn.close()
        return jsonify({'success':True,'estudiantes':rows})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/estudiantes/grupos')
def grupos():
    try:
        conn = get_db()
        try:
            rows = conn.execute("""
                SELECT e.*, COUNT(DISTINCT t.id) as tarjetas_asignadas
                FROM estudiantes e LEFT JOIN tarjetas t ON e.id=t.id_estudiante
                WHERE e.estado='activo'
                GROUP BY e.id ORDER BY e.carrera, CAST(e.semestre AS INTEGER), COALESCE(e.grupo,''), e.apellido_paterno
            """).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute("""
                SELECT e.*, COUNT(DISTINCT t.id) as tarjetas_asignadas
                FROM estudiantes e LEFT JOIN tarjetas t ON e.id=t.id_estudiante
                WHERE e.estado='activo'
                GROUP BY e.id ORDER BY e.carrera, CAST(e.semestre AS INTEGER), e.apellido_paterno
            """).fetchall()

        grupos = {}
        for e in rows:
            e = dict(e)
            key = f"{e.get('carrera','')}-{e.get('semestre','')}-{e.get('grupo','')}"
            if key not in grupos:
                grupos[key] = {'carrera':e.get('carrera',''),'semestre':str(e.get('semestre','')),'grupo':e.get('grupo',''),'estudiantes':[]}
            grupos[key]['estudiantes'].append(e)

        conn.close()
        return jsonify({'success':True,'grupos':list(grupos.values())})
    except Exception as e:
        return jsonify({'success':False,'error':str(e),'trace':traceback.format_exc()}), 500

@app.route('/api/estudiantes/<int:id>', methods=['GET'])
def get_estudiante(id):
    try:
        conn = get_db()
        row  = conn.execute("SELECT * FROM estudiantes WHERE id=?", (id,)).fetchone()
        conn.close()
        if not row: return jsonify({'success':False,'error':'No encontrado'}), 404
        return jsonify({'success':True,'estudiante':dict(row)})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/estudiantes', methods=['POST'])
def crear_estudiante():
    try:
        d    = request.get_json()
        conn = get_db()
        try:
            conn.execute("""INSERT INTO estudiantes
                (nombre,apellido_paterno,apellido_materno,matricula,carrera,semestre,grupo,correo,estado,foto)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (d.get('nombre'),d.get('apellido_paterno'),d.get('apellido_materno'),
                 d.get('matricula'),d.get('carrera',"ITIC's"),d.get('semestre'),
                 d.get('grupo',''),d.get('correo'),d.get('estado','activo'),d.get('foto')))
        except sqlite3.OperationalError:
            conn.execute("""INSERT INTO estudiantes
                (nombre,apellido_paterno,apellido_materno,matricula,carrera,semestre,correo,estado,foto)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (d.get('nombre'),d.get('apellido_paterno'),d.get('apellido_materno'),
                 d.get('matricula'),d.get('carrera',"ITIC's"),d.get('semestre'),
                 d.get('correo'),d.get('estado','activo'),d.get('foto')))
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
        conn.close()
        return jsonify({'success':True,'id':new_id,'mensaje':'Estudiante creado'})
    except sqlite3.IntegrityError:
        return jsonify({'success':False,'error':'La matrícula ya existe'}), 400
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/estudiantes/<int:id>', methods=['PUT'])
def actualizar_estudiante(id):
    try:
        d    = request.get_json()
        conn = get_db()
        try:
            conn.execute("""UPDATE estudiantes SET
                nombre=?,apellido_paterno=?,apellido_materno=?,matricula=?,
                carrera=?,semestre=?,grupo=?,correo=?,estado=?,foto=? WHERE id=?""",
                (d.get('nombre'),d.get('apellido_paterno'),d.get('apellido_materno'),
                 d.get('matricula'),d.get('carrera'),d.get('semestre'),d.get('grupo',''),
                 d.get('correo'),d.get('estado'),d.get('foto'),id))
        except sqlite3.OperationalError:
            conn.execute("""UPDATE estudiantes SET
                nombre=?,apellido_paterno=?,apellido_materno=?,matricula=?,
                carrera=?,semestre=?,correo=?,estado=?,foto=? WHERE id=?""",
                (d.get('nombre'),d.get('apellido_paterno'),d.get('apellido_materno'),
                 d.get('matricula'),d.get('carrera'),d.get('semestre'),
                 d.get('correo'),d.get('estado'),d.get('foto'),id))
        conn.commit(); conn.close()
        return jsonify({'success':True,'mensaje':'Estudiante actualizado'})
    except sqlite3.IntegrityError:
        return jsonify({'success':False,'error':'La matrícula ya existe'}), 400
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/estudiantes/<int:id>', methods=['DELETE'])
def eliminar_estudiante(id):
    try:
        conn = get_db()
        conn.execute("DELETE FROM estudiantes WHERE id=?", (id,))
        conn.commit(); conn.close()
        return jsonify({'success':True,'mensaje':'Estudiante eliminado'})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

# ── TARJETAS ─────────────────────────────────────────────────────
@app.route('/api/tarjetas', methods=['GET'])
def get_tarjetas():
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT t.*,
                   e.nombre, e.apellido_paterno, e.matricula, e.estado as est_estado
            FROM tarjetas t LEFT JOIN estudiantes e ON t.id_estudiante=e.id
            ORDER BY t.asignada_en DESC
        """).fetchall()
        tarjetas = []
        for r in rows:
            t = dict(r)
            t['estudiante_nombre'] = f"{t.get('nombre','')} {t.get('apellido_paterno','') or ''}".strip() or None
            tarjetas.append(t)
        conn.close()
        return jsonify({'success':True,'tarjetas':tarjetas})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/tarjetas', methods=['POST'])
def crear_tarjeta():
    try:
        d    = request.get_json()
        conn = get_db()
        conn.execute("INSERT INTO tarjetas (uid,id_estudiante,activa) VALUES (?,?,?)",
            (d.get('uid'), d.get('id_estudiante') or None, d.get('activa',1)))
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
        conn.close()
        return jsonify({'success':True,'id':new_id,'mensaje':'Tarjeta asignada'})
    except sqlite3.IntegrityError:
        return jsonify({'success':False,'error':'UID ya existe'}), 400
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/tarjetas/<int:id>', methods=['PUT'])
def actualizar_tarjeta(id):
    try:
        d    = request.get_json()
        conn = get_db()
        conn.execute("UPDATE tarjetas SET uid=?,id_estudiante=?,activa=? WHERE id=?",
            (d.get('uid'), d.get('id_estudiante') or None, d.get('activa'), id))
        conn.commit(); conn.close()
        return jsonify({'success':True,'mensaje':'Tarjeta actualizada'})
    except sqlite3.IntegrityError:
        return jsonify({'success':False,'error':'UID ya existe'}), 400
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/tarjetas/<int:id>', methods=['DELETE'])
def eliminar_tarjeta(id):
    try:
        conn = get_db()
        conn.execute("DELETE FROM tarjetas WHERE id=?", (id,))
        conn.commit(); conn.close()
        return jsonify({'success':True,'mensaje':'Tarjeta eliminada'})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/tarjetas/bulk-toggle', methods=['POST'])
def bulk_toggle():
    try:
        d      = request.get_json()
        ids    = d.get('ids',[])
        activa = d.get('activa',1)
        if not ids: return jsonify({'success':False,'error':'Sin IDs'}), 400
        conn = get_db()
        conn.execute(f"UPDATE tarjetas SET activa=? WHERE id IN ({','.join('?'*len(ids))})", [activa]+ids)
        conn.commit(); conn.close()
        return jsonify({'success':True,'mensaje':f'{len(ids)} tarjeta(s) actualizadas'})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

# ── RFID ADMIN ───────────────────────────────────────────────────
@app.route('/api/rfid/desconocidos')
def rfid_desconocidos():
    try:
        conn = get_db()
        s    = schema(conn)
        rows = conn.execute(f"""
            SELECT ra.uid, COUNT(*) as veces, MAX(ra.timestamp) as ultimo_scan
            FROM registros_asistencia ra
            WHERE ra.{s['col']} IN ('rebote','desconocido')
              AND NOT EXISTS (SELECT 1 FROM tarjetas t WHERE t.uid=ra.uid)
            GROUP BY ra.uid ORDER BY veces DESC LIMIT 50
        """).fetchall()
        conn.close()
        return jsonify({'success':True,'desconocidos':[dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/rfid/historial/<uid>')
def rfid_historial(uid):
    try:
        conn = get_db()
        s    = schema(conn)
        rows = conn.execute(f"""
            SELECT ra.*, ra.{s['col']} as tipo_raw,
                   COALESCE(e.nombre||' '||COALESCE(e.apellido_paterno,''),'') as nombre,
                   e.matricula
            FROM registros_asistencia ra
            LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
            WHERE ra.uid=? ORDER BY ra.timestamp DESC LIMIT 100
        """, (uid,)).fetchall()
        conn.close()
        return jsonify({'success':True,'historial':[dict(r) for r in rows],'uid':uid})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/rfid/ultimo-scan')
def ultimo_scan():
    try:
        conn = get_db()
        s    = schema(conn)
        row  = conn.execute(f"""
            SELECT uid, timestamp, {s['col']} as tipo
            FROM registros_asistencia ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
        conn.close()
        return jsonify({'success':True,'scan':dict(row) if row else None})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

# ── REGISTROS ────────────────────────────────────────────────────
@app.route('/api/registros')
def get_registros():
    try:
        conn   = get_db()
        s      = schema(conn)
        limit  = request.args.get('limit', 25, type=int)
        offset = request.args.get('offset', 0, type=int)
        fecha  = request.args.get('fecha')
        tipo   = request.args.get('estado')

        where = "WHERE 1=1"
        p     = []
        if fecha:
            where += f" AND {s['ff']}"; p.append(fecha)
        if tipo:
            vals  = ('aceptado','entrada') if tipo == 'aceptado' else (tipo,)
            where += f" AND ra.{s['col']} IN ({','.join('?'*len(vals))})"; p += list(vals)

        total = conn.execute(
            f"SELECT COUNT(*) as t FROM registros_asistencia ra {where}", p
        ).fetchone()['t']

        q = f"""SELECT ra.*, ra.{s['col']} as tipo_raw,
                       COALESCE(e.nombre||' '||COALESCE(e.apellido_paterno,''),'DESCONOCIDO') as estudiante_nombre,
                       e.matricula, e.foto
                FROM registros_asistencia ra
                LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
                {where}
                ORDER BY ra.timestamp DESC LIMIT ? OFFSET ?"""
        rows = [dict(r) for r in conn.execute(q, p+[limit, offset]).fetchall()]
        conn.close()
        return jsonify({'success':True,'registros':rows,'total':total,'limit':limit,'offset':offset})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/api/estudiantes/<int:id>/perfil')
def perfil_estudiante(id):
    """Perfil completo con historial de asistencia"""
    try:
        conn = get_db()
        s    = schema(conn)

        est = conn.execute("SELECT * FROM estudiantes WHERE id=?", (id,)).fetchone()
        if not est:
            return jsonify({'success':False,'error':'No encontrado'}), 404

        tarjetas = [dict(r) for r in conn.execute(
            "SELECT * FROM tarjetas WHERE id_estudiante=?", (id,)
        ).fetchall()]

        registros = [dict(r) for r in conn.execute(f"""
            SELECT fecha_dia, {s['col']} as tipo, timestamp, uid
            FROM registros_asistencia
            WHERE id_estudiante=?
            ORDER BY timestamp DESC LIMIT 90
        """, (id,)).fetchall()]

        total_acc = conn.execute(f"""
            SELECT COUNT(*) as t FROM registros_asistencia
            WHERE id_estudiante=? AND {s['col']} IN ('aceptado','entrada')
        """, (id,)).fetchone()['t']

        ultimo = conn.execute(f"""
            SELECT timestamp FROM registros_asistencia
            WHERE id_estudiante=? ORDER BY timestamp DESC LIMIT 1
        """, (id,)).fetchone()

        conn.close()
        return jsonify({
            'success': True,
            'estudiante': dict(est),
            'tarjetas': tarjetas,
            'registros': registros,
            'total_asistencias': total_acc,
            'ultimo_acceso': dict(ultimo)['timestamp'] if ultimo else None,
        })
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

# ── MIGRACIÓN ────────────────────────────────────────────────────
# ── UPLOAD FOTO ──────────────────────────────────────────────────
@app.route('/api/upload-foto', methods=['POST'])
def upload_foto():
    try:
        if 'foto' not in request.files:
            return jsonify({'success':False,'error':'No se envió archivo'}), 400
        file = request.files['foto']
        if not file.filename:
            return jsonify({'success':False,'error':'Archivo vacío'}), 400
        ext = file.filename.rsplit('.',1)[-1].lower()
        if ext not in {'png','jpg','jpeg','gif','webp'}:
            return jsonify({'success':False,'error':'Tipo no permitido'}), 400
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        file.save(os.path.join(FOTOS, filename))
        return jsonify({'success':True,'foto_url':f'/static/fotos/{filename}'})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

# ── EXPORTACIÓN ──────────────────────────────────────────────────
@app.route('/api/export/estudiantes')
def export_estudiantes():
    import csv, io
    conn = get_db()
    rows = conn.execute("""
        SELECT id,nombre,apellido_paterno,apellido_materno,matricula,
               carrera,semestre,COALESCE(grupo,'') as grupo,correo,estado
        FROM estudiantes ORDER BY CAST(semestre AS INTEGER),apellido_paterno
    """).fetchall()
    conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['ID','Nombre','Ap. Paterno','Ap. Materno','Matrícula','Carrera','Semestre','Grupo','Correo','Estado'])
    for r in rows:
        w.writerow([r['id'],r['nombre'],r['apellido_paterno'],r['apellido_materno'],
                    r['matricula'],r['carrera'],r['semestre'],r['grupo'],r['correo'],r['estado']])
    out.seek(0)
    from flask import Response
    return Response('\ufeff'+out.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition':'attachment; filename=estudiantes.csv'})

@app.route('/api/export/registros')
def export_registros():
    import csv, io
    conn  = get_db()
    s     = schema(conn)
    fecha = request.args.get('fecha', datetime.now().strftime('%Y-%m-%d'))
    rows  = conn.execute(f"""
        SELECT ra.id, ra.timestamp, ra.{s['col']} as tipo, ra.uid,
               COALESCE(ra.mensaje,'') as mensaje,
               COALESCE(e.nombre||' '||COALESCE(e.apellido_paterno,''),'DESCONOCIDO') as nombre,
               COALESCE(e.matricula,'') as matricula,
               COALESCE(e.carrera,'') as carrera,
               COALESCE(CAST(e.semestre AS TEXT),'') as semestre
        FROM registros_asistencia ra
        LEFT JOIN estudiantes e ON ra.id_estudiante=e.id
        WHERE {s['ff']} ORDER BY ra.timestamp
    """, (fecha,)).fetchall()
    conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['ID','Timestamp','Tipo','UID','Nombre','Matrícula','Carrera','Semestre','Mensaje'])
    for r in rows:
        w.writerow([r['id'],r['timestamp'],r['tipo'],r['uid'],r['nombre'],
                    r['matricula'],r['carrera'],r['semestre'],r['mensaje']])
    out.seek(0)
    from flask import Response
    return Response('\ufeff'+out.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition':f'attachment; filename=registros_{fecha}.csv'})

@app.route('/api/migrate', methods=['POST'])
def migrate():
    conn = get_db()
    results = []
    for sql in ["ALTER TABLE estudiantes ADD COLUMN grupo TEXT DEFAULT ''"]:
        try:
            conn.execute(sql); results.append({'sql':sql,'ok':True})
        except sqlite3.OperationalError as e:
            results.append({'sql':sql,'ok':False,'msg':str(e)})
    conn.commit(); conn.close()
    _schema.clear()  # reset cache
    return jsonify({'success':True,'results':results})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
