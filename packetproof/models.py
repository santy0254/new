"""Estructuras de datos del monitor."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class ProbeResult:
    """Resultado de un ping individual a un objetivo."""

    host: str
    label: str
    trigger: bool
    success: bool
    rtt_ms: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sample:
    """Una medición: un ping a cada objetivo en un instante dado."""

    ts: float  # epoch en segundos (UTC)
    results: list[ProbeResult]

    @property
    def iso(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc).isoformat()

    def any_loss(self, only_trigger: bool = False) -> bool:
        return any(
            (not r.success) and (r.trigger or not only_trigger)
            for r in self.results
        )

    def to_dict(self) -> dict:
        return {"ts": self.ts, "iso": self.iso, "results": [r.to_dict() for r in self.results]}


@dataclass
class Event:
    """Un evento de degradación de red con su ventana de contexto."""

    start_ts: float
    cause: str  # "loss" | "latency" | "loss+latency"
    samples: list[Sample] = field(default_factory=list)
    pre: list[Sample] = field(default_factory=list)
    end_ts: float | None = None

    @property
    def window(self) -> list[Sample]:
        """Todas las muestras: contexto previo + evento + recuperación."""
        return self.pre + self.samples

    @property
    def duration_s(self) -> float:
        if self.end_ts is None:
            return 0.0
        return self.end_ts - self.start_ts

    @property
    def start_iso(self) -> str:
        return datetime.fromtimestamp(self.start_ts, tz=timezone.utc).isoformat()

    def stats(self) -> dict:
        """Estadísticas de pérdida/latencia por objetivo dentro del evento."""
        per_host: dict[str, dict] = {}
        # Solo la ventana "de evento" (excluye pre/post limpios) para % de pérdida
        core = self.samples
        for s in core:
            for r in s.results:
                d = per_host.setdefault(
                    r.host,
                    {"label": r.label, "trigger": r.trigger, "sent": 0, "lost": 0, "rtts": []},
                )
                d["sent"] += 1
                if r.success and r.rtt_ms is not None:
                    d["rtts"].append(r.rtt_ms)
                else:
                    d["lost"] += 1
        for d in per_host.values():
            rtts = d.pop("rtts")
            d["loss_pct"] = round(100.0 * d["lost"] / d["sent"], 1) if d["sent"] else 0.0
            d["avg_rtt_ms"] = round(sum(rtts) / len(rtts), 1) if rtts else None
            d["max_rtt_ms"] = round(max(rtts), 1) if rtts else None
        return per_host
