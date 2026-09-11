"""Conservative Huawei CLI parsers. Unrecognized output is not an empty topology."""
import re


class TopologyParseError(ValueError):
    pass


def mac(value):
    value = re.sub(r"[.:\-]", "", value.strip()).lower()
    return value if re.fullmatch(r"[0-9a-f]{12}", value) else ""


def port_key(value):
    value = re.sub(r"\s+", "", value).lower()
    for long, short in (("hundredgige", "100ge"), ("xgigabitethernet", "10ge"),
                        ("tengigabitethernet", "10ge"), ("gigabitethernet", "ge")):
        if value.startswith(long):
            return short + value[len(long):]
    return value


def fields(text):
    result = {}
    for line in text.splitlines():
        match = re.match(r"\s*([A-Za-z][A-Za-z ()/\d_-]*?)\s*:\s*(.*?)\s*$", line)
        if match:
            result[match[1].strip().lower()] = match[2].strip()
    return result


def parse_local(text):
    data = fields(text)
    chassis = data.get("chassis id", "")
    name = data.get("system name", "")
    if not chassis and not name:
        raise TopologyParseError("未识别本机 LLDP 信息")
    return {"chassis_id": chassis, "system_name": name}


def parse_neighbors(text):
    # VRP uses '<interface> has N neighbor(s):', with optional spaces in port names.
    sections = list(re.finditer(r"(?m)^\s*([\w./:-]+(?:\s+[\d/.:]+)?)\s+has\s+(\d+)\s+neighbor\(s\)\s*:", text, re.I))
    if not sections:
        if re.search(r"(?:no\s+(?:lldp\s+)?neighbor|total\s+(?:number\s+of\s+)?neighbors?\s*[:=]\s*0)\b", text, re.I):
            return []
        raise TopologyParseError("未识别 LLDP 邻居输出；不能当作无连接")
    neighbors = []
    for i, section in enumerate(sections):
        block = text[section.end():sections[i + 1].start() if i + 1 < len(sections) else len(text)]
        records = re.split(r"(?im)^\s*Neighbor index\s*:\s*\d+\s*$", block)[1:]
        if len(records) != int(section[2]):
            raise TopologyParseError("LLDP 邻居输出不完整")
        for record in records:
            data = fields(record)
            if not data.get("chassis id") or not data.get("port id"):
                raise TopologyParseError("LLDP 邻居缺少设备或端口标识")
            neighbors.append({
                "local_port": port_key(section[1]), "remote_chassis": data["chassis id"],
                "remote_port": data["port id"], "remote_name": data.get("system name", ""),
                "remote_address": data.get("management address", ""),
            })
    return neighbors


def parse_interfaces(text):
    if not re.search(r"Interface\s+PHY\s+Protocol", text, re.I):
        raise TopologyParseError("未识别交换机端口表")
    ports = []
    for line in text.splitlines():
        match = re.match(r"\s*((?:\d*GE|GigabitEthernet|XGigabitEthernet|Ethernet|MEth)\s*\d[\d/]*)(?:\([^)]*\))?\s+(\S+)\s+\S+", line, re.I)
        if not match:
            continue
        name, state = match.groups()
        name = port_key(name)
        # Retain the reported slot locator; it does not establish board ownership.
        ports.append({"id": name, "label": re.sub(r"\s+", "", match[1]),
                      "state": "up" if state.lower() == "up" else "down" if "down" in state.lower() else "unknown",
                      "location": name.rsplit("/", 1)[0], "kind": "ethernet", "mac": "", "speed": ""})
    if not ports:
        raise TopologyParseError("端口表中没有可识别的以太网端口")
    return ports


def parse_storage_ports(text):
    # OceanStor tables use runs of >=2 spaces between columns; multi-word headers are preserved.
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if re.search(r"\bID\s{2,}.*Running Status", line)), None)
    if header is None:
        raise TopologyParseError("未识别 OceanStor 以太网端口表")
    keys = re.split(r"\s{2,}", lines[header].strip())
    ports = []
    for line in lines[header + 1:]:
        cells = re.split(r"\s{2,}", line.strip())
        if not cells or not re.fullmatch(r"[\w.-]+\.P\d+", cells[0], re.I):
            continue
        if len(cells) != len(keys):
            raise TopologyParseError("OceanStor 端口表列数不匹配")
        data = dict(zip(keys, cells))
        name = data["ID"]
        location = name.rsplit(".", 1)[0]
        state = data["Running Status"].lower()
        ports.append({"id": port_key(name), "label": name, "location": location,
                      "kind": "card" if re.search(r"\.IOM\d+", name, re.I) else "onboard" if re.search(r"\.NET\d+", name, re.I) else "unknown",
                      "state": "up" if state == "link up" else "down" if state == "link down" else "unknown",
                      "mac": mac(data.get("MAC", data.get("MAC Address", ""))),
                      "speed": data.get("Working Rate(Mbps)", "") if data.get("Working Rate(Mbps)", "").isdigit() else ""})
    if not ports:
        raise TopologyParseError("端口表中没有可识别的端口定位信息")
    return ports
