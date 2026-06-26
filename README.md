# Virtual TSN
This repository contains the source code for the paper:

V-TSN: A Software-Defined TSN Overlay for General-Purpose Networks


# 🔬 Reference

If you use this work, please cite:
M. Karimi, M. Nabi, A. Khalaf, A. Nelson, K. Goossens, and T. Basten, "V-TSN: A Software-Defined TSN Overlay for General-Purpose Networks," arXiv.



# 📄 License

This project is licensed under the MIT License. See the LICENSE file for details.

# 📝 Abstract

Time-Sensitive Networking (TSN) extends Ethernet with deterministic communication for time-critical applications such as industrial automation, in-vehicle networks, and cyber-physical systems. However, realizing TSN behavior without dedicated hardware is difficult. During design and validation, offline simulation cannot run application software at real-time speed when costly specialized TSN hardware is not (yet) available. At deployment time, many systems run on general-purpose and cloud networks with no native TSN support, where provisioning full TSN hardware is unnecessary or impractical for applications that tolerate relaxed timing. In this paper, we introduce Virtual Time-Sensitive Networking (V-TSN), a software-defined overlay that realizes gPTP-based synchronization and TSN traffic shaping over general-purpose, non-deterministic networks without specialized hardware. V-TSN runs in real time alongside the unmodified application stack, serving both as a development-time emulation tool and as a cost-efficient deployment option where relaxed timing is acceptable. In a cloud-based deployment, V-TSN achieves an average clock offset below 200 microseconds, it isolates time-critical traffic through a virtual Time-Aware Shaper (TAS), and it enforces per-class bandwidth reservations through a virtual Credit-Based Shaper (CBS).

# 📬 Contact Us

For questions, comments, or collaborations, feel free to contact us:
Mohammadparsa Karimi — m.karimi@tue.nl

# Acknowledgments

This work has received funding from the European Chips Joint Undertaking under
Framework Partnership Agreement No 101139789 (HAL4SDV).


# USER GUIDE

---

## Topology

```
   GrandMaster ──gPTP──► Switch ──gPTP + data──► Endpoints (Slaves)
   (clock src)           (TAS + CBS + dashboard)
```

Four node roles:

| Role | Script | What it does |
|---|---|---|
| GrandMaster | `run_master.py` | The reference clock; sends gPTP Sync/Follow-Up |
| Switch | `run_switch.py` | Relays time, forwards data, applies TAS + CBS per port, hosts the dashboard |
| Slave | `run_slave.py` | Synchronizes its clock to the GrandMaster |
| Endpoint | `run_endpoint.py` | Optional application endpoint (TAP/tunnel) |

Network ports used:

- `UDP 319` — gPTP control plane
- `UDP 4789` — data-plane tunnel
- `TCP 5000` — dashboard (switch only)

---

## Repository structure

```
.
├── run_master.py        GrandMaster entry point
├── run_switch.py        Switch entry point (+ dashboard, drift logger)
├── run_slave.py         Slave entry point
├── run_endpoint.py      Application endpoint entry point
├── requirements.txt
│
├── core/                gPTP virtual clock, delay filter, drift logger, dashboard reporter
├── nodes/               Node logic: master, switch, slave, base node
├── protocol/            gPTP messages, peer-delay exchange, tunnel framing
├── tas/                 TAS gate engine, CBS credit shaper, per-port config store
├── dashboard/           Flask web dashboard (state + app + templates)
├── accuracy/            Sync-accuracy metrics
└── endpoint/            Endpoint agent + TAP interface
```

---

## Requirements

- Python 3.8+ (standard library only on the GrandMaster and Slaves)
- The **Switch** additionally needs `flask` (dashboard) and `openpyxl` (drift logging):

```bash
# on the switch machine only
python3 -m pip install -r requirements.txt
# (or, on Debian/Ubuntu without pip:  apt-get install python3-flask python3-openpyxl)
```

If you use a firewall, open the ports on each machine:

```bash
ufw allow 319/udp
ufw allow 4789/udp
ufw allow 5000/tcp   # switch only
```

---

## Running it

Use at least three machines (or three terminals on one host with distinct IPs):
one GrandMaster, one Switch, one or more Slaves.

Each entry point **creates a template config on first run, then exits** so you can
fill in the real IP addresses:

```bash
python3 run_master.py        # writes config_master.json, then edit the IPs
python3 run_switch.py        # writes config_switch.json, then edit the IPs
python3 run_slave.py         # writes config_slave.json,  then edit the IPs
```

Edit the generated JSON files (replace `YOUR_GM_IP`, `YOUR_SLAVE1_IP`, …), then
start the nodes **in this order**:

```bash
# 1) GrandMaster
python3 run_master.py --config config_master.json

# 2) Switch  (drift logs go to --drift-dir; default is /root)
python3 run_switch.py --config config_switch.json --drift-dir .

# 3) Slaves (one per slave machine)
python3 run_slave.py  --config config_slave.json
```

Add `--debug` to any node for verbose logging.

### Config examples

`config_master.json`
```json
{
  "role": "master", "node_id": "gm-1",
  "bind_ip": "0.0.0.0", "port": 319,
  "sync_interval_ms": 125, "pdelay_interval_ms": 1000,
  "public_ip": "GM_PUBLIC_IP",
  "dashboard_url": "http://SWITCH_IP:5000",
  "peers": [{"node_id": "switch-1", "ip": "SWITCH_IP", "port": 319}]
}
```

`config_switch.json`
```json
{
  "role": "switch", "node_id": "switch-1",
  "bind_ip": "0.0.0.0", "port": 319,
  "dashboard_port": 5000,
  "tas_config_path": "tas_config.json",
  "upstream_peer": {"node_id": "gm-1", "ip": "GM_IP", "port": 319},
  "downstream_peers": [
    {"node_id": "slave-1", "ip": "SLAVE1_IP", "port": 319, "tunnel_port": 4789},
    {"node_id": "slave-2", "ip": "SLAVE2_IP", "port": 319, "tunnel_port": 4789}
  ]
}
```

`config_slave.json`
```json
{
  "role": "slave", "node_id": "slave-1",
  "bind_ip": "0.0.0.0", "port": 319,
  "pdelay_interval_ms": 1000, "probe_interval_ms": 2000,
  "public_ip": "SLAVE1_PUBLIC_IP",
  "dashboard_url": "http://SWITCH_IP:5000",
  "peers": [{"node_id": "switch-1", "ip": "SWITCH_IP", "port": 319}],
  "gm_peer": {"node_id": "gm-1", "ip": "GM_IP", "port": 319}
}
```

---

## Dashboard

Once the switch is running, open `http://SWITCH_IP:5000` (default password
`tuetuetue`). It shows each node's clock offset over time and, per egress port,
the live TAS gate states and CBS credit levels. TAS and CBS can also be
configured per port from the dashboard.

---

## TAS / CBS configuration

Per-port shaping is defined in `tas_config.json` (path set by `tas_config_path`
in the switch config), keyed by downstream node id. The switch reads it at
startup, so restart the switch after editing it.

```json
{
  "slave-1": {
    "tas": {
      "enabled": true,
      "cycle_us": 14000,
      "gcl": [
        {"gates": 8, "duration_us": 7000},
        {"gates": 7, "duration_us": 7000}
      ],
      "base_time_ns": 0,
      "port_speed_bps": 1500000
    },
    "cbs": {
      "enabled": false,
      "port_speed_bps": 10000000,
      "tc_configs": {
        "0": {"enabled": true, "idle_slope_bps": 7000000, "max_credit_bytes": 8750},
        "3": {"enabled": true, "idle_slope_bps": 2000000, "max_credit_bytes": 2500}
      }
    }
  }
}
```

- `gates` is a 4-bit mask over traffic classes TC0..TC3 (e.g. `8` = TC3 only,
  `7` = TC0/TC1/TC2, `15` = all open). The gate list (`gcl`) durations must sum
  to `cycle_us`.
- `port_speed_bps` simulates the egress wire speed (one frame at a time;
  `tx_time = frame_bits / port_speed_bps`).
- CBS `idle_slope_bps` is the reserved rate per traffic class; the sum of
  enabled classes must be below `port_speed_bps`.

---