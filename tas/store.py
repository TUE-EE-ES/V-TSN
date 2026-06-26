import json
import os
import threading
import logging
from typing import Dict, List, Callable
from .engine import TASConfig
from .cbs import CBSConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "tas_config.json"

class TASConfigStore:

    def __init__(self, port_ids: List[str],
                 path: str = DEFAULT_CONFIG_PATH):
        self.path      = path
        self.port_ids  = port_ids
        self._lock     = threading.Lock()
        self._tas: Dict[str, TASConfig] = {}
        self._cbs: Dict[str, CBSConfig] = {}
        self._listeners: List[Callable] = []
        self._load(port_ids)

    def _load(self, port_ids: List[str]):
        saved = {}
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    saved = json.load(f)
                logger.info("[Store] Loaded from %s", self.path)
            except Exception as e:
                logger.warning("[Store] Load error: %s", e)

        for pid in port_ids:
            port_data = saved.get(pid, {})

            try:
                tas_data = port_data.get("tas", {})
                cfg = TASConfig.from_dict(tas_data) if tas_data else TASConfig()
                ok, msg = cfg.validate()
                self._tas[pid] = cfg if ok else TASConfig()
                if not ok:
                    logger.warning("[Store] Invalid TAS for %s: %s", pid, msg)
            except Exception as e:
                logger.warning("[Store] TAS parse error for %s: %s", pid, e)
                self._tas[pid] = TASConfig()

            try:
                cbs_data = port_data.get("cbs", {})
                self._cbs[pid] = CBSConfig.from_dict(cbs_data) if cbs_data else CBSConfig()
            except Exception as e:
                logger.warning("[Store] CBS parse error for %s: %s", pid, e)
                self._cbs[pid] = CBSConfig()

            logger.info("[Store] Port %s ready (TAS=%s, CBS=%s)",
                        pid,
                        "custom" if port_data.get("tas") else "default",
                        "custom" if port_data.get("cbs") else "default")

    def get_tas(self, port_id: str) -> TASConfig:
        with self._lock:
            return self._tas.get(port_id, TASConfig())

    def get_cbs(self, port_id: str) -> CBSConfig:
        with self._lock:
            return self._cbs.get(port_id, CBSConfig())

    def get_all_tas(self) -> Dict[str, TASConfig]:
        with self._lock:
            return dict(self._tas)

    def get_all_cbs(self) -> Dict[str, CBSConfig]:
        with self._lock:
            return dict(self._cbs)

    def get(self, port_id: str) -> TASConfig:
        return self.get_tas(port_id)

    def update_tas(self, port_id: str, new_config: TASConfig):
        ok, msg = new_config.validate()
        if not ok:
            return False, msg
        with self._lock:
            self._tas[port_id] = new_config
            self._save()
        self._notify(port_id)
        return True, "ok"

    def update_cbs(self, port_id: str, new_config: CBSConfig):
        ok, msg = new_config.validate()
        if not ok:
            return False, msg
        with self._lock:
            self._cbs[port_id] = new_config
            self._save()
        self._notify(port_id)
        return True, "ok"

    def update(self, port_id: str, new_config: TASConfig):
        return self.update_tas(port_id, new_config)

    def reset_tas(self, port_id: str):
        return self.update_tas(port_id, TASConfig())

    def reset_cbs(self, port_id: str):
        return self.update_cbs(port_id, CBSConfig())

    def reset_all(self):
        results = {}
        for pid in self.port_ids:
            ok1, m1 = self.update_tas(pid, TASConfig())
            ok2, m2 = self.update_cbs(pid, CBSConfig())
            results[pid] = {"tas": {"ok": ok1, "msg": m1},
                            "cbs": {"ok": ok2, "msg": m2}}
        return results

    def _save(self):
        try:
            data = {}
            for pid in self.port_ids:
                data[pid] = {
                    "tas": self._tas[pid].to_dict(),
                    "cbs": self._cbs[pid].to_dict(),
                }
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("[Store] Save error: %s", e)

    def add_listener(self, fn: Callable):
        self._listeners.append(fn)

    def _notify(self, port_id: str):
        tas = self._tas.get(port_id, TASConfig())
        cbs = self._cbs.get(port_id, CBSConfig())
        for fn in self._listeners:
            try:
                fn(port_id, tas, cbs)
            except Exception as e:
                logger.warning("[Store] Listener error: %s", e)
