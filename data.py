#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de configuración única para eliminar "database is locked"
Ejecutar una sola vez: python3 fix_database_locked.py
"""

import sqlite3
import os

# Ruta a la base de datos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "shared", "rfid.db")

def fix_database_locked():
    """Configura la BD en modo WAL para eliminar locks"""
    
    print("=" * 70)
    print("🔧 CONFIGURACIÓN ANTI-LOCK PARA BASE DE DATOS")
    print("=" * 70)
    
    if not os.path.exists(DB):
        print(f"❌ Error: No se encontró la base de datos en {DB}")
        return False
    
    try:
        print(f"\n📂 Base de datos encontrada: {DB}")
        print(f"📊 Tamaño actual: {os.path.getsize(DB) / 1024:.2f} KB")
        
        # Conectar a la base de datos
        conn = sqlite3.connect(DB, timeout=60.0)
        cursor = conn.cursor()
        
        print("\n🔍 Verificando modo actual...")
        current_mode = cursor.execute('PRAGMA journal_mode').fetchone()[0]
        print(f"   Modo actual: {current_mode}")
        
        if current_mode.upper() == 'WAL':
            print("\n✅ La base de datos YA está en modo WAL")
            print("   No es necesario hacer cambios")
        else:
            print(f"\n⚠️  Cambiando de {current_mode} a WAL...")
            
            # Configurar WAL mode
            cursor.execute('PRAGMA journal_mode=WAL')
            new_mode = cursor.fetchone()[0]
            print(f"✅ Modo cambiado a: {new_mode}")
        
        # Aplicar configuraciones adicionales
        print("\n⚙️  Aplicando configuraciones de rendimiento...")
        
        configs = [
            ('busy_timeout', 60000, 'Timeout para locks (60 segundos)'),
            ('synchronous', 'NORMAL', 'Modo de sincronización'),
            ('cache_size', 10000, 'Tamaño de caché'),
            ('temp_store', 'MEMORY', 'Almacenamiento temporal'),
            ('mmap_size', 30000000000, 'Memory-mapped I/O (30GB)'),
        ]
        
        for pragma, value, desc in configs:
            try:
                if isinstance(value, str):
                    cursor.execute(f'PRAGMA {pragma}={value}')
                else:
                    cursor.execute(f'PRAGMA {pragma}={value}')
                print(f"   ✓ {desc}")
            except Exception as e:
                print(f"   ⚠️  {desc}: {e}")
        
        conn.commit()
        conn.close()
        
        print("\n" + "=" * 70)
        print("✅ CONFIGURACIÓN COMPLETADA EXITOSAMENTE")
        print("=" * 70)
        print("\n📋 CAMBIOS APLICADOS:")
        print("   • Modo WAL habilitado (permite lecturas concurrentes)")
        print("   • Timeout aumentado a 60 segundos")
        print("   • Rendimiento optimizado")
        print("   • Locks reducidos significativamente")
        
        print("\n🚀 PRÓXIMOS PASOS:")
        print("   1. Reinicia tu servidor CRUD")
        print("   2. El error 'database is locked' debería desaparecer")
        print("   3. Si usas otros servicios (lector RFID), reinícialos también")
        
        print("\n💡 BENEFICIOS DEL MODO WAL:")
        print("   • Múltiples lecturas simultáneas")
        print("   • Escrituras no bloquean lecturas")
        print("   • Mejor rendimiento en general")
        print("   • Menos probabilidad de locks")
        
        # Verificar archivos WAL
        wal_file = DB + "-wal"
        shm_file = DB + "-shm"
        
        print("\n📁 ARCHIVOS RELACIONADOS:")
        print(f"   • {os.path.basename(DB)} (base de datos principal)")
        if os.path.exists(wal_file):
            print(f"   • {os.path.basename(wal_file)} (Write-Ahead Log)")
        if os.path.exists(shm_file):
            print(f"   • {os.path.basename(shm_file)} (Shared memory)")
        
        print("\n" + "=" * 70)
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    fix_database_locked()
