import argparse
import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nodes.master import GrandMaster
from dashboard.state import network_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Virtual TSN Grand Master")
    parser.add_argument("--config", default="config_master.json")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not os.path.exists(args.config):
        default = {
            "role": "master",
            "node_id": "gm-1",
            "bind_ip": "0.0.0.0",
            "port": 319,
            "sync_interval_ms": 125,
            "pdelay_interval_ms": 1000,
            "public_ip": "YOUR_GM_PUBLIC_IP",
            "dashboard_url": "http://YOUR_SWITCH_IP:5000",
            "peers": [
                {"node_id": "switch-1", "ip": "YOUR_SWITCH_IP", "port": 319}
            ]
        }
        with open(args.config, "w") as f:
            json.dump(default, f, indent=2)
        logger.info(f"Created {args.config} — edit IPs then re-run.")
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    logger.info(f"Starting Grand Master: {config['node_id']}")
    logger.info(f"Peers: {[p['node_id'] for p in config.get('peers', [])]}")

    network_state.update_node(
        node_id=config["node_id"],
        role="master",
        offset_ms=0.0,
        ip=config.get("public_ip", "?")
    )

    gm = GrandMaster(config)
    gm.start()
    gm.run_forever()

if __name__ == "__main__":
    main()
