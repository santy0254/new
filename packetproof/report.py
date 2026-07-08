"""Generación de gráficos por evento y reporte HTML agregado.

Los gráficos siguen una paleta validada para daltonismo (azul / naranja /
violeta / aqua) con identidad reforzada por etiquetas directas, y un panel
inferior de "pérdida" que muestra de un vistazo qué tramo falló.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .models import Event

log = logging.getLogger("packetproof")

# Paleta categórica validada (orden fijo, seguro para daltonismo).
_SERIES = ["#2a78d6", "#eb6834", "#4a3aa7", "#1baf7a", "#e87ba4", "#c98500"]
_LAN = "#898781"          # gris para objetivos que no disparan (LAN)
_CRIT = "#d03b3b"         # rojo estado "crítico" para pérdida
_INK = "#0b0b0b"
_MUTED = "#898781"
_GRID = "#e1e0d9"
_SURFACE = "#fcfcfb"
_WARN_BAND = "#fab219"


def _color_for(idx: int, trigger: bool) -> str:
    if not trigger:
        return _LAN
    return _SERIES[idx % len(_SERIES)]


def render_event_chart(cfg: Config, ev: Event, out_path: Path) -> bool:
    """Dibuja el gráfico del evento. Devuelve False si matplotlib no está."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except Exception:  # matplotlib es opcional
        log.warning("matplotlib no disponible: se omite el gráfico de %s", out_path.parent.name)
        return False

    window = ev.window
    if not window:
        return False

    hosts = [(r.host, r.label, r.trigger) for r in window[0].results]
    start = ev.start_ts
    end = ev.end_ts or window[-1].ts

    times = [datetime.fromtimestamp(s.ts, tz=timezone.utc) for s in window]

    fig = plt.figure(figsize=(11, 6.2), dpi=130)
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.12)
    ax = fig.add_subplot(gs[0])
    ax_loss = fig.add_subplot(gs[1], sharex=ax)

    for a in (ax, ax_loss):
        a.set_facecolor(_SURFACE)
        for spine in ("top", "right"):
            a.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            a.spines[spine].set_color(_GRID)
        a.tick_params(colors=_MUTED, labelsize=9)
    fig.patch.set_facecolor(_SURFACE)

    # Banda del núcleo del evento (inicio -> fin).
    band0 = datetime.fromtimestamp(start, tz=timezone.utc)
    band1 = datetime.fromtimestamp(end, tz=timezone.utc)
    for a in (ax, ax_loss):
        a.axvspan(band0, band1, color=_WARN_BAND, alpha=0.10, lw=0)

    # --- Panel superior: latencia ---
    for i, (host, label, trigger) in enumerate(hosts):
        color = _color_for(i, trigger)
        ys = []
        for s in window:
            r = next((x for x in s.results if x.host == host), None)
            ys.append(r.rtt_ms if (r and r.rtt_ms is not None) else float("nan"))
        ax.plot(times, ys, color=color, lw=2.0, label=label,
                zorder=3 if trigger else 2, alpha=0.95 if trigger else 0.7)

    ax.axhline(cfg.latency_threshold_ms, color=_CRIT, lw=1.0, ls="--", alpha=0.6,
               zorder=1)
    ax.annotate(f"umbral {cfg.latency_threshold_ms:.0f} ms",
                (times[0], cfg.latency_threshold_ms), color=_CRIT, fontsize=7.5,
                xytext=(2, 3), textcoords="offset points")
    ax.set_ylabel("RTT (ms)", color=_INK, fontsize=10)
    ax.grid(True, axis="y", color=_GRID, lw=0.8)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=len(hosts))

    started = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ax.set_title(
        f"Evento de red — {started}  ·  causa: {ev.cause}  ·  duración {ev.duration_s:.0f}s",
        color=_INK, fontsize=12, weight="bold", loc="left", pad=10,
    )

    # --- Panel inferior: pérdida por objetivo (rojo = paquete perdido) ---
    lanes = list(enumerate(hosts))
    for lane, (host, label, trigger) in lanes:
        y = len(lanes) - 1 - lane
        lost_t = [t for t, s in zip(times, window)
                  if (r := next((x for x in s.results if x.host == host), None)) and not r.success]
        ok_t = [t for t, s in zip(times, window)
                if (r := next((x for x in s.results if x.host == host), None)) and r.success]
        ax_loss.scatter(ok_t, [y] * len(ok_t), s=14, marker="s",
                        color=_color_for(lane, trigger), alpha=0.35, lw=0)
        ax_loss.scatter(lost_t, [y] * len(lost_t), s=26, marker="x",
                        color=_CRIT, lw=1.6, zorder=4)
    ax_loss.set_yticks([len(lanes) - 1 - l for l, _ in lanes])
    ax_loss.set_yticklabels([h[1] for h in hosts], fontsize=7.5, color=_INK)
    ax_loss.set_ylim(-0.6, len(lanes) - 0.4)
    ax_loss.set_ylabel("pérdida", color=_MUTED, fontsize=9)
    ax_loss.grid(True, axis="x", color=_GRID, lw=0.6)
    ax_loss.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate(rotation=0, ha="center")

    fig.savefig(out_path, bbox_inches="tight", facecolor=_SURFACE)
    plt.close(fig)
    return True


def build_report(cfg: Config) -> Path | None:
    """Genera un reporte HTML agregado a partir del índice de eventos."""
    events_dir = Path(cfg.data_dir) / "events"
    index = events_dir / "index.jsonl"
    if not index.exists():
        log.info("Todavía no hay eventos registrados.")
        return None

    entries = [json.loads(l) for l in index.read_text().splitlines() if l.strip()]
    entries.sort(key=lambda e: e["start"], reverse=True)

    out = Path(cfg.data_dir) / "report.html"
    out.write_text(_render_html(cfg, entries), encoding="utf-8")
    log.info("Reporte generado: %s (%d eventos)", out, len(entries))
    return out


def _render_html(cfg: Config, entries: list[dict]) -> str:
    total = len(entries)
    worst = max((e["max_trigger_loss_pct"] for e in entries), default=0.0)
    total_downtime = sum(e["duration_s"] for e in entries)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    rows = []
    for e in entries:
        chart_rel = f"events/{e['dir']}/chart.png"
        loss = e["max_trigger_loss_pct"]
        sev = "critical" if loss >= 50 else "serious" if loss >= 10 else "warning"
        per_host = "".join(
            f"<tr><td>{'🌐' if d['trigger'] else '🏠'} {html.escape(d['label'])}</td>"
            f"<td class='num'>{d['loss_pct']}%</td>"
            f"<td class='num'>{d['lost']}/{d['sent']}</td>"
            f"<td class='num'>{d['avg_rtt_ms'] if d['avg_rtt_ms'] is not None else '—'}</td>"
            f"<td class='num'>{d['max_rtt_ms'] if d['max_rtt_ms'] is not None else '—'}</td></tr>"
            for d in e["stats"].values()
        )
        rows.append(f"""
        <section class="event">
          <div class="event-head">
            <div>
              <span class="badge {sev}">{loss:.0f}% pérdida</span>
              <h3>{html.escape(e['start'])}</h3>
              <p class="meta">Causa: <b>{html.escape(e['cause'])}</b> · Duración: <b>{e['duration_s']:.0f} s</b></p>
            </div>
          </div>
          <img src="{chart_rel}" alt="Gráfico del evento" loading="lazy">
          <table class="detail">
            <thead><tr><th>Objetivo</th><th>Pérdida</th><th>Perdidos</th><th>RTT prom (ms)</th><th>RTT máx (ms)</th></tr></thead>
            <tbody>{per_host}</tbody>
          </table>
        </section>""")

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PacketProof — Reporte de pérdida de paquetes</title>
<style>
  :root {{
    --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --muted:#52514e;
    --hair:#e1e0d9; --blue:#2a78d6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --muted:#c3c2b7; --hair:#2c2c2a; --blue:#3987e5; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--plane); color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.5; }}
  header {{ padding:32px 24px; border-bottom:1px solid var(--hair); }}
  h1 {{ margin:0 0 4px; font-size:22px; }}
  .sub {{ color:var(--muted); font-size:14px; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:24px; }}
  .kpis {{ display:flex; flex-wrap:wrap; gap:16px; margin:24px 0; }}
  .kpi {{ flex:1 1 160px; background:var(--surface); border:1px solid var(--hair);
    border-radius:12px; padding:16px 18px; }}
  .kpi .v {{ font-size:28px; font-weight:700; }}
  .kpi .l {{ color:var(--muted); font-size:13px; }}
  .event {{ background:var(--surface); border:1px solid var(--hair);
    border-radius:14px; padding:18px; margin:20px 0; }}
  .event img {{ width:100%; height:auto; border-radius:8px; margin:12px 0; }}
  .event h3 {{ margin:6px 0 2px; font-size:16px; }}
  .meta {{ color:var(--muted); font-size:13px; margin:0; }}
  .badge {{ display:inline-block; font-size:12px; font-weight:700; color:#fff;
    padding:3px 10px; border-radius:999px; }}
  .badge.warning {{ background:#c98500; }} .badge.serious {{ background:#ec835a; }}
  .badge.critical {{ background:#d03b3b; }}
  table.detail {{ width:100%; border-collapse:collapse; font-size:13px; overflow-x:auto; }}
  table.detail th, table.detail td {{ text-align:left; padding:6px 10px;
    border-bottom:1px solid var(--hair); }}
  td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  footer {{ color:var(--muted); font-size:12px; padding:24px; text-align:center; }}
</style></head>
<body>
  <header><div class="wrap" style="padding-top:0;padding-bottom:0">
    <h1>PacketProof — Evidencia de pérdida de paquetes</h1>
    <div class="sub">Generado {generated} · umbral de latencia {cfg.latency_threshold_ms:.0f} ms ·
      ventana de contexto ±{cfg.pre_event_seconds}s / {cfg.post_event_seconds}s</div>
  </div></header>
  <div class="wrap">
    <div class="kpis">
      <div class="kpi"><div class="v">{total}</div><div class="l">Eventos detectados</div></div>
      <div class="kpi"><div class="v">{worst:.0f}%</div><div class="l">Pérdida máxima (Internet)</div></div>
      <div class="kpi"><div class="v">{total_downtime:.0f}s</div><div class="l">Tiempo degradado acumulado</div></div>
    </div>
    <p class="sub">🌐 = objetivo en Internet (dispara eventos) · 🏠 = router/LAN (referencia).
      Pérdida en Internet con el router sano indica un problema del lado del ISP.</p>
    {''.join(rows) if rows else '<p>No hay eventos registrados todavía.</p>'}
  </div>
  <footer>PacketProof v{__import__('packetproof').__version__} · datos crudos en <code>events/&lt;fecha&gt;/</code></footer>
</body></html>"""
