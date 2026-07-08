"""Sondas ICMP multiplataforma usando el comando ``ping`` del sistema.

Se usa el ``ping`` nativo (sin dependencias ni privilegios de root) y se
parsea el RTT con una expresión regular tolerante a distintos idiomas
(Windows en inglés/español y Linux).
"""

from __future__ import annotations

import re
import subprocess
import sys

from .models import ProbeResult

# Captura "time=12.3 ms", "time<1ms", "tiempo=12ms" (Windows en español)
_RTT_RE = re.compile(r"(?:time|tiempo)[=<]\s*([\d.,]+)\s*ms", re.IGNORECASE)


def _build_cmd(host: str, timeout_ms: int) -> list[str]:
    if sys.platform == "win32":
        # -n 1: un paquete, -w timeout en ms
        return ["ping", "-n", "1", "-w", str(timeout_ms), host]
    # Linux / macOS: -c 1 un paquete, -W timeout en segundos (entero, mín. 1)
    timeout_s = max(1, round(timeout_ms / 1000))
    return ["ping", "-c", "1", "-W", str(timeout_s), host]


def _parse_rtt(output: str) -> float | None:
    m = _RTT_RE.search(output)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def ping(host: str, label: str, trigger: bool, timeout_ms: int) -> ProbeResult:
    """Envía un ping y devuelve el resultado.

    Se considera éxito únicamente si se pudo parsear un RTT de la respuesta;
    el código de retorno del comando no es confiable en todas las plataformas.
    """
    cmd = _build_cmd(host, timeout_ms)
    # Margen extra sobre el timeout de ping para no matar el proceso antes.
    proc_timeout = timeout_ms / 1000 + 2
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=proc_timeout,
        )
        rtt = _parse_rtt(proc.stdout)
        success = rtt is not None
        return ProbeResult(host=host, label=label, trigger=trigger, success=success, rtt_ms=rtt)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ProbeResult(host=host, label=label, trigger=trigger, success=False, rtt_ms=None)
