"""Interfaz de línea de comandos de PacketProof."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .models import Event
from .monitor import Monitor
from .probe import ping
from .report import build_report, render_event_chart
from .storage import save_event

log = logging.getLogger("packetproof")


def _setup_logging(data_dir: str, verbose: bool) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler(sys.stderr),
                logging.FileHandler(Path(data_dir) / "packetproof.log", encoding="utf-8")]
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def _on_event(cfg: Config) -> "callable":
    def handler(ev: Event) -> None:
        base = save_event(cfg, ev)
        render_event_chart(cfg, ev, base / "chart.png")
        build_report(cfg)
    return handler


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    monitor = Monitor(cfg, _on_event(cfg))

    def _sigterm(signum, frame):
        log.info("Señal recibida, cerrando…")
        monitor.stop()

    signal.signal(signal.SIGINT, _sigterm)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sigterm)

    monitor.run()
    build_report(cfg)
    return 0


def cmd_test(cfg: Config, args: argparse.Namespace) -> int:
    print(f"PacketProof v{__version__} — prueba de objetivos\n")
    for t in cfg.targets:
        r = ping(t.host, t.label, t.trigger, cfg.probe_timeout_ms)
        flag = "🌐" if t.trigger else "🏠"
        status = f"{r.rtt_ms:.1f} ms" if r.success else "SIN RESPUESTA"
        print(f"  {flag} {t.label:<28} {t.host:<16} {status}")
    return 0


def cmd_report(cfg: Config, args: argparse.Namespace) -> int:
    out = build_report(cfg)
    print(f"Reporte: {out}" if out else "No hay eventos para reportar todavía.")
    return 0


def cmd_simulate(cfg: Config, args: argparse.Namespace) -> int:
    """Genera un evento sintético para probar gráficos y reporte sin esperar."""
    import random
    from .models import ProbeResult, Sample

    now = time.time()
    interval = cfg.interval_seconds
    samples: list[Sample] = []
    n_pre = cfg.pre_samples
    n_event = 12
    n_post = cfg.recovery_samples
    total = n_pre + n_event + n_post

    for i in range(total):
        ts = now - (total - i) * interval
        in_event = n_pre <= i < n_pre + n_event
        results = []
        for j, t in enumerate(cfg.targets):
            if in_event and t.trigger:
                lost = random.random() < 0.6
                rtt = None if lost else random.uniform(180, 500)
            else:
                lost = random.random() < 0.02
                rtt = None if lost else random.uniform(8, 35) + (5 if not t.trigger else 15)
            results.append(ProbeResult(t.host, t.label, t.trigger, rtt is not None, rtt))
        samples.append(Sample(ts=ts, results=results))

    ev = Event(
        start_ts=samples[n_pre].ts,
        cause="loss+latency",
        pre=samples[:n_pre],
        samples=samples[n_pre:],
        end_ts=samples[n_pre + n_event].ts,
    )
    base = save_event(cfg, ev)
    render_event_chart(cfg, ev, base / "chart.png")
    build_report(cfg)
    print(f"Evento simulado guardado en {base}")
    print(f"Reporte: {Path(cfg.data_dir) / 'report.html'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="packetproof",
        description="Monitor de pérdida de paquetes para documentar problemas del ISP.",
    )
    p.add_argument("--version", action="version", version=f"PacketProof {__version__}")
    p.add_argument("-c", "--config", help="Ruta al archivo de configuración TOML")
    p.add_argument("-d", "--data-dir", help="Carpeta de datos (sobreescribe config)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("run", help="Monitorear indefinidamente (por defecto)")
    sub.add_parser("test", help="Probar objetivos una vez y salir")
    sub.add_parser("report", help="Regenerar el reporte HTML")
    sub.add_parser("simulate", help="Generar un evento sintético de demostración")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 2
    if args.data_dir:
        cfg.data_dir = args.data_dir

    _setup_logging(cfg.data_dir, args.verbose)

    command = args.command or "run"
    dispatch = {
        "run": cmd_run, "test": cmd_test,
        "report": cmd_report, "simulate": cmd_simulate,
    }
    return dispatch[command](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
