"""Bounded, read-only CLI collection over a dedicated SSH session."""
import re
import time
import threading

from .ssh_pool import SSHConnection
from .topology_parsers import fields, parse_interfaces, parse_local, parse_neighbors, parse_storage_ports

COMMANDS = {
    "switch": ("display interface brief", "display lldp local", "display lldp neighbor"),
    "storage": ("show port general physical_type=ETH", "show system general"),
}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PROMPT = re.compile(r"(?:^|\n)(?:<[^\r\n<>]+>|\[[^\r\n\[\]]+\]|[\w.@:-]+:/>)[ \t]*$")
PAGER = re.compile(r"[- ]+More[- ]+|Press (?:any key|SPACE).*?continue", re.I)
CLI_ERROR = re.compile(r"(?:^|\n)\s*(?:Error\s*:|Failure\s*:|%\s*(?:Error|Unknown)|Unrecognized command|Incomplete command)", re.I)


def read_reply(channel, timeout=20):
    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        if channel.recv_ready():
            chunk = channel.recv(65536)
            if not chunk:
                raise RuntimeError("SSH 会话提前结束")
            text += chunk.decode("utf-8", errors="replace")
            text = ANSI.sub("", text).replace("\r", "")
            # VRP erases its pager using backspace; remove the control characters.
            text = text.replace("\b", "")
            if len(text) > 2_000_000:
                raise RuntimeError("采集输出超过 2 MB，未保存不完整结果")
            if PAGER.search(text):
                text = PAGER.sub("", text)
                channel.sendall(" ")
            if PROMPT.search(text):
                return text
        elif channel.closed:
            raise RuntimeError("SSH 会话提前关闭")
        else:
            time.sleep(0.02)
    raise TimeoutError("等待设备命令提示符超时")


class TopologySSHConnection(SSHConnection):
    def collect(self, kind):
        # Closing the underlying client is deliberately lock-free: connect() holds
        # SSHConnection._lock while authenticating. This also interrupts PTY/shell waits.
        expired = threading.Event()
        def expire():
            expired.set()
            if self._client:
                self._client.close()
        watchdog = threading.Timer(85, expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            result = self._collect(kind)
            if expired.is_set():
                raise TimeoutError("设备采集超过 85 秒，连接已关闭")
            return result
        except Exception:
            if expired.is_set():
                raise TimeoutError("设备采集超过 85 秒，连接已关闭") from None
            raise
        finally:
            watchdog.cancel()
            self.disconnect()

    def _collect(self, kind):
        if not self.connect():
            # SSH errors can include authentication detail. API exposes only a fixed category.
            raise ConnectionError("SSH 登录失败，请检查地址、凭据和权限")
        try:
            channel = self._client.invoke_shell(width=512, height=1000)
            channel.settimeout(20)
            try:
                read_reply(channel)
                outputs = {}
                for command in COMMANDS[kind]:
                    channel.sendall(command + "\n")
                    reply = read_reply(channel)
                    if CLI_ERROR.search(reply):
                        raise RuntimeError(f"设备拒绝读取命令：{command}")
                    outputs[command] = reply
            finally:
                channel.close()
        finally:
            self.disconnect()
        if kind == "switch":
            return {
                **parse_local(outputs[COMMANDS[kind][1]]),
                "ports": parse_interfaces(outputs[COMMANDS[kind][0]]),
                "neighbors": parse_neighbors(outputs[COMMANDS[kind][2]]),
                "neighbor_supported": True, "commands": list(COMMANDS[kind]),
            }
        identity = fields(outputs[COMMANDS[kind][1]])
        return {"system_name": identity.get("name", ""), "chassis_id": "",
                "ports": parse_storage_ports(outputs[COMMANDS[kind][0]]), "neighbors": [],
                "neighbor_supported": False, "commands": list(COMMANDS[kind]),
                "notice": "存储端口已采集；自动连线依赖交换机邻居证据。存储直连可通过人工确认接线记录。"}


def collect_device(device, password=""):
    connection = TopologySSHConnection(
        device["id"], device["host"], device["port"], device["username"],
        password=password, key_path=device.get("key_path") or None,
    )
    return connection.collect(device["kind"])
