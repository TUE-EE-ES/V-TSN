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
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "role": "slave",
    "node_id": "slave-1",
    "bind_ip": "0.0.0.0",
    "port": 319,
    "pdelay_interval_ms": 1000,
    "probe_interval_ms": 2000,
    "public_ip": "YOUR_ENDPOINT_IP",
    "dashboard_url": "http://YOUR_SWITCH_IP:5000",
    "peers": [
        {"node_id": "switch-1", "ip": "YOUR_SWITCH_IP", "port": 319}
    ],
    "gm_peer": {
        "node_id": "gm-1",
        "ip": "YOUR_GM_IP",
        "port": 319
    },
    "endpoint": {
        "switch_ip": "YOUR_SWITCH_IP",
        "switch_tunnel_port": 4789,
        "tunnel_port": 4789,
        "tap_name": "tsn0",
        "tap_ip": "10.100.0.2",
        "tap_netmask": "255.255.255.0"
    }
}

def main():
    parser = argparse.ArgumentParser(description="Virtual TSN Endpoint")
    parser.add_argument("--config", default="config_endpoint.json")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not os.path.exists(args.config):
        with open(args.config, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        logger.info("Created %s — edit IPs then re-run.", args.config)
        sys.exit(1)

    with open(args.config) as f:
        config = json.load(f)

    ep_cfg = config.get("endpoint")
    logger.info("Starting Endpoint: %s", config["node_id"])
    logger.info("  gPTP port    : %d", config.get("port", 319))
    logger.info("  Tunnel port  : %d", ep_cfg.get("tunnel_port", 4789) if ep_cfg else "N/A")
    logger.info("  Switch       : %s", (config.get("peers") or [{}])[0].get("ip"))
    logger.info("  GM           : %s", config.get("gm_peer", {}).get("ip"))
    logger.info("  TAP          : %s (%s)",
                ep_cfg.get("tap_name", "tsn0") if ep_cfg else "disabled",
                ep_cfg.get("tap_ip", "") if ep_cfg else "")

    slave = Slave(config)
    slave.start()

    try:
        report_interval = 10
        while slave.running:
            time.sleep(report_interval)
            r = slave.accuracy.report()
            if r:
                print(f"\n{'='*52}")
                print(f"  Accuracy Report — {config['node_id']}")
                print(f"{'='*52}")
                print(f"  Samples    : {r['count']}")
                print(f"  Mean offset: {r['mean_ms']:+.3f} ms")
                print(f"  Std dev    : {r['std_ms']:.3f} ms")
                print(f"  P95        : {r['p95_ms']:.3f} ms")
                print(f"  P99        : {r['p99_ms']:.3f} ms")
                print(f"  Path delay : {r['mean_delay_ms']:.3f} ms (avg)")
                if slave.get_endpoint():
                    ep_stats = slave.get_endpoint().get_stats()
                    print(f"  EP TX pkts : {ep_stats['tx_packets']}")
                    print(f"  EP RX pkts : {ep_stats['rx_packets']}")
                    print(f"  EP mode    : {'TAP' if slave.get_endpoint().tap_mode else 'fallback'}")
                print(f"{'='*52}\n")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        slave.stop()

if __name__ == "__main__":
    main()
