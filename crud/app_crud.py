#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRUD Service — Puerto 5001
Sistema de Asistencia RFID — ITSOEH
"""

import sqlite3, os, csv, io, traceback, logging
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, jsonify, request, Response
from werkzeug.utils import secure_filename

# ── App ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024   # 5 MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB       = os.path.join(BASE_DIR, "..", "shared", "rfid.db")
FOTOS    = os.path.join(BASE_DIR, "static", "fotos")
os.makedirs(FOTOS, exist_ok=True)

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger('crud')

# ── DB ──────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

# ── Schema cache ────────────────────────────────────────────────
_schema_cache: dict = {}

def schema(conn) -> dict:
    """
    Detecta qué columna y formato de fecha usa la tabla.
    Cachea el resultado para no hacer PRAGMA en cada request.
    """
    if _schema_cache:
        return _schema_cache
    cols = {r[1] for r in conn.execute("PRAGMA table_info(registros_asistencia)").fetchall()}
    _schema_cache['col'] = (
        'tipo_evento' if 'tipo_evento' in cols
        else 'estado'   if 'estado'      in cols
        else 'tipo_evento'
    )
    _schema_cache['ff'] = (
        "fecha_dia = ?" if 'fecha_dia' in cols
        else "strftime('%Y-%m-%d', timestamp) = ?"
    )
    return _schema_cache

# ── Decorator: JSON error handler ───────────────────────────────
def api(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except sqlite3.IntegrityError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            log.exception(f"Error en {f.__name__}")
            return jsonify({'success': False, 'error': str(e),
                            'trace': traceback.format_exc()}), 500
    return wrapper

# ═══════════════════════════════════════════════════════════════
#  PÁGINAS
# ═══════════════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template('crud_dashboard.html')

# ═══════════════════════════════════════════════════════════════
#  ESTADÍSTICAS
# ═══════════════════════════════════════════════════════════════
@app.route('/api/estadisticas')
@api
def estadisticas():
    conn = get_db()
    s    = schema(conn)
    hoy  = datetime.now().strftime('%Y-%m-%d')

    def cnt(col_vals: tuple) -> int:
        ph = ','.join('?' * len(col_vals))
        return conn.execute(
            f"SELECT COUNT(*) AS t FROM registros_asistencia "
            f"WHERE {s['ff']} AND {s['col']} IN ({ph})",
            (hoy,) + col_vals
        ).fetchone()['t']

    data = {
        'total_estudiantes':   conn.execute("SELECT COUNT(*) AS t FROM estudiantes").fetchone()['t'],
        'estudiantes_activos': conn.execute("SELECT COUNT(*) AS t FROM estudiantes WHERE estado='activo'").fetchone()['t'],
        'total_tarjetas':      conn.execute("SELECT COUNT(*) AS t FROM tarjetas").fetchone()['t'],
        'tarjetas_activas':    conn.execute("SELECT COUNT(*) AS t FROM tarjetas WHERE activa=1").fetchone()['t'],
        'registros_hoy':       conn.execute(f"SELECT COUNT(*) AS t FROM registros_asistencia WHERE {s['ff']}", (hoy,)).fetchone()['t'],
        'total_registros':     conn.execute("SELECT COUNT(*) AS t FROM registros_asistencia").fetchone()['t'],
        'aceptados_hoy':       cnt(('aceptado', 'entrada')),
    }
    conn.close()
    return jsonify({'success': True, 'stats': data})

# ═══════════════════════════════════════════════════════════════
#  ANALÍTICA
# ═══════════════════════════════════════════════════════════════
@app.route('/api/analytics')
@api
def analytics():
    conn = get_db()
    s    = schema(conn)
    col  = s['col']
    ff   = s['ff']
    hoy  = datetime.now().strftime('%Y-%m-%d')

    # 7 días de asistencia
    dias = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        t = conn.execute(
            f"SELECT COUNT(*) AS t FROM registros_asistencia "
            f"WHERE {ff} AND {col} IN ('aceptado','entrada')",
            (d,)
        ).fetchone()['t']
        dias.append({'fecha': d, 'total': t})

    # Total mes actual
    mes_inicio = datetime.now().strftime('%Y-%m-01')
    mes_total  = conn.execute(
        f"SELECT COUNT(*) AS t FROM registros_asistencia "
        f"WHERE fecha_dia >= ? AND {col} IN ('aceptado','entrada')",
        (mes_inicio,)
    ).fetchone()['t']

    por_carrera = [dict(r) for r in conn.execute("""
        SELECT carrera, COUNT(*) AS alumnos FROM estudiantes
        WHERE estado='activo' GROUP BY carrera ORDER BY alumnos DESC
    """).fetchall()]

    por_semestre = [dict(r) for r in conn.execute("""
        SELECT semestre, COUNT(*) AS alumnos FROM estudiantes
        WHERE estado='activo' GROUP BY semestre ORDER BY CAST(semestre AS INTEGER)
    """).fetchall()]

    por_hora = [dict(r) for r in conn.execute(f"""
        SELECT CAST(strftime('%H', timestamp) AS INTEGER) AS hora, COUNT(*) AS total
        FROM registros_asistencia
        WHERE {ff} AND {col} IN ('aceptado','entrada')
        GROUP BY hora ORDER BY hora
    """, (hoy,)).fetchall()]

    top = [dict(r) for r in conn.execute(f"""
        SELECT e.nombre || ' ' || COALESCE(e.apellido_paterno,'') AS nombre,
               e.matricula, e.carrera, e.semestre,
               COUNT(ra.id) AS visitas
        FROM estudiantes e
        JOIN registros_asistencia ra ON ra.id_estudiante = e.id
        WHERE ra.{col} IN ('aceptado','entrada')
        GROUP BY e.id ORDER BY visitas DESC LIMIT 10
    """).fetchall()]

    conn.close()
    return jsonify({'success': True, 'analytics': {
        'asistencia_7dias': dias,
        'mes_total':        mes_total,
        'por_carrera':      por_carrera,
        'por_semestre':     por_semestre,
        'por_hora':         por_hora,
        'top_estudiantes':  top,
    }})

# ═══════════════════════════════════════════════════════════════
#  ESTUDIANTES
# ═══════════════════════════════════════════════════════════════
@app.route('/api/estudiantes', methods=['GET'])
@api
def get_estudiantes():
    conn = get_db()
    q = """
        SELECT e.*,
               COUNT(DISTINCT t.id)  AS tarjetas_asignadas,
               COUNT(DISTINCT ra.id) AS total_registros
        FROM estudiantes e
        LEFT JOIN tarjetas t ON e.id = t.id_estudiante
        LEFT JOIN registros_asistencia ra ON e.id = ra.id_estudiante
        WHERE 1=1
    """
    p = []
    sem = request.args.get('semestre')
    car = request.args.get('carrera')
    bus = request.args.get('buscar', '').strip()

    if sem: q += " AND e.semestre=?";            p.append(sem)
    if car: q += " AND e.carrera=?";             p.append(car)
    if bus:
        q += " AND (e.nombre LIKE ? OR e.apellido_paterno LIKE ? OR e.matricula LIKE ?)"
        p += [f'%{bus}%'] * 3

    q += " GROUP BY e.id ORDER BY CAST(e.semestre AS INTEGER), e.apellido_paterno, e.nombre"
    rows = [dict(r) for r in conn.execute(q, p).fetchall()]
    conn.close()
    return jsonify({'success': True, 'estudiantes': rows})


@app.route('/api/estudiantes/grupos')
@api
def grupos():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT e.*, COUNT(DISTINCT t.id) AS tarjetas_asignadas
            FROM estudiantes e
            LEFT JOIN tarjetas t ON e.id = t.id_estudiante
            WHERE e.estado = 'activo'
            GROUP BY e.id
            ORDER BY e.carrera, CAST(e.semestre AS INTEGER),
                     COALESCE(e.grupo,''), e.apellido_paterno
        """).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute("""
            SELECT e.*, COUNT(DISTINCT t.id) AS tarjetas_asignadas
            FROM estudiantes e
            LEFT JOIN tarjetas t ON e.id = t.id_estudiante
            WHERE e.estado = 'activo'
            GROUP BY e.id
            ORDER BY e.carrera, CAST(e.semestre AS INTEGER), e.apellido_paterno
        """).fetchall()

    grupos_dict: dict = {}
    for row in rows:
        e   = dict(row)
        key = f"{e.get('carrera','')}-{e.get('semestre','')}-{e.get('grupo','')}"
        if key not in grupos_dict:
            grupos_dict[key] = {
                'carrera':     e.get('carrera', ''),
                'semestre':    str(e.get('semestre', '')),
                'grupo':       e.get('grupo', ''),
                'estudiantes': [],
            }
        grupos_dict[key]['estudiantes'].append(e)

    conn.close()
    return jsonify({'success': True, 'grupos': list(grupos_dict.values())})


@app.route('/api/estudiantes/<int:est_id>', methods=['GET'])
@api
def get_estudiante(est_id):
    conn = get_db()
    row  = conn.execute("SELECT * FROM estudiantes WHERE id=?", (est_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'success': False, 'error': 'No encontrado'}), 404
    return jsonify({'success': True, 'estudiante': dict(row)})


@app.route('/api/estudiantes', methods=['POST'])
@api
def crear_estudiante():
    d    = request.get_json(force=True)
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO estudiantes
                (nombre,apellido_paterno,apellido_materno,matricula,
                 carrera,semestre,grupo,correo,estado,foto)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            d.get('nombre'), d.get('apellido_paterno'), d.get('apellido_materno'),
            d.get('matricula'), d.get('carrera', "ITIC's"), d.get('semestre'),
            d.get('grupo', ''), d.get('correo'), d.get('estado', 'activo'), d.get('foto'),
        ))
    except sqlite3.OperationalError:
        # Sin columna grupo (DB antigua)
        conn.execute("""
            INSERT INTO estudiantes
                (nombre,apellido_paterno,apellido_materno,matricula,
                 carrera,semestre,correo,estado,foto)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            d.get('nombre'), d.get('apellido_paterno'), d.get('apellido_materno'),
            d.get('matricula'), d.get('carrera', "ITIC's"), d.get('semestre'),
            d.get('correo'), d.get('estado', 'activo'), d.get('foto'),
        ))
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
    conn.close()
    return jsonify({'success': True, 'id': new_id, 'mensaje': 'Estudiante creado correctamente'})


@app.route('/api/estudiantes/<int:est_id>', methods=['PUT'])
@api
def actualizar_estudiante(est_id):
    d    = request.get_json(force=True)
    conn = get_db()
    try:
        conn.execute("""
            UPDATE estudiantes SET
                nombre=?,apellido_paterno=?,apellido_materno=?,matricula=?,
                carrera=?,semestre=?,grupo=?,correo=?,estado=?,foto=?
            WHERE id=?
        """, (
            d.get('nombre'), d.get('apellido_paterno'), d.get('apellido_materno'),
            d.get('matricula'), d.get('carrera'), d.get('semestre'),
            d.get('grupo', ''), d.get('correo'), d.get('estado'), d.get('foto'),
            est_id,
        ))
    except sqlite3.OperationalError:
        conn.execute("""
            UPDATE estudiantes SET
                nombre=?,apellido_paterno=?,apellido_materno=?,matricula=?,
                carrera=?,semestre=?,correo=?,estado=?,foto=?
            WHERE id=?
        """, (
            d.get('nombre'), d.get('apellido_paterno'), d.get('apellido_materno'),
            d.get('matricula'), d.get('carrera'), d.get('semestre'),
            d.get('correo'), d.get('estado'), d.get('foto'), est_id,
        ))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'mensaje': 'Estudiante actualizado'})


@app.route('/api/estudiantes/<int:est_id>', methods=['DELETE'])
@api
def eliminar_estudiante(est_id):
    conn = get_db()
    conn.execute("DELETE FROM estudiantes WHERE id=?", (est_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'mensaje': 'Estudiante eliminado'})


@app.route('/api/estudiantes/<int:est_id>/perfil')
@api
def perfil_estudiante(est_id):
    conn = get_db()
    s    = schema(conn)

    est = conn.execute("SELECT * FROM estudiantes WHERE id=?", (est_id,)).fetchone()
    if not est:
        return jsonify({'success': False, 'error': 'No encontrado'}), 404

    tarjetas = [dict(r) for r in conn.execute(
        "SELECT * FROM tarjetas WHERE id_estudiante=?", (est_id,)
    ).fetchall()]

    registros = [dict(r) for r in conn.execute(f"""
        SELECT fecha_dia, {s['col']} AS tipo, timestamp, uid
        FROM registros_asistencia
        WHERE id_estudiante=?
        ORDER BY timestamp DESC LIMIT 90
    """, (est_id,)).fetchall()]

    total_acc = conn.execute(f"""
        SELECT COUNT(*) AS t FROM registros_asistencia
        WHERE id_estudiante=? AND {s['col']} IN ('aceptado','entrada')
    """, (est_id,)).fetchone()['t']

    ultimo = conn.execute(f"""
        SELECT timestamp FROM registros_asistencia
        WHERE id_estudiante=? ORDER BY timestamp DESC LIMIT 1
    """, (est_id,)).fetchone()

    conn.close()
    return jsonify({
        'success':          True,
        'estudiante':       dict(est),
        'tarjetas':         tarjetas,
        'registros':        registros,
        'total_asistencias':total_acc,
        'ultimo_acceso':    dict(ultimo)['timestamp'] if ultimo else None,
    })

# ═══════════════════════════════════════════════════════════════
#  TARJETAS
# ═══════════════════════════════════════════════════════════════
@app.route('/api/tarjetas', methods=['GET'])
@api
def get_tarjetas():
    conn = get_db()
    rows = conn.execute("""
        SELECT t.*,
               e.nombre, e.apellido_paterno, e.matricula,
               e.estado AS est_estado
        FROM tarjetas t
        LEFT JOIN estudiantes e ON t.id_estudiante = e.id
        ORDER BY t.asignada_en DESC
    """).fetchall()

    tarjetas = []
    for r in rows:
        t = dict(r)
        nom = t.get('nombre', '') or ''
        ap  = t.get('apellido_paterno', '') or ''
        t['estudiante_nombre'] = (nom + ' ' + ap).strip() or None
        tarjetas.append(t)

    conn.close()
    return jsonify({'success': True, 'tarjetas': tarjetas})


@app.route('/api/tarjetas', methods=['POST'])
@api
def crear_tarjeta():
    d    = request.get_json(force=True)
    uid  = (d.get('uid') or '').strip()
    if not uid:
        return jsonify({'success': False, 'error': 'UID requerido'}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO tarjetas (uid, id_estudiante, activa) VALUES (?,?,?)",
        (uid, d.get('id_estudiante') or None, int(d.get('activa', 1)))
    )
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
    conn.close()
    return jsonify({'success': True, 'id': new_id, 'mensaje': 'Tarjeta asignada'})


@app.route('/api/tarjetas/<int:tarj_id>', methods=['PUT'])
@api
def actualizar_tarjeta(tarj_id):
    d    = request.get_json(force=True)
    conn = get_db()
    conn.execute(
        "UPDATE tarjetas SET uid=?, id_estudiante=?, activa=? WHERE id=?",
        (d.get('uid'), d.get('id_estudiante') or None, int(d.get('activa', 1)), tarj_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'mensaje': 'Tarjeta actualizada'})


@app.route('/api/tarjetas/<int:tarj_id>', methods=['DELETE'])
@api
def eliminar_tarjeta(tarj_id):
    conn = get_db()
    conn.execute("DELETE FROM tarjetas WHERE id=?", (tarj_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'mensaje': 'Tarjeta eliminada'})


@app.route('/api/tarjetas/bulk-toggle', methods=['POST'])
@api
def bulk_toggle():
    d      = request.get_json(force=True)
    ids    = [int(i) for i in d.get('ids', []) if str(i).isdigit()]
    activa = int(bool(d.get('activa', 1)))
    if not ids:
        return jsonify({'success': False, 'error': 'Sin IDs válidos'}), 400

    conn = get_db()
    conn.execute(
        f"UPDATE tarjetas SET activa=? WHERE id IN ({','.join('?'*len(ids))})",
        [activa] + ids
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'mensaje': f'{len(ids)} tarjeta(s) actualizadas'})

# ═══════════════════════════════════════════════════════════════
#  RFID ADMIN
# ═══════════════════════════════════════════════════════════════
@app.route('/api/rfid/desconocidos')
@api
def rfid_desconocidos():
    conn = get_db()
    s    = schema(conn)
    rows = conn.execute(f"""
        SELECT ra.uid,
               COUNT(*)           AS veces,
               MAX(ra.timestamp)  AS ultimo_scan
        FROM registros_asistencia ra
        WHERE ra.{s['col']} IN ('rebote','desconocido')
          AND NOT EXISTS (SELECT 1 FROM tarjetas t WHERE t.uid = ra.uid)
        GROUP BY ra.uid
        ORDER BY veces DESC
        LIMIT 50
    """).fetchall()
    conn.close()
    return jsonify({'success': True, 'desconocidos': [dict(r) for r in rows]})


@app.route('/api/rfid/historial/<path:uid>')
@api
def rfid_historial(uid):
    conn = get_db()
    s    = schema(conn)
    rows = conn.execute(f"""
        SELECT ra.*,
               ra.{s['col']}   AS tipo_raw,
               COALESCE(e.nombre || ' ' || COALESCE(e.apellido_paterno,''), '') AS nombre,
               e.matricula
        FROM registros_asistencia ra
        LEFT JOIN estudiantes e ON ra.id_estudiante = e.id
        WHERE ra.uid = ?
        ORDER BY ra.timestamp DESC LIMIT 100
    """, (uid,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'historial': [dict(r) for r in rows], 'uid': uid})


@app.route('/api/rfid/ultimo-scan')
@api
def ultimo_scan():
    conn = get_db()
    s    = schema(conn)
    row  = conn.execute(f"""
        SELECT uid, timestamp, {s['col']} AS tipo
        FROM registros_asistencia
        ORDER BY timestamp DESC LIMIT 1
    """).fetchone()
    conn.close()
    return jsonify({'success': True, 'scan': dict(row) if row else None})

# ═══════════════════════════════════════════════════════════════
#  REGISTROS
# ═══════════════════════════════════════════════════════════════
@app.route('/api/registros')
@api
def get_registros():
    conn   = get_db()
    s      = schema(conn)
    limit  = min(request.args.get('limit', 25, type=int), 200)   # hard cap 200
    offset = max(request.args.get('offset', 0, type=int), 0)
    fecha  = request.args.get('fecha')
    tipo   = request.args.get('estado')

    where = "WHERE 1=1"
    p: list = []

    if fecha:
        where += f" AND {s['ff']}"; p.append(fecha)
    if tipo:
        vals   = ('aceptado', 'entrada') if tipo == 'aceptado' else (tipo,)
        ph     = ','.join('?' * len(vals))
        where += f" AND ra.{s['col']} IN ({ph})"; p += list(vals)

    total = conn.execute(
        f"SELECT COUNT(*) AS t FROM registros_asistencia ra {where}", p
    ).fetchone()['t']

    rows = conn.execute(f"""
        SELECT ra.*,
               ra.{s['col']} AS tipo_raw,
               COALESCE(e.nombre || ' ' || COALESCE(e.apellido_paterno,''), 'DESCONOCIDO') AS estudiante_nombre,
               e.matricula, e.foto
        FROM registros_asistencia ra
        LEFT JOIN estudiantes e ON ra.id_estudiante = e.id
        {where}
        ORDER BY ra.timestamp DESC
        LIMIT ? OFFSET ?
    """, p + [limit, offset]).fetchall()

    conn.close()
    return jsonify({
        'success':   True,
        'registros': [dict(r) for r in rows],
        'total':     total,
        'limit':     limit,
        'offset':    offset,
    })

# ═══════════════════════════════════════════════════════════════
#  UPLOAD FOTO
# ═══════════════════════════════════════════════════════════════
EXTS_PERMITIDAS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

@app.route('/api/upload-foto', methods=['POST'])
@api
def upload_foto():
    if 'foto' not in request.files:
        return jsonify({'success': False, 'error': 'No se envió archivo'}), 400
    file = request.files['foto']
    if not file.filename:
        return jsonify({'success': False, 'error': 'Archivo vacío'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in EXTS_PERMITIDAS:
        return jsonify({'success': False, 'error': f'Tipo no permitido: {ext}'}), 400

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{secure_filename(file.filename)}"
    file.save(os.path.join(FOTOS, filename))
    return jsonify({'success': True, 'foto_url': f'/static/fotos/{filename}'})

# ═══════════════════════════════════════════════════════════════
#  EXPORTACIÓN
# ═══════════════════════════════════════════════════════════════
@app.route('/api/export/estudiantes')
def export_estudiantes():
    conn = get_db()
    rows = conn.execute("""
        SELECT id,nombre,apellido_paterno,apellido_materno,matricula,
               carrera,semestre,COALESCE(grupo,'') AS grupo,correo,estado
        FROM estudiantes
        ORDER BY CAST(semestre AS INTEGER), apellido_paterno
    """).fetchall()
    conn.close()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['ID','Nombre','Ap. Paterno','Ap. Materno','Matrícula',
                'Carrera','Semestre','Grupo','Correo','Estado'])
    for r in rows:
        w.writerow([r['id'], r['nombre'], r['apellido_paterno'],
                    r['apellido_materno'], r['matricula'], r['carrera'],
                    r['semestre'], r['grupo'], r['correo'], r['estado']])
    out.seek(0)
    return Response(
        '\ufeff' + out.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=estudiantes.csv'}
    )


@app.route('/api/export/registros')
def export_registros():
    conn  = get_db()
    s     = schema(conn)
    fecha = request.args.get('fecha', datetime.now().strftime('%Y-%m-%d'))
    rows  = conn.execute(f"""
        SELECT ra.id, ra.timestamp, ra.{s['col']} AS tipo, ra.uid,
               COALESCE(ra.mensaje,'') AS mensaje,
               COALESCE(e.nombre || ' ' || COALESCE(e.apellido_paterno,''), 'DESCONOCIDO') AS nombre,
               COALESCE(e.matricula,'')          AS matricula,
               COALESCE(e.carrera,'')            AS carrera,
               COALESCE(CAST(e.semestre AS TEXT),'') AS semestre
        FROM registros_asistencia ra
        LEFT JOIN estudiantes e ON ra.id_estudiante = e.id
        WHERE {s['ff']}
        ORDER BY ra.timestamp
    """, (fecha,)).fetchall()
    conn.close()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['ID','Timestamp','Tipo','UID','Nombre','Matrícula','Carrera','Semestre','Mensaje'])
    for r in rows:
        w.writerow([r['id'], r['timestamp'], r['tipo'], r['uid'],
                    r['nombre'], r['matricula'], r['carrera'], r['semestre'], r['mensaje']])
    out.seek(0)
    return Response(
        '\ufeff' + out.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=registros_{fecha}.csv'}
    )

# ═══════════════════════════════════════════════════════════════
#  MIGRACIÓN
# ═══════════════════════════════════════════════════════════════
@app.route('/api/migrate', methods=['POST'])
def migrate():
    conn    = get_db()
    results = []
    migraciones = [
        "ALTER TABLE estudiantes ADD COLUMN grupo TEXT DEFAULT ''",
        "ALTER TABLE registros_asistencia ADD COLUMN fecha_dia TEXT",
    ]
    for sql in migraciones:
        try:
            conn.execute(sql)
            results.append({'sql': sql, 'ok': True})
        except sqlite3.OperationalError as e:
            results.append({'sql': sql, 'ok': False, 'msg': str(e)})
    conn.commit()
    conn.close()
    _schema_cache.clear()   # invalidar cache tras migrar
    return jsonify({'success': True, 'results': results})

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
