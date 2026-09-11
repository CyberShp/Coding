"""Resolve LLDP endpoint identities; never infer cables from IP subnets or MAC tables."""
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta

from .topology_parsers import mac, port_key

STALE_SECONDS = 300


def identity(value):
    value = (value or "").strip().lower()
    return mac(value) or value


def build_graph(devices, snapshots, now=None, cables=None):
    now = now or datetime.utcnow()
    nodes, lookup, port_lookup = [], defaultdict(set), defaultdict(set)
    by_id = {}
    for device in devices:
        snap = snapshots.get(device["id"], {})
        payload = snap.get("payload", {})
        collected = snap.get("collected_at")
        stale = not collected or bool(snap.get("last_error")) or now - collected > timedelta(seconds=STALE_SECONDS)
        node = {**device, "ports": payload.get("ports", []),
                "system_name": payload.get("system_name", ""),
                "collected_at": collected.isoformat() + "Z" if collected else None,
                "attempted_at": snap["attempted_at"].isoformat() + "Z" if snap.get("attempted_at") else None,
                "stale": stale, "last_error": snap.get("last_error", ""),
                "notice": payload.get("notice", ""), "commands": payload.get("commands", []),
                "state": "uncollected" if not collected else "stale" if stale else "collected"}
        nodes.append(node)
        by_id[node["id"]] = node
        for key in (device["host"], device.get("mgmt_ip"), payload.get("system_name"), payload.get("chassis_id")):
            if key and key != "--":
                lookup[identity(key)].add(node["id"])
        for port in node["ports"]:
            if port.get("mac"):
                port_lookup[mac(port["mac"])].add((node["id"], port["id"]))
    links = {}
    for device in devices:
        source = by_id[device["id"]]
        payload = snapshots.get(source["id"], {}).get("payload", {})
        for neighbor in payload.get("neighbors", []):
            local = port_key(neighbor["local_port"])
            # An LLDP logical/aggregate interface is not a physical cable endpoint.
            if not any(p["id"] == local for p in source["ports"]):
                continue
            evidence_sets = [lookup[identity(neighbor.get(k))] for k in ("remote_chassis", "remote_address", "remote_name") if lookup.get(identity(neighbor.get(k)))]
            remote_mac = mac(neighbor["remote_port"])
            mac_matches = port_lookup.get(remote_mac, set()) if remote_mac else set()
            if mac_matches:
                evidence_sets.append({d for d, _ in mac_matches})
            candidates = set.intersection(*evidence_sets) if evidence_sets else set()
            # A system name is not sufficient when supplied strong identities do
            # not match. Also reject a known chassis mismatch even if the IP/name matches.
            strong = set()
            for field in ('remote_chassis', 'remote_address'):
                strong.update(lookup.get(identity(neighbor.get(field)), set()))
            strong.update(d for d, _ in mac_matches)
            candidates &= strong
            candidates = {candidate for candidate in candidates if not (
                snapshots.get(candidate, {}).get('payload', {}).get('chassis_id')
                and neighbor.get('remote_chassis')
                and identity(snapshots[candidate]['payload']['chassis_id']) != identity(neighbor['remote_chassis'])
            )}
            target_id = next(iter(candidates)) if len(candidates) == 1 else None
            target_port = port_key(neighbor["remote_port"])
            if target_id == source["id"]:
                target_id = None
            if target_id:
                matches = [p for p in by_id[target_id]["ports"] if p["id"] == target_port or (remote_mac and p.get("mac") == remote_mac)]
                if len(matches) == 1:
                    target_port = matches[0]["id"]
                else:
                    # Device identity is known; endpoint remains the raw advertised port.
                    target_port = "unresolved:" + target_port
            if not target_id:
                key = identity(neighbor["remote_chassis"]) + "|" + identity(neighbor.get("remote_address"))
                target_id = "external:" + hashlib.sha256(key.encode()).hexdigest()[:16]
                if target_id not in by_id:
                    external = {"id": target_id, "name": neighbor.get("remote_name") or neighbor["remote_chassis"],
                                "kind": "external", "host": neighbor.get("remote_address", ""), "ports": [],
                                "state": "unresolved", "stale": True, "collected_at": None,
                                "notice": "邻居尚未匹配到唯一的已添加设备", "last_error": ""}
                    by_id[target_id] = external
                    nodes.append(external)
            endpoints = sorted([(source["id"], local), (target_id, target_port)])
            key = tuple(endpoints)
            if key not in links:
                links[key] = {"id": hashlib.sha256(repr(key).encode()).hexdigest()[:20],
                              "source": endpoints[0][0], "source_port": endpoints[0][1],
                              "target": endpoints[1][0], "target_port": endpoints[1][1], "evidence": []}
            links[key]["evidence"].append({"device_id": source["id"], "collected_at": source["collected_at"],
                                           "stale": source["stale"], "source": "LLDP", **neighbor})
    for cable in cables or []:
        if cable['source'] not in by_id or cable['target'] not in by_id:
            continue
        endpoints = sorted([(cable['source'], cable['source_port']), (cable['target'], cable['target_port'])])
        key = tuple(endpoints)
        if key not in links:
            links[key] = {"id": hashlib.sha256(repr(key).encode()).hexdigest()[:20],
                          "source": endpoints[0][0], "source_port": endpoints[0][1],
                          "target": endpoints[1][0], "target_port": endpoints[1][1], "evidence": []}
        links[key]['manual_id'] = cable['cable_id']
        links[key]['evidence'].append({"source": "人工确认", "device_id": cable['source'],
                                      "collected_at": cable['confirmed_at'].isoformat() + 'Z',
                                      "confirmed_by": cable['confirmed_by'],
                                      "stale": any(by_id[d]['stale'] for d, _ in endpoints)})
    occupied = defaultdict(set)
    for link in links.values():
        for end in ("source", "target"):
            occupied[(link[end], link[end + "_port"])].add(link["id"])
    for link in links.values():
        unresolved = any(by_id[link[e]]["kind"] == "external" or not any(p['id'] == link[e + '_port'] for p in by_id[link[e]]['ports']) for e in ("source", "target"))
        conflict = any(len(occupied[(link[e], link[e + "_port"])]) > 1 for e in ("source", "target"))
        stale = any(e["stale"] for e in link["evidence"])
        states = [p["state"] for e in ("source", "target") for p in by_id[link[e]]["ports"] if p["id"] == link[e + "_port"] and not by_id[link[e]]["stale"]]
        automatic = [e for e in link['evidence'] if e['source'] == 'LLDP']
        link["state"] = "conflict" if conflict else "stale" if stale else "unresolved" if unresolved else "down" if "down" in states else "observed" if automatic else "manual"
        link["confirmation"] = "manual" if not automatic else "bilateral" if len({e["device_id"] for e in automatic}) == 2 else "unilateral"
    return {"devices": nodes, "links": list(links.values()), "stale_after_seconds": STALE_SECONDS,
            "generated_at": now.isoformat() + "Z"}
