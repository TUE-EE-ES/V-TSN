import argparse
import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nodes.switch import VirtualSwitch
from dashboard.state import network_state
from core.drift_logger import DriftLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Virtual TSN Switch")
    parser.add_argument("--config",         default="config_switch.json")
    parser.add_argument("--debug",          action="store_true")
    parser.add_argument("--drift-interval", type=float, default=60.0,
                        help="Seconds between Excel writes (default: 60)")
    parser.add_argument("--drift-dir",      default="/root",
                        help="Directory to save drift Excel files")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not os.path.exists(args.config):
        default = {
            "role": "switch", "node_id": "switch-1",
            "bind_ip": "0.0.0.0", "port": 319,
            "dashboard_port": 5000,
            "tas_config_path": "tas_config.json",
            "pdelay_interval_ms": 1000,
            "upstream_peer":    {"node_id":"gm-1","ip":"YOUR_GM_IP","port":319},
            "downstream_peers": [
                {"node_id":"slave-1","ip":"YOUR_SLAVE1_IP","port":319,"tunnel_port":4789},
                {"node_id":"slave-2","ip":"YOUR_SLAVE2_IP","port":319,"tunnel_port":4789},
            ]
        }
        with open(args.config, "w") as f:
            json.dump(default, f, indent=2)
        logger.info("Created %s — edit IPs then re-run.", args.config)
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    logger.info("Starting Virtual Switch: %s", config["node_id"])
    logger.info("Upstream:  %s", config.get("upstream_peer", {}).get("node_id"))
    logger.info("Downstream: %s",
                [p["node_id"] for p in config.get("downstream_peers", [])])
    logger.info("Dashboard: http://0.0.0.0:%d", config.get("dashboard_port", 5000))

    drift = DriftLogger(
        output_dir=args.drift_dir,
        interval_s=args.drift_interval
    )
    drift.start()
    network_state.set_drift_logger(drift)
    logger.info("Drift logger: writing every %ds to %s/",
                args.drift_interval, args.drift_dir)

    sw = VirtualSwitch(config)
    sw.start()
    sw.run_forever()

if __name__ == "__main__":
    main()
