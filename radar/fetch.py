"""
Módulo de descarga respetuosa de contenidos HTTP (Fetcher).
Maneja límites por dominio, reintentos, ETag/Last-Modified y robots.txt.
"""
import time
import urllib.parse
import urllib.robotparser
import logging
from typing import Optional, Tuple, Dict, Any

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger("radar.fetch")

DEFAULT_USER_AGENT = "ColombiaRadar/1.0 (+https://github.com/local/colombia-radar; herramienta educativa personal)"


class Fetcher:
    """
    Cliente HTTP con política de respeto:
    - user-agent identificable
    - respeto a robots.txt
    - min_delay por dominio
    - soporte de reintentos y ETag/Last-Modified
    """

    def __init__(
        self,
        db=None,
        user_agent: str = DEFAULT_USER_AGENT,
        default_min_delay: float = 1.0,
        max_retries: int = 2,
        timeout: int = 15,
        verify_robots: bool = True,
    ):
        self.db = db
        self.user_agent = user_agent
        self.default_min_delay = default_min_delay
        self.max_retries = max_retries
        self.timeout = timeout
        self.verify_robots = verify_robots
        self._last_request: Dict[str, float] = {}
        self._robots_cache: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self._mock_responses: Dict[str, Tuple[int, bytes, Dict[str, str]]] = {}
        # Último resultado por URL: {url: (status | None, motivo)}. Permite distinguir
        # "la fuente no tiene novedades" de "el sitio nos bloqueó" (403, 429...).
        self.ultimo_estado: Dict[str, Tuple[Optional[int], str]] = {}

    def registrar_mock(self, url: str, status_code: int = 200, body: bytes = b"", headers: Optional[Dict[str, str]] = None):
        """Registra una respuesta simulada para pruebas offline."""
        self._mock_responses[url] = (status_code, body, headers or {})

    def _obtener_dominio(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc.lower()

    def _respetar_delay(self, dominio: str, min_delay: Optional[float] = None):
        delay = min_delay if min_delay is not None else self.default_min_delay
        if delay <= 0:
            return
        ahora = time.time()
        ultimo = self._last_request.get(dominio, 0.0)
        espera = delay - (ahora - ultimo)
        if espera > 0:
            time.sleep(espera)
        self._last_request[dominio] = time.time()

    def permite_robots(self, url: str) -> bool:
        """Verifica si robots.txt permite la URL."""
        if not self.verify_robots:
            return True
        if url in self._mock_responses:
            return True

        dominio = self._obtener_dominio(url)
        if not dominio:
            return True

        parsed = urllib.parse.urlparse(url)
        base_robots = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        if dominio not in self._robots_cache:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(base_robots)
            try:
                # Si hay mock para robots.txt, usarlo
                if base_robots in self._mock_responses:
                    _, body, _ = self._mock_responses[base_robots]
                    rp.parse(body.decode("utf-8", errors="ignore").splitlines())
                else:
                    # En modo sin internet, no bloquear si robots.txt falla
                    rp.read()
            except Exception as e:
                logger.debug(f"No se pudo leer robots.txt para {dominio}: {e}")
                # Si falla robots.txt, asumimos permitido de forma conservadora
            self._robots_cache[dominio] = rp

        rp = self._robots_cache[dominio]
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def get(
        self,
        url: str,
        min_delay: Optional[float] = None,
        headers: Optional[Dict[str, str]] = None,
        use_cache: bool = True,
    ) -> Tuple[Optional[int], Optional[bytes], Dict[str, str]]:
        """
        Descarga una URL respetando límites, robots y cache HTTP (ETag / Last-Modified).
        Retorna (status_code, body_bytes, headers_dict) y deja anotado el resultado en
        self.ultimo_estado[url].
        """
        resultado = self._get_interno(url, min_delay=min_delay, headers=headers, use_cache=use_cache)
        status, _, hdrs = resultado
        if status is None:
            if hdrs.get("X-Robots-Blocked"):
                motivo = "robots.txt no permite la descarga (o no se pudo leer robots.txt)"
            else:
                motivo = hdrs.get("error") or "sin respuesta del servidor"
        else:
            motivo = ""
        self.ultimo_estado[url] = (status, motivo)
        return resultado

    def _get_interno(
        self,
        url: str,
        min_delay: Optional[float] = None,
        headers: Optional[Dict[str, str]] = None,
        use_cache: bool = True,
    ) -> Tuple[Optional[int], Optional[bytes], Dict[str, str]]:
        # 1. Comprobar si hay respuesta simulada en mock
        if url in self._mock_responses:
            st, b, h = self._mock_responses[url]
            return st, b, h

        # 2. Respetar robots.txt
        if not self.permite_robots(url):
            logger.warning(f"robots.txt prohíbe la descarga de: {url}")
            return None, None, {"X-Robots-Blocked": "true"}

        dominio = self._obtener_dominio(url)
        self._respetar_delay(dominio, min_delay)

        req_headers = {"User-Agent": self.user_agent}
        if headers:
            req_headers.update(headers)

        cached_etag = None
        cached_lm = None
        if self.db and use_cache:
            cache_info = self.db.obtener_http_cache(url)
            if cache_info:
                cached_etag = cache_info.get("etag")
                cached_lm = cache_info.get("last_modified")
                if cached_etag:
                    req_headers["If-None-Match"] = cached_etag
                if cached_lm:
                    req_headers["If-Modified-Since"] = cached_lm

        # 3. Intentos de descarga con reintentos
        for intento in range(self.max_retries + 1):
            try:
                if requests is None:
                    # Fallback a urllib estándar
                    import urllib.request
                    req = urllib.request.Request(url, headers=req_headers)
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        status = resp.status
                        body = resp.read()
                        res_headers = dict(resp.headers)
                else:
                    r = requests.get(url, headers=req_headers, timeout=self.timeout)
                    status = r.status_code
                    body = r.content
                    res_headers = dict(r.headers)

                # Si el servidor responde 304 Not Modified, servimos del cache
                if status == 304 and self.db and use_cache:
                    cached_data = self.db.obtener_http_cache(url)
                    if cached_data and cached_data.get("body"):
                        return 304, cached_data["body"], res_headers

                # Guardar en cache si fue exitoso
                if status == 200 and self.db and use_cache:
                    etag = res_headers.get("ETag") or res_headers.get("etag")
                    last_mod = res_headers.get("Last-Modified") or res_headers.get("last-modified")
                    self.db.guardar_http_cache(url, etag, last_mod, body, status)

                return status, body, res_headers

            except Exception as e:
                logger.warning(f"Error descargando {url} (intento {intento + 1}/{self.max_retries + 1}): {e}")
                if intento < self.max_retries:
                    time.sleep(1.0 * (intento + 1))
                else:
                    return None, None, {"error": str(e)}

        return None, None, {}
