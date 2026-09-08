"""
Programmatic SUMO Network & Traffic Demand Builder.

Generates standard benchmark networks:
1. 4-way single intersection with netconvert auto-generated traffic light logic
2. Corridor (multi-intersection arterial) for coordination and degradation testing
"""
import os
import subprocess
import logging
from typing import List, Tuple, Dict, Optional

from .sumo_config import get_binary

logger = logging.getLogger("network_builder")


def build_4way_network(
    workdir: str,
    arm_length: float = 200.0,
    num_lanes: int = 2,
    speed_limit: float = 13.89,  # ~50 km/h
) -> Tuple[str, str]:
    """
    Builds a standard 4-way intersection network with a traffic light at (0, 0).
    Uses netconvert default traffic light generation as recommended.
    Returns (net_file_path, tls_id).
    """
    os.makedirs(workdir, exist_ok=True)
    nod_path = os.path.join(workdir, "intersection_4way.nod.xml")
    edg_path = os.path.join(workdir, "intersection_4way.edg.xml")
    net_path = os.path.join(workdir, "intersection_4way.net.xml")

    # Center intersection J0 is type="traffic_light"
    # Outer entry/exit nodes are type="priority"
    nodes = [
        ('J0', 0.0, 0.0, 'traffic_light'),
        ('N', 0.0, arm_length, 'priority'),
        ('S', 0.0, -arm_length, 'priority'),
        ('E', arm_length, 0.0, 'priority'),
        ('W', -arm_length, 0.0, 'priority'),
    ]

    with open(nod_path, "w", encoding="utf-8") as f:
        f.write('<nodes>\n')
        for node_id, x, y, ntype in nodes:
            f.write(f'  <node id="{node_id}" x="{x:.2f}" y="{y:.2f}" type="{ntype}"/>\n')
        f.write('</nodes>\n')

    # Bidirectional edges connecting perimeter to J0
    edges = [
        ('N2J0', 'N', 'J0'),
        ('J02N', 'J0', 'N'),
        ('S2J0', 'S', 'J0'),
        ('J02S', 'J0', 'S'),
        ('E2J0', 'E', 'J0'),
        ('J02E', 'J0', 'E'),
        ('W2J0', 'W', 'J0'),
        ('J02W', 'J0', 'W'),
    ]

    with open(edg_path, "w", encoding="utf-8") as f:
        f.write('<edges>\n')
        for edge_id, frm, to in edges:
            f.write(
                f'  <edge id="{edge_id}" from="{frm}" to="{to}" '
                f'numLanes="{num_lanes}" speed="{speed_limit:.2f}"/>\n'
            )
        f.write('</edges>\n')

    netconvert_bin = get_binary("netconvert")
    cmd = [
        netconvert_bin,
        "--node-files", nod_path,
        "--edge-files", edg_path,
        "--output-file", net_path,
        "--no-turnarounds",
        "--junctions.corner-detail", "5",
        "--tls.default-type", "static",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"netconvert failed (code {result.returncode}):\n{result.stderr}")

    return net_path, "J0"


def build_corridor_network(
    workdir: str,
    n_intersections: int = 2,
    spacing: float = 250.0,
    arm_length: float = 150.0,
    num_lanes: int = 2,
    speed_limit: float = 13.89,
) -> Tuple[str, List[str]]:
    """
    Builds an arterial corridor with `n_intersections` traffic lights connected in a line.
    Returns (net_file_path, list_of_tls_ids).
    """
    os.makedirs(workdir, exist_ok=True)
    nod_path = os.path.join(workdir, "corridor.nod.xml")
    edg_path = os.path.join(workdir, "corridor.edg.xml")
    net_path = os.path.join(workdir, "corridor.net.xml")

    tls_ids = [f"J{i}" for i in range(n_intersections)]
    nodes = []

    # Traffic light junctions along the x-axis
    for i in range(n_intersections):
        x = i * spacing
        nodes.append((f"J{i}", x, 0.0, "traffic_light"))
        # Cross street nodes
        nodes.append((f"N{i}", x, arm_length, "priority"))
        nodes.append((f"S{i}", x, -arm_length, "priority"))

    # Arterial endpoints (West entry, East entry)
    nodes.append(("W_IN", -arm_length, 0.0, "priority"))
    nodes.append(("E_IN", (n_intersections - 1) * spacing + arm_length, 0.0, "priority"))

    with open(nod_path, "w", encoding="utf-8") as f:
        f.write('<nodes>\n')
        for node_id, x, y, ntype in nodes:
            f.write(f'  <node id="{node_id}" x="{x:.2f}" y="{y:.2f}" type="{ntype}"/>\n')
        f.write('</nodes>\n')

    edges = []
    # Cross street edges for each intersection
    for i in range(n_intersections):
        edges.append((f"N{i}2J{i}", f"N{i}", f"J{i}"))
        edges.append((f"J{i}2N{i}", f"J{i}", f"N{i}"))
        edges.append((f"S{i}2J{i}", f"S{i}", f"J{i}"))
        edges.append((f"J{i}2S{i}", f"J{i}", f"S{i}"))

    # Arterial corridor links
    edges.append(("W2J0", "W_IN", "J0"))
    edges.append(("J02W", "J0", "W_IN"))

    for i in range(n_intersections - 1):
        edges.append((f"J{i}2J{i+1}", f"J{i}", f"J{i+1}"))
        edges.append((f"J{i+1}2J{i}", f"J{i+1}", f"J{i}"))

    last_j = f"J{n_intersections - 1}"
    edges.append((f"{last_j}2E", last_j, "E_IN"))
    edges.append((f"E2{last_j}", "E_IN", last_j))

    with open(edg_path, "w", encoding="utf-8") as f:
        f.write('<edges>\n')
        for edge_id, frm, to in edges:
            f.write(
                f'  <edge id="{edge_id}" from="{frm}" to="{to}" '
                f'numLanes="{num_lanes}" speed="{speed_limit:.2f}"/>\n'
            )
        f.write('</edges>\n')

    netconvert_bin = get_binary("netconvert")
    cmd = [
        netconvert_bin,
        "--node-files", nod_path,
        "--edge-files", edg_path,
        "--output-file", net_path,
        "--no-turnarounds",
        "--junctions.corner-detail", "5",
        "--tls.default-type", "static",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"netconvert corridor failed (code {result.returncode}):\n{result.stderr}")

    return net_path, tls_ids


def build_4way_demand(
    workdir: str,
    duration_s: float = 1200.0,
    main_vph: float = 700.0,
    side_vph: float = 400.0,
    car_accel: float = 2.0,
    car_decel: float = 3.5,
) -> str:
    """
    Generates Poisson/uniform vehicle flows across the 4-way intersection.
    North-South is primary arterial (main_vph), East-West is secondary (side_vph).
    Returns path to route file.
    """
    rou_path = os.path.join(workdir, "intersection_4way.rou.xml")

    # Routes: through, left turn, right turn
    routes = [
        # North-South arterial
        ("r_N2S", "N2J0 J02S"),
        ("r_S2N", "S2J0 J02N"),
        ("r_N2E", "N2J0 J02E"),
        ("r_S2W", "S2J0 J02W"),
        # East-West side arterial
        ("r_E2W", "E2J0 J02W"),
        ("r_W2E", "W2J0 J02E"),
        ("r_E2N", "E2J0 J02N"),
        ("r_W2S", "W2J0 J02S"),
    ]

    with open(rou_path, "w", encoding="utf-8") as f:
        f.write('<routes>\n')
        # Standard vehicle type definition
        f.write(
            f'  <vType id="standard_car" accel="{car_accel:.2f}" decel="{car_decel:.2f}" '
            f'sigma="0.4" length="4.5" minGap="2.0" maxSpeed="14.0"/>\n'
        )

        for rid, edges_str in routes:
            f.write(f'  <route id="{rid}" edges="{edges_str}"/>\n')

        # Flows
        # NS through flows
        f.write(
            f'  <flow id="f_N2S" route="r_N2S" type="standard_car" begin="0" end="{duration_s}" '
            f'vehsPerHour="{main_vph * 0.7:.0f}" departLane="best" departSpeed="max"/>\n'
        )
        f.write(
            f'  <flow id="f_S2N" route="r_S2N" type="standard_car" begin="0" end="{duration_s}" '
            f'vehsPerHour="{main_vph * 0.7:.0f}" departLane="best" departSpeed="max"/>\n'
        )
        # NS turning flows
        f.write(
            f'  <flow id="f_N2E" route="r_N2E" type="standard_car" begin="0" end="{duration_s}" '
            f'vehsPerHour="{main_vph * 0.3:.0f}" departLane="best" departSpeed="max"/>\n'
        )
        f.write(
            f'  <flow id="f_S2W" route="r_S2W" type="standard_car" begin="0" end="{duration_s}" '
            f'vehsPerHour="{main_vph * 0.3:.0f}" departLane="best" departSpeed="max"/>\n'
        )

        # EW through flows
        f.write(
            f'  <flow id="f_E2W" route="r_E2W" type="standard_car" begin="0" end="{duration_s}" '
            f'vehsPerHour="{side_vph * 0.7:.0f}" departLane="best" departSpeed="max"/>\n'
        )
        f.write(
            f'  <flow id="f_W2E" route="r_W2E" type="standard_car" begin="0" end="{duration_s}" '
            f'vehsPerHour="{side_vph * 0.7:.0f}" departLane="best" departSpeed="max"/>\n'
        )
        # EW turning flows
        f.write(
            f'  <flow id="f_E2N" route="r_E2N" type="standard_car" begin="0" end="{duration_s}" '
            f'vehsPerHour="{side_vph * 0.3:.0f}" departLane="best" departSpeed="max"/>\n'
        )
        f.write(
            f'  <flow id="f_W2S" route="r_W2S" type="standard_car" begin="0" end="{duration_s}" '
            f'vehsPerHour="{side_vph * 0.3:.0f}" departLane="best" departSpeed="max"/>\n'
        )

        f.write('</routes>\n')

    return rou_path
