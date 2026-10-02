"""
Módulo de base de datos SQLite para Colombia Radar.
Maneja tablas: articulos, senales, fuente_salud, http_cache, feedback, series, backfill_estado.
Incluye migraciones aditivas automáticas.
"""
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Any


class Database:
    def __init__(self, db_path: str = "radar.db"):
        self.db_path = db_path
        self._init_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self.get_connection() as conn:
            cur = conn.cursor()

            # 1. Tabla articulos
            cur.execute("""
                CREATE TABLE IF NOT EXISTS articulos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    titulo TEXT,
                    fuente_id TEXT,
                    fecha TEXT,
                    resumen TEXT,
                    extracto TEXT,
                    creado_en TEXT
                )
            """)

            # 2. Tabla senales
            cur.execute("""
                CREATE TABLE IF NOT EXISTS senales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cluster_id INTEGER,
                    tipo TEXT,
                    etiqueta TEXT,
                    insumo TEXT,
                    certeza TEXT,
                    score REAL,
                    razonamiento TEXT,
                    empresas TEXT,
                    sectores TEXT,
                    articulos_ids TEXT,
                    creado_en TEXT
                )
            """)

            # 3. Tabla fuente_salud
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fuente_salud (
                    fuente_id TEXT PRIMARY KEY,
                    ultima_recoleccion TEXT,
                    items_recolectados INTEGER DEFAULT 0,
                    exitos INTEGER DEFAULT 0,
                    fallos INTEGER DEFAULT 0,
                    corridas_vacias_consecutivas INTEGER DEFAULT 0,
                    promedio_items REAL DEFAULT 0.0,
                    estado TEXT DEFAULT 'ok',
                    motivo_degradada TEXT DEFAULT ''
                )
            """)

            # 4. Tabla http_cache
            cur.execute("""
                CREATE TABLE IF NOT EXISTS http_cache (
                    url TEXT PRIMARY KEY,
                    etag TEXT,
                    last_modified TEXT,
                    body BLOB,
                    status_code INTEGER,
                    actualizado_en TEXT
                )
            """)

            # 5. Tabla feedback
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cluster_id INTEGER,
                    tipo TEXT,
                    util INTEGER,
                    fecha TEXT
                )
            """)

            # 6. Tabla series (macro e insumos)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS series (
                    serie_id TEXT,
                    fecha TEXT,
                    valor REAL,
                    PRIMARY KEY (serie_id, fecha)
                )
            """)

            # 7. Tabla backfill_estado (reanudación de backfill histórico)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS backfill_estado (
                    fuente_id TEXT PRIMARY KEY,
                    ultima_fecha TEXT,
                    paginacion_cursor TEXT
                )
            """)

            conn.commit()

        # Migraciones aditivas seguras
        self.migrar_esquema()

    def migrar_esquema(self):
        """Añade columnas nuevas a bases existentes sin romper datos."""
        columnas_por_tabla = {
            "articulos": [
                ("extracto", "TEXT"),
                ("resumen", "TEXT"),
                ("fuente_id", "TEXT"),
                ("creado_en", "TEXT"),
                ("medio", "TEXT"),
                ("certeza", "TEXT"),
            ],
            "fuente_salud": [
                ("corridas_vacias_consecutivas", "INTEGER DEFAULT 0"),
                ("promedio_items", "REAL DEFAULT 0.0"),
                ("estado", "TEXT DEFAULT 'ok'"),
                ("motivo_degradada", "TEXT DEFAULT ''"),
            ],
            "senales": [
                ("insumo", "TEXT"),
                ("razonamiento", "TEXT"),
                ("articulos_ids", "TEXT"),
                ("senal_key", "TEXT"),
                ("primera", "TEXT"),
                ("ultima", "TEXT"),
                ("n_notas", "INTEGER"),
                ("n_fuentes", "INTEGER"),
                ("score_breakdown", "TEXT"),
                ("medios", "TEXT"),
                ("actualizado_en", "TEXT"),
            ],
        }

        with self.get_connection() as conn:
            cur = conn.cursor()
            for tabla, columnas in columnas_por_tabla.items():
                cur.execute(f"PRAGMA table_info({tabla})")
                existentes = {row["name"] for row in cur.fetchall()}
                for col_name, col_type in columnas:
                    if col_name not in existentes:
                        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {col_name} {col_type}")
            # Una señal = una clave estable. Las filas antiguas sin clave (NULL) no chocan.
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_senales_key ON senales(senal_key)")
            conn.commit()

    # --- Métodos de Artículos ---
    def guardar_articulo(
        self,
        url: str,
        titulo: str,
        fuente_id: str,
        fecha: str,
        resumen: Optional[str] = None,
        extracto: Optional[str] = None,
        medio: Optional[str] = None,
        certeza: Optional[str] = None,
    ) -> Optional[int]:
        creado_en = datetime.utcnow().isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO articulos (url, titulo, fuente_id, fecha, resumen, extracto, creado_en, medio, certeza)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        titulo=excluded.titulo,
                        resumen=COALESCE(excluded.resumen, articulos.resumen),
                        extracto=COALESCE(excluded.extracto, articulos.extracto),
                        fecha=excluded.fecha,
                        medio=COALESCE(excluded.medio, articulos.medio),
                        certeza=COALESCE(excluded.certeza, articulos.certeza)
                    """,
                    (url, titulo, fuente_id, fecha, resumen, extracto, creado_en, medio, certeza),
                )
                conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def obtener_articulos(self, limit: int = 100, solo_no_demo: bool = False) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM articulos"
            params = []
            if solo_no_demo:
                query += " WHERE fuente_id != 'demo'"
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def obtener_articulos_por_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        """Devuelve los artículos con esos ids (sin los de demostración), ordenados por id."""
        ids = [int(i) for i in ids if i is not None]
        if not ids:
            return []
        marcas = ",".join("?" for _ in ids)
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM articulos WHERE id IN ({marcas}) AND fuente_id != 'demo' ORDER BY id ASC",
                ids,
            )
            return [dict(row) for row in cur.fetchall()]

    def contar_articulos(self) -> int:
        with self.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM articulos WHERE fuente_id != 'demo'").fetchone()[0]

    def actualizar_extracto_articulo(self, articulo_id: int, extracto: str):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE articulos SET extracto = ? WHERE id = ?", (extracto, articulo_id))
            conn.commit()

    # --- Métodos de Señales ---
    def guardar_senal(self, senal: Dict[str, Any]) -> int:
        """
        Guarda una señal. Si trae 'senal_key' y ya existe, la ACTUALIZA (mismo id, sin duplicar).
        Sin 'senal_key' se comporta como antes: inserta una fila nueva.
        """
        ahora = datetime.utcnow().isoformat()
        key = senal.get("senal_key")
        campos = {
            "cluster_id": senal.get("cluster_id"),
            "tipo": senal.get("tipo"),
            "etiqueta": senal.get("etiqueta"),
            "insumo": senal.get("insumo"),
            "certeza": senal.get("certeza", "probable"),
            "score": senal.get("score", 1.0),
            "razonamiento": senal.get("razonamiento", ""),
            "empresas": json.dumps(senal.get("empresas", []), ensure_ascii=False),
            "sectores": json.dumps(senal.get("sectores", []), ensure_ascii=False),
            "articulos_ids": json.dumps(senal.get("articulos_ids", [])),
            "primera": senal.get("primera"),
            "ultima": senal.get("ultima"),
            "n_notas": senal.get("n_notas"),
            "n_fuentes": senal.get("n_fuentes"),
            "score_breakdown": json.dumps(senal["score_breakdown"], ensure_ascii=False)
            if senal.get("score_breakdown") is not None
            else None,
            "medios": json.dumps(senal.get("medios", []), ensure_ascii=False),
            "actualizado_en": ahora,
        }
        with self.get_connection() as conn:
            cur = conn.cursor()
            if key:
                cur.execute("SELECT id FROM senales WHERE senal_key = ?", (key,))
                fila = cur.fetchone()
                if fila:
                    asignaciones = ", ".join(f"{c} = ?" for c in campos)
                    cur.execute(
                        f"UPDATE senales SET {asignaciones} WHERE id = ?",
                        list(campos.values()) + [fila["id"]],
                    )
                    conn.commit()
                    return fila["id"]

            columnas = list(campos.keys()) + ["senal_key", "creado_en"]
            marcas = ", ".join("?" for _ in columnas)
            cur.execute(
                f"INSERT INTO senales ({', '.join(columnas)}) VALUES ({marcas})",
                list(campos.values()) + [key, ahora],
            )
            conn.commit()
            return cur.lastrowid

    @staticmethod
    def _fila_a_senal(r) -> Dict[str, Any]:
        d = dict(r)
        for campo in ("empresas", "sectores", "articulos_ids", "medios"):
            d[campo] = json.loads(d[campo]) if d.get(campo) else []
        d["score_breakdown"] = json.loads(d["score_breakdown"]) if d.get("score_breakdown") else None
        return d

    def obtener_senales(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM senales ORDER BY id DESC LIMIT ?", (limit,))
            return [self._fila_a_senal(r) for r in cur.fetchall()]

    def obtener_senales_exportables(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Señales con clave estable, de mayor a menor score. Las filas antiguas sin clave se omiten."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM senales WHERE senal_key IS NOT NULL "
                "ORDER BY score DESC, ultima DESC, id DESC LIMIT ?",
                (limit,),
            )
            return [self._fila_a_senal(r) for r in cur.fetchall()]

    def buscar_senales_por_patron(self, patron: str) -> List[Dict[str, Any]]:
        """Busca señales cuya clave encaja con un patrón LIKE (usa \\ como escape)."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM senales WHERE senal_key LIKE ? ESCAPE '\\' ORDER BY id DESC",
                (patron,),
            )
            return [self._fila_a_senal(r) for r in cur.fetchall()]

    # --- Salud de Fuentes ---
    def registrar_salud(
        self,
        fuente_id: str,
        items_recolectados: int,
        exito: bool,
        motivo_error: str = "",
        max_corridas_vacias: int = 3,
        umbral_caida_brusca: float = 0.5,
    ):
        ahora = datetime.utcnow().isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM fuente_salud WHERE fuente_id = ?", (fuente_id,))
            row = cur.fetchone()

            if not row:
                exitos = 1 if exito else 0
                fallos = 0 if exito else 1
                vacias = 1 if (exito and items_recolectados == 0) else 0
                promedio = float(items_recolectados)
                estado = "ok" if exito else "error"
                motivo = motivo_error if not exito else ""
                cur.execute(
                    """
                    INSERT INTO fuente_salud (fuente_id, ultima_recoleccion, items_recolectados, exitos, fallos, corridas_vacias_consecutivas, promedio_items, estado, motivo_degradada)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (fuente_id, ahora, items_recolectados, exitos, fallos, vacias, promedio, estado, motivo),
                )
            else:
                exitos = row["exitos"] + (1 if exito else 0)
                fallos = row["fallos"] + (0 if exito else 1)
                antiguas_vacias = row["corridas_vacias_consecutivas"] or 0
                promedio_previo = row["promedio_items"] or 0.0

                if exito:
                    if items_recolectados == 0:
                        vacias = antiguas_vacias + 1
                    else:
                        vacias = 0
                else:
                    vacias = antiguas_vacias

                # Calcular promedio móvil exponencial suave (alfa=0.2)
                nuevo_promedio = (0.8 * promedio_previo) + (0.2 * items_recolectados)

                # Detección de degradación
                estado = "ok"
                motivo = ""

                if not exito:
                    estado = "error"
                    motivo = motivo_error or "Fallo de conexión o respuesta no exitosa"
                elif vacias >= max_corridas_vacias:
                    estado = "degradada"
                    motivo = f"0 items durante {vacias} corridas consecutivas"
                elif promedio_previo > 4 and items_recolectados < (promedio_previo * umbral_caida_brusca):
                    estado = "degradada"
                    motivo = f"Caída brusca de items ({items_recolectados} vs promedio {promedio_previo:.1f})"

                cur.execute(
                    """
                    UPDATE fuente_salud SET
                        ultima_recoleccion = ?,
                        items_recolectados = ?,
                        exitos = ?,
                        fallos = ?,
                        corridas_vacias_consecutivas = ?,
                        promedio_items = ?,
                        estado = ?,
                        motivo_degradada = ?
                    WHERE fuente_id = ?
                    """,
                    (ahora, items_recolectados, exitos, fallos, vacias, nuevo_promedio, estado, motivo, fuente_id),
                )
            conn.commit()

    def obtener_salud_fuentes(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM fuente_salud ORDER BY fuente_id ASC")
            return [dict(r) for r in cur.fetchall()]

    # --- HTTP Cache ---
    def guardar_http_cache(self, url: str, etag: Optional[str], last_modified: Optional[str], body: bytes, status_code: int):
        ahora = datetime.utcnow().isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO http_cache (url, etag, last_modified, body, status_code, actualizado_en)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (url, etag, last_modified, body, status_code, ahora),
            )
            conn.commit()

    def obtener_http_cache(self, url: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM http_cache WHERE url = ?", (url,))
            row = cur.fetchone()
            return dict(row) if row else None

    # --- Feedback ---
    def guardar_feedback(self, cluster_id: int, tipo: str, util: int):
        ahora = datetime.utcnow().isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO feedback (cluster_id, tipo, util, fecha) VALUES (?, ?, ?, ?)",
                (cluster_id, tipo, util, ahora),
            )
            conn.commit()

    def obtener_feedback(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM feedback ORDER BY id DESC")
            return [dict(r) for r in cur.fetchall()]

    # --- Series (Macro e Insumos) ---
    def guardar_serie_valor(self, serie_id: str, fecha: str, valor: float) -> bool:
        with self.get_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO series (serie_id, fecha, valor)
                    VALUES (?, ?, ?)
                    """,
                    (serie_id, fecha, valor),
                )
                conn.commit()
                return True
            except Exception:
                return False

    def obtener_ultimos_valores_serie(self, serie_id: str, limite: int = 10) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM series WHERE serie_id = ? ORDER BY fecha DESC LIMIT ?",
                (serie_id, limite),
            )
            return [dict(r) for r in cur.fetchall()]

    def obtener_series_ids(self) -> List[str]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT serie_id FROM series ORDER BY serie_id ASC")
            return [r["serie_id"] for r in cur.fetchall()]

    # --- Backfill histórico estado ---
    def guardar_backfill_estado(self, fuente_id: str, ultima_fecha: str, paginacion_cursor: str):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO backfill_estado (fuente_id, ultima_fecha, paginacion_cursor)
                VALUES (?, ?, ?)
                """,
                (fuente_id, ultima_fecha, paginacion_cursor),
            )
            conn.commit()

    def obtener_backfill_estado(self, fuente_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM backfill_estado WHERE fuente_id = ?", (fuente_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    # --- Limpieza segura (Punto 0) ---
    def limpiar_demo(self) -> int:
        """Borra ÚNICAMENTE los datos de demostración (fuente_id='demo'). Conserva la historia real."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM articulos WHERE fuente_id = 'demo'")
            borrados = cur.rowcount
            conn.commit()
            return borrados
