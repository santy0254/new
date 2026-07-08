"""Carga de configuración y valores por defecto."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore


@dataclass
class Target:
    label: str
    host: str
    trigger: bool = True


@dataclass
class Config:
    interval_seconds: float = 1.0
    probe_timeout_ms: int = 1000
    pre_event_seconds: int = 10
    post_event_seconds: int = 10
    max_event_seconds: int = 300
    latency_threshold_ms: float = 300.0
    data_dir: str = "packetproof-data"
    targets: list[Target] = field(default_factory=list)

    @property
    def recovery_samples(self) -> int:
        return max(1, round(self.post_event_seconds / self.interval_seconds))

    @property
    def pre_samples(self) -> int:
        return max(1, round(self.pre_event_seconds / self.interval_seconds))


def default_targets() -> list[Target]:
    """Objetivos por defecto.

    El gateway LAN NO dispara eventos (su pérdida es problema local); los
    anclajes públicos SÍ, porque pérdida ahí con gateway sano = problema del ISP.
    """
    gw = detect_gateway()
    targets: list[Target] = []
    if gw:
        targets.append(Target(label="Router / Gateway (LAN)", host=gw, trigger=False))
    targets += [
        Target(label="Cloudflare (1.1.1.1)", host="1.1.1.1", trigger=True),
        Target(label="Google (8.8.8.8)", host="8.8.8.8", trigger=True),
        Target(label="Quad9 (9.9.9.9)", host="9.9.9.9", trigger=True),
    ]
    return targets


def detect_gateway() -> str | None:
    """Detecta la puerta de enlace por defecto en Linux y Windows."""
    try:
        if sys.platform.startswith("linux"):
            route = Path("/proc/net/route")
            if route.exists():
                for line in route.read_text().splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 3 and parts[1] == "00000000":
                        gw_hex = parts[2]
                        octets = [str(int(gw_hex[i : i + 2], 16)) for i in (6, 4, 2, 0)]
                        return ".".join(octets)
        elif sys.platform == "win32":
            out = subprocess.run(
                ["route", "print", "0.0.0.0"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    return parts[2]
        elif sys.platform == "darwin":
            out = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                if "gateway:" in line:
                    return line.split(":", 1)[1].strip()
    except Exception:
        return None
    return None


def load_config(path: str | os.PathLike | None) -> Config:
    """Carga configuración desde TOML; si no hay archivo usa valores por defecto."""
    cfg = Config()
    data: dict = {}
    if path:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"No existe el archivo de configuración: {p}")
        if tomllib is None:
            raise RuntimeError("Se requiere Python 3.11+ (tomllib) para leer TOML")
        data = tomllib.loads(p.read_text())

    for k in (
        "interval_seconds", "probe_timeout_ms", "pre_event_seconds",
        "post_event_seconds", "max_event_seconds", "latency_threshold_ms",
        "data_dir",
    ):
        if k in data:
            setattr(cfg, k, data[k])

    raw_targets = data.get("targets")
    if raw_targets:
        for t in raw_targets:
            host = t["host"]
            if host in ("auto", "gateway"):
                gw = detect_gateway()
                if not gw:
                    continue
                host = gw
            cfg.targets.append(
                Target(label=t.get("label", host), host=host, trigger=t.get("trigger", True))
            )
    else:
        cfg.targets = default_targets()

    if not cfg.targets:
        raise RuntimeError("No hay objetivos para monitorear (revisá la configuración)")
    return cfg
