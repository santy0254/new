"""Pruebas unitarias de PacketProof."""

import time

import pytest

from packetproof.config import Config, Target
from packetproof.models import Event, ProbeResult, Sample
from packetproof.monitor import Monitor
from packetproof.probe import _parse_rtt


# --- Parseo de RTT (multiplataforma / multi-idioma) ---

@pytest.mark.parametrize("out,expected", [
    ("64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.3 ms", 12.3),      # Linux
    ("Reply from 8.8.8.8: bytes=32 time=24ms TTL=115", 24.0),             # Windows EN
    ("Respuesta desde 8.8.8.8: bytes=32 tiempo=8ms TTL=115", 8.0),        # Windows ES
    ("Reply from 8.8.8.8: bytes=32 time<1ms TTL=115", 1.0),              # sub-ms
    ("time=1,5 ms", 1.5),                                                 # coma decimal
    ("Request timed out.", None),                                         # pérdida
    ("Tiempo de espera agotado para esta solicitud.", None),             # pérdida ES
])
def test_parse_rtt(out, expected):
    assert _parse_rtt(out) == expected


# --- Estadísticas del evento ---

def _mk_sample(ts, specs):
    """specs: lista de (host, trigger, rtt|None)."""
    results = [
        ProbeResult(host=h, label=h, trigger=trig, success=rtt is not None, rtt_ms=rtt)
        for h, trig, rtt in specs
    ]
    return Sample(ts=ts, results=results)


def test_event_stats_loss_pct():
    samples = [
        _mk_sample(1000 + i, [("8.8.8.8", True, None if i < 3 else 20.0)])
        for i in range(5)
    ]
    ev = Event(start_ts=1000, cause="loss", samples=samples, end_ts=1005)
    stats = ev.stats()["8.8.8.8"]
    assert stats["sent"] == 5
    assert stats["lost"] == 3
    assert stats["loss_pct"] == 60.0
    assert stats["avg_rtt_ms"] == 20.0


# --- Máquina de estados del monitor ---

def _cfg():
    c = Config(
        interval_seconds=1.0, pre_event_seconds=3, post_event_seconds=2,
        latency_threshold_ms=300, max_event_seconds=100,
    )
    c.targets = [
        Target("Gateway", "192.168.0.1", trigger=False),
        Target("Internet", "8.8.8.8", trigger=True),
    ]
    return c


def test_monitor_detects_and_finalizes_event():
    cfg = _cfg()
    captured = []
    mon = Monitor(cfg, captured.append)
    base = time.time()

    def feed(offset, gw_rtt, net_rtt):
        s = _mk_sample(base + offset, [
            ("192.168.0.1", False, gw_rtt),
            ("8.8.8.8", True, net_rtt),
        ])
        mon._handle(s)

    # 3 muestras buenas (llenan el buffer previo)
    for i in range(3):
        feed(i, 5.0, 20.0)
    assert not mon._in_event

    # pérdida en Internet -> arranca evento
    feed(3, 5.0, None)
    assert mon._in_event

    # sigue mala una vez más
    feed(4, 5.0, None)
    # 2 muestras buenas -> recuperación (post_event_seconds=2)
    feed(5, 5.0, 22.0)
    assert mon._in_event  # todavía no alcanzó la racha
    feed(6, 5.0, 22.0)
    assert not mon._in_event  # finalizó

    assert len(captured) == 1
    ev = captured[0]
    assert "loss" in ev.cause
    # La ventana incluye contexto previo + evento + post
    assert len(ev.pre) == 3
    assert len(ev.window) >= 6


def test_gateway_loss_does_not_trigger():
    cfg = _cfg()
    captured = []
    mon = Monitor(cfg, captured.append)
    base = time.time()
    # El gateway se pierde pero Internet responde: NO debe disparar evento.
    for i in range(4):
        mon._handle(_mk_sample(base + i, [
            ("192.168.0.1", False, None),
            ("8.8.8.8", True, 20.0),
        ]))
    assert not mon._in_event
    assert captured == []


def test_latency_spike_triggers():
    cfg = _cfg()
    captured = []
    mon = Monitor(cfg, captured.append)
    base = time.time()
    mon._handle(_mk_sample(base, [("8.8.8.8", True, 20.0)]))
    bad, cause = mon._classify(_mk_sample(base + 1, [("8.8.8.8", True, 800.0)]))
    assert bad and cause == "latency"
