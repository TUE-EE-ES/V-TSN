import argparse
import json
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nodes.slave import Slave

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Virtual TSN Slave")
    parser.add_argument("--config", default="config_slave.json")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--report-interval", type=int, default=10)
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not os.path.exists(args.config):
        default = {
            "role": "slave",
            "node_id": "slave-1",
            "bind_ip": "0.0.0.0",
            "port": 319,
            "pdelay_interval_ms": 1000,
            "probe_interval_ms": 2000,
            "public_ip": "YOUR_SLAVE_PUBLIC_IP",
            "dashboard_url": "http://YOUR_SWITCH_IP:5000",
            "peers": [
                {"node_id": "switch-1", "ip": "YOUR_SWITCH_IP", "port": 319}
            ],
            "gm_peer": {
                "node_id": "gm-1",
                "ip": "YOUR_GM_IP",
                "port": 319
            }
        }
        with open(args.config, "w") as f:
            json.dump(default, f, indent=2)
        logger.info(f"Created {args.config} — edit IPs then re-run.")
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    logger.info(f"Starting Slave: {config['node_id']}")
    logger.info(f"Switch: {[p['node_id'] for p in config.get('peers', [])]}")
    logger.info(f"GM:     {config.get('gm_peer', {}).get('node_id')}")

    slave = Slave(config)
    slave.start()

    try:
        while slave.running:
            time.sleep(args.report_interval)
            r = slave.accuracy.report()
            if r:
                print("\n" + "="*50)
                print(f"  Accuracy Report — {config['node_id']}")
                print("="*50)
                print(f"  Samples:     {r['count']}")
                print(f"  Mean offset: {r['mean_ms']:+.3f} ms")
                print(f"  Std dev:     {r['std_ms']:.3f} ms")
                print(f"  P95:         {r['p95_ms']:.3f} ms")
                print(f"  P99:         {r['p99_ms']:.3f} ms")
                print(f"  Max:         {r['max_ms']:.3f} ms")
                print(f"  Path delay:  {r['mean_delay_ms']:.3f} ms (avg)")
                print("="*50 + "\n")
            else:
                logger.info(f"[{config['node_id']}] Waiting for accuracy data...")
    except KeyboardInterrupt:
        logger.info(f"Shutting down...")
        slave.stop()

if __name__ == "__main__":
    main()
