# Colombia Radar

Herramienta personal y educativa para recolección, detección de eventos corporativos y monitoreo macroeconómico en Colombia.


---

## ☁️ Ejecución en GitHub (sin servidor propio)

El backend corre solo en GitHub Actions y publica los datos que lee la interfaz.

**Qué hace `.github/workflows/actualizar.yml`**
1. Restaura la base desde la rama `datos` (si existe).
2. Corre `python run.py ciclo --estricto`: recolecta, analiza y **falla de verdad** si no se recolectó nada o si menos de la mitad de las fuentes respondió.
3. Corre `python run.py exportar`: escribe `senales.json`, `macro.json`, `salud.json` y `meta.json` con la hora real de generación.
4. Publica los JSON y una copia de la base en la rama `datos`, que se **reemplaza completa** en cada corrida (el historial no crece).
5. Si el último commit de la rama principal tiene más de 30 días, deja una marca de actividad (GitHub apaga las tareas programadas tras 60 días sin actividad).

**Horario**: lunes a viernes, de 7:17 a. m. a 6:17 p. m. hora de Colombia, y una vez en la madrugada (2:47 a. m.). Se evita el minuto :00 porque es el más congestionado. GitHub puede retrasar o saltarse corridas en horas de mucha carga.

**Puesta en marcha**
1. Sube el contenido de esta carpeta a la **raíz** de un repositorio público (`run.py`, `radar/`, `.github/`…).
2. *Settings → Actions → General → Workflow permissions*: marca **Read and write permissions**.
3. *Actions → Actualizar datos del Radar → Run workflow* (primera corrida).
4. Cuando termine y exista la rama `datos`: *Settings → Pages → Deploy from a branch → `datos` / `(root)`*.
5. Los JSON quedan en `https://TU-USUARIO.github.io/TU-REPOSITORIO/data/senales.json` (y `macro.json`, `salud.json`, `meta.json`). Esa dirección, sin el nombre del archivo, es la que va en la interfaz.

**Si una fuente falla**: el paso "Recolectar y analizar noticias" lista cada fuente caída con su motivo (por ejemplo `HTTP 403`). Los servidores de GitHub tienen IPs que algunos sitios bloquean; esos bloqueos no se esquivan (el programa se identifica y respeta `robots.txt`). Las fuentes bloqueadas se pueden recolectar desde un computador propio con `python run.py ciclo`.

**Derechos de autor**: los JSON publicados llevan solo enlace, titular, medio, fecha y certeza. No incluyen resúmenes (se activan con `publicacion.incluir_resumen: true` en `config/sources.yaml`). La copia de la base que se publica (`radar_publico.db`) sale sin extractos, sin resúmenes y sin caché de páginas.

**Una sola fórmula del score**: vive en `radar/analysis/calor.py`. La interfaz solo muestra `score` y `scoreBreakdown`.

**Certeza**: sale de la `certeza` declarada para cada fuente en `config/sources.yaml`. Una señal toma la más alta de sus notas (una nota de la BVC la deja como *Confirmada*).

**ID de señal estable**: `tipo_empresa_semana_hash`. El mismo tema conserva su ID mientras siga activo, así que cada corrida actualiza la señal en vez de duplicarla. Donde no hay dato (fecha, medio…) el JSON lleva `null` o lista vacía.

---

## 🚀 Comandos Principales (`run.py` y `lanzador.py`)

| Comando | Descripción |
| :--- | :--- |
| `python lanzador.py` | **Lanzador de PC**: Inicia el servidor local y abre automáticamente la interfaz en el navegador web. |
| `python run.py servir` | Inicia el tablero web Flask en `http://127.0.0.1:5000`. |
| `python run.py probar <id>` | Prueba un colector individual configurado en `config/sources.yaml` y actualiza la tabla `fuente_salud`. |
| `python run.py descubrir <url>` | Inspecciona una página web en busca de enlaces a feeds RSS/Atom respetando `robots.txt`. |
| `python run.py recolectar` | Descarga noticias y datos de todas las fuentes activas y las guarda en la base de datos. |
| `python run.py analizar` | Detecta eventos corporativos (fusiones, insolvencias, capex, etc.), entidades e insumos, generando señales con score de calor. |
| `python run.py ciclo` | Ejecuta el flujo completo: `recolectar` → `guardar` → `analizar` → `limpiar` (conservando toda la historia real). Con `--estricto` sale con error si no se recolectó nada o si respondió menos de la mitad de las fuentes (`--min-fuentes-ok` ajusta ese umbral). |
| `python run.py exportar [--salida carpeta] [--base-publica archivo.db]` | Escribe `senales.json`, `macro.json`, `salud.json` y `meta.json` (el mismo formato que sirve el Flask local). Con `--base-publica` también copia la base sin texto de medios. |
| `python run.py todo` | Ejecuta un ciclo completo y arranca el servidor web. |
| `python run.py evaluar` | Analiza el desempeño del sistema comparando señales detectadas contra el feedback de analistas. |
| `python run.py historico --desde AAAA-MM-DD` | **Backfill Histórico**: Descarga noticias pasadas de Colombia desde el archivo de GDELT con paginación, límites de tasa y progreso reanudable. |
| `python run.py importar-emisores <archivo.csv>` | **Catálogo de Emisores**: Lee un CSV oficial de emisores y lo fusiona en `config/empresas.yaml` sin pisar alias manuales, generando alias limpios (sin S.A., S.A.S., Ltda.). |

---

## 📌 Reglas de Conservación de Historia y Esquema de Base de Datos

1. **Conservación de Historia (Punto 0)**:
   - `guardar()` no descarta noticias con fechas anteriores al 1 de enero. Toda la historia se almacena permanentemente.
   - `limpiar()` elimina **únicamente** los registros de prueba con `fuente_id='demo'`.
2. **Migraciones Aditivas Automáticas (Regla 3)**:
   - Al iniciar `Database("radar.db")`, el sistema ejecuta `PRAGMA table_info` y añade cualquier columna faltante mediante `ALTER TABLE ... ADD COLUMN` sin romper bases existentes.

### Esquema SQLite (`radar.db`)
- `articulos`: `id`, `url` (UNIQUE), `titulo`, `fuente_id`, `fecha`, `resumen`, `extracto`, `creado_en`.
- `senales`: `id`, `cluster_id`, `tipo`, `etiqueta`, `insumo`, `certeza`, `score`, `razonamiento`, `empresas`, `sectores`, `articulos_ids`, `creado_en`.
- `fuente_salud`: `fuente_id`, `ultima_recoleccion`, `items_recolectados`, `exitos`, `fallos`, `corridas_vacias_consecutivas`, `promedio_items`, `estado`, `motivo_degradada`.
- `http_cache`: `url`, `etag`, `last_modified`, `body`, `status_code`, `actualizado_en`.
- `feedback`: `id`, `cluster_id`, `tipo`, `util`, `fecha`.
- `series`: `serie_id`, `fecha`, `valor` (PRIMARY KEY compuesto).
- `backfill_estado`: `fuente_id`, `ultima_fecha`, `paginacion_cursor`.

---

## 🔍 Lista de Elementos Marcados "VERIFICAR"

Como el entorno de desarrollo opera sin conexión a internet externa para pruebas herméticas, las siguientes URLs, endpoints de APIs y selectores HTML quedaron configurados con el comentario `# VERIFICAR` para que los valides en tu conexión real:

### 1. Fuentes Oficiales Directas (`config/sources.yaml`)
- `superfinanciera_relevante`:
  - URL configurada: `https://www.superfinanciera.gov.co/inicio/informacion-relevante-emisores`
  - Selectores: `table.tabla-informacion-relevante tbody tr`, `.asunto a`, `.emisor`
  - *VERIFICAR*: Si la Superfinanciera requiere token para el webservice SIMEV/RNVE o si mantiene la tabla HTML estática.
- `bvc_hechos_relevantes`:
  - URL configurada: `https://www.bvc.com.co/noticias-y-boletines/hechos-relevantes`
  - *VERIFICAR*: Endpoint exacto de boletines para emisores en la BVC.
- `sic_integraciones`:
  - URL configurada: `https://www.sic.gov.co/integraciones-empresariales`
  - *VERIFICAR*: Ruta de consulta pública del registro de resoluciones de integraciones empresariales.
- `supersociedades_insolvencia`:
  - URL configurada: `https://www.supersociedades.gov.co/procesos-insolvencia-autos`
  - *VERIFICAR*: Estructura del portal de consulta web del sistema Baranda Virtual / Insolvencia.

### 2. Medios de Comunicación Directos (`config/sources.yaml`)
*Configurados como inactivos (`activo: false`) por defecto para no generar fallos hasta que confirmes sus rutas exactas con `python run.py descubrir <url>`*:
- `medio_larepublica`: `https://www.larepublica.co/rss/empresas`
- `medio_valora_analitik`: `https://www.valoraanalitik.com/feed/`
- `medio_dinero`: `https://www.semana.com/rss/economia/empresas/`
- `medio_portafolio`: `https://www.portafolio.co/rss/negocios` (bajo protocolo HTTPS)
- `medio_bloomberg_linea`: `https://www.bloomberglinea.com/arc/outboundfeeds/rss/category/colombia/`
- `medio_eltiempo_economia`: `https://www.eltiempo.com/rss/economia.xml`

### 3. Series de Datos Abiertos (`config/sources.yaml`)
- `serie_trm`: Dataset Socrata de datos.gov.co `32sa-8pi3` (`https://www.datos.gov.co/resource/32sa-8pi3.json`).
- `serie_tasa_politica`: Dataset BanRep en datos.gov.co para tasa de intervención de política monetaria.
- `serie_ipc`: Dataset DANE para variación anual de inflación.
- `serie_insumo_fertilizantes`: Dataset SIPSA DANE para precios mayoristas de Urea/fertilizantes.

### 4. Backfill Histórico GDELT (`run.py` -> `cmd_historico`)
- API: `https://api.gdeltproject.org/api/v2/doc/doc`
- Límites: GDELT limita a un máximo de 250 artículos por consulta (`maxrecords`). Se configuró un valor seguro por defecto de 75 items por ventana diaria con delay de 2.5s para respetar las políticas de tasa de la API.

---

## 🛠️ Pasos para Verificar las Fuentes Reales en tu PC

Cuando estés en tu PC con acceso a internet:

1. **Probar fuentes oficiales**:
   ```bash
   python run.py probar superfinanciera_relevante
   python run.py probar bvc_hechos_relevantes
   python run.py probar sic_integraciones
   python run.py probar supersociedades_insolvencia
   ```

2. **Descubrir y activar medios de comunicación**:
   ```bash
   python run.py descubrir https://www.larepublica.co
   python run.py descubrir https://www.portafolio.co
   python run.py descubrir https://www.valoraanalitik.com
   ```
   Una vez confirmadas las URLs en la salida del comando, cambia `activo: true` en `config/sources.yaml` y pruébalas con:
   ```bash
   python run.py probar medio_larepublica
   python run.py probar medio_portafolio
   ```

3. **Probar series macroeconómicas**:
   ```bash
   python run.py probar serie_trm
   ```

4. **Importar listado oficial de emisores**:
   Descarga el CSV del Registro Nacional de Valores y Emisores (RNVE) o BVC y ejecuta:
   ```bash
   python run.py importar-emisores ruta_a_tu_archivo.csv
   ```

5. **Iniciar el tablero en tu PC**:
   ```bash
   python lanzador.py
   ```
   Se abrirá automáticamente el navegador en `http://127.0.0.1:5000`.
