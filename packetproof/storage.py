"""Persistencia de eventos: JSON, CSV y actualización del índice."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .models import Event

log = logging.getLogger("packetproof")


def event_dirname(ev: Event) -> str:
    return datetime.fromtimestamp(ev.start_ts, tz=timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def save_event(cfg: Config, ev: Event) -> Path:
    """Guarda toda la evidencia de un evento y devuelve su carpeta."""
    base = Path(cfg.data_dir) / "events" / event_dirname(ev)
    base.mkdir(parents=True, exist_ok=True)

    stats = ev.stats()

    # 1) JSON completo con todas las muestras (contexto previo + evento + post).
    payload = {
        "start": ev.start_iso,
        "end": datetime.fromtimestamp(ev.end_ts, tz=timezone.utc).isoformat() if ev.end_ts else None,
        "duration_s": round(ev.duration_s, 1),
        "cause": ev.cause,
        "pre_event_seconds": cfg.pre_event_seconds,
        "post_event_seconds": cfg.post_event_seconds,
        "latency_threshold_ms": cfg.latency_threshold_ms,
        "stats": stats,
        "samples": [s.to_dict() for s in ev.window],
    }
    (base / "event.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # 2) CSV plano (una fila por muestra, una columna de RTT por objetivo).
    _write_csv(base / "samples.csv", ev)

    # 3) Resumen legible.
    (base / "summary.txt").write_text(_summary_text(cfg, ev, stats))

    # 4) Índice acumulado para el reporte agregado.
    _append_index(cfg, ev, stats, base)

    log.info("Evidencia guardada en %s", base)
    return base


def _write_csv(path: Path, ev: Event) -> None:
    hosts = [r.host for r in ev.window[0].results] if ev.window else []
    labels = {r.host: r.label for s in ev.window for r in s.results}
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = ["timestamp_iso", "epoch"]
        for h in hosts:
            header += [f"{labels[h]} rtt_ms", f"{labels[h]} ok"]
        w.writerow(header)
        for s in ev.window:
            by_host = {r.host: r for r in s.results}
            row = [s.iso, f"{s.ts:.3f}"]
            for h in hosts:
                r = by_host.get(h)
                row += [
                    "" if (r is None or r.rtt_ms is None) else f"{r.rtt_ms:.2f}",
                    "1" if (r and r.success) else "0",
                ]
            w.writerow(row)


def _summary_text(cfg: Config, ev: Event, stats: dict) -> str:
    lines = [
        "PacketProof - Resumen de evento",
        "=" * 40,
        f"Inicio:    {ev.start_iso}",
        f"Duración:  {ev.duration_s:.1f} s",
        f"Causa:     {ev.cause}",
        f"Umbral latencia: {cfg.latency_threshold_ms:.0f} ms",
        "",
        "Por objetivo (durante el evento):",
    ]
    for host, d in stats.items():
        flag = "[DISPARA]" if d["trigger"] else "[LAN]"
        avg = f"{d['avg_rtt_ms']} ms" if d["avg_rtt_ms"] is not None else "s/d"
        mx = f"{d['max_rtt_ms']} ms" if d["max_rtt_ms"] is not None else "s/d"
        lines.append(
            f"  {flag} {d['label']:<28} pérdida {d['loss_pct']:>5}%  "
            f"(perdidos {d['lost']}/{d['sent']})  avg {avg}  max {mx}"
        )
    return "\n".join(lines) + "\n"


def _append_index(cfg: Config, ev: Event, stats: dict, base: Path) -> None:
    index = Path(cfg.data_dir) / "events" / "index.jsonl"
    # Pérdida máxima entre objetivos disparadores (métrica destacada para el ISP).
    trig_loss = [d["loss_pct"] for d in stats.values() if d["trigger"]]
    entry = {
        "dir": base.name,
        "start": ev.start_iso,
        "duration_s": round(ev.duration_s, 1),
        "cause": ev.cause,
        "max_trigger_loss_pct": max(trig_loss) if trig_loss else 0.0,
        "stats": stats,
    }
    with index.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
