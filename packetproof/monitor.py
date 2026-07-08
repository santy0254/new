"""Bucle principal de monitoreo, buffer rodante y detección de eventos."""

from __future__ import annotations

import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .config import Config
from .models import Event, Sample
from .probe import ping

log = logging.getLogger("packetproof")


class Monitor:
    """Corre indefinidamente, sondea objetivos y detecta eventos.

    Mantiene un buffer rodante con las muestras recientes para capturar el
    contexto previo al evento. Cuando termina un evento (tras recuperarse
    ``post_event_seconds``) invoca ``on_event`` con el objeto :class:`Event`.
    """

    def __init__(self, cfg: Config, on_event: Callable[[Event], None]):
        self.cfg = cfg
        self.on_event = on_event
        self._pre_buffer: deque[Sample] = deque(maxlen=cfg.pre_samples)
        self._executor = ThreadPoolExecutor(max_workers=max(2, len(cfg.targets)))
        self._stop = False

        self._in_event = False
        self._event: Event | None = None
        self._good_streak = 0

    def stop(self) -> None:
        self._stop = True

    def _probe_all(self) -> Sample:
        """Sondea todos los objetivos en paralelo (una vuelta)."""
        futures = [
            self._executor.submit(
                ping, t.host, t.label, t.trigger, self.cfg.probe_timeout_ms
            )
            for t in self.cfg.targets
        ]
        results = [f.result() for f in futures]
        return Sample(ts=time.time(), results=results)

    def _classify(self, sample: Sample) -> tuple[bool, str]:
        """Devuelve (es_malo, causa) para una muestra según objetivos disparadores."""
        loss = False
        latency = False
        thr = self.cfg.latency_threshold_ms
        for r in sample.results:
            if not r.trigger:
                continue
            if not r.success:
                loss = True
            elif r.rtt_ms is not None and r.rtt_ms > thr:
                latency = True
        cause = "+".join([c for c, f in (("loss", loss), ("latency", latency)) if f])
        return (loss or latency), cause

    def _handle(self, sample: Sample) -> None:
        bad, cause = self._classify(sample)

        if not self._in_event:
            if bad:
                # Arranca un evento: fotografía el contexto previo del buffer.
                self._in_event = True
                self._event = Event(
                    start_ts=sample.ts,
                    cause=cause,
                    pre=list(self._pre_buffer),
                    samples=[sample],
                )
                self._good_streak = 0
                log.warning("Evento detectado (%s) a las %s", cause, sample.iso)
            else:
                self._pre_buffer.append(sample)
            return

        # Dentro de un evento
        assert self._event is not None
        self._event.samples.append(sample)
        self._pre_buffer.append(sample)  # mantener buffer al día para el próximo evento

        if bad:
            self._good_streak = 0
            if cause and cause not in self._event.cause:
                self._event.cause = "+".join(sorted(set(self._event.cause.split("+")) | set(cause.split("+"))))
        else:
            self._good_streak += 1

        elapsed = sample.ts - self._event.start_ts
        recovered = self._good_streak >= self.cfg.recovery_samples
        too_long = elapsed >= self.cfg.max_event_seconds

        if recovered or too_long:
            self._finalize(reason="recuperado" if recovered else "límite de duración")

    def _finalize(self, reason: str) -> None:
        assert self._event is not None
        ev = self._event
        # El fin del evento es cuando empezó la racha buena (última muestra mala).
        ev.end_ts = ev.samples[-1].ts - (self._good_streak * self.cfg.interval_seconds)
        log.warning(
            "Evento finalizado (%s): duración %.1fs, %d muestras",
            reason, ev.duration_s, len(ev.window),
        )
        self._in_event = False
        self._event = None
        self._good_streak = 0
        try:
            self.on_event(ev)
        except Exception:  # no dejar que un fallo de reporte tumbe el monitor
            log.exception("Error al procesar el evento")

    def run(self) -> None:
        """Bucle principal. Bloquea hasta ``stop()``."""
        interval = self.cfg.interval_seconds
        log.info(
            "Monitoreando %d objetivos cada %.1fs (Ctrl+C para salir)",
            len(self.cfg.targets), interval,
        )
        try:
            while not self._stop:
                start = time.monotonic()
                sample = self._probe_all()
                self._handle(sample)
                # Dormir el resto del intervalo (bajo consumo, sin busy-wait).
                drift = time.monotonic() - start
                sleep_for = interval - drift
                if sleep_for > 0:
                    time.sleep(sleep_for)
        finally:
            self._executor.shutdown(wait=False)
