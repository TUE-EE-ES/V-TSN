import threading
import time
import logging
import urllib.request
import json

logger = logging.getLogger(__name__)

class DashboardReporter:
    def __init__(self, node_id: str, role: str, ip: str,
                 dashboard_url: str, interval_s: float = 2.0):
        self.node_id = node_id
        self.role = role
        self.ip = ip
        self.url = dashboard_url.rstrip("/") + "/api/report"
        self.interval_s = interval_s
        self.offset_ms = 0.0
        self._lock = threading.Lock()
        self._running = False

    def update_offset(self, offset_ms: float):
        with self._lock:
            self.offset_ms = offset_ms

    def start(self):
        self._running = True
        threading.Thread(target=self._run, daemon=True,
                         name=f"reporter-{self.node_id}").start()
        logger.info(f"[{self.node_id}] Dashboard reporter -> {self.url}")

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            try:
                with self._lock:
                    offset = self.offset_ms
                payload = json.dumps({
                    "node_id":   self.node_id,
                    "role":      self.role,
                    "ip":        self.ip,
                    "offset_ms": offset
                }).encode()
                req = urllib.request.Request(
                    self.url, data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                urllib.request.urlopen(req, timeout=2)
            except Exception as e:
                logger.debug(f"[{self.node_id}] Reporter error: {e}")
            time.sleep(self.interval_s)
