"""SELinux command construction, validation, and text parsing (no Qt dependency)."""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import shlex


@dataclass(frozen=True)
class Command:
    tool: str
    args: tuple[str, ...] = ()
    privileged: bool = False
    mutation: bool = False

    @property
    def display(self):
        return shlex.join((self.tool, *self.args))


TOOLS = {"sestatus", "getenforce", "setenforce", "getsebool", "setsebool",
         "semanage", "semodule", "restorecon", "ausearch", "pkexec"}


def executable(tool):
    if tool not in TOOLS:
        raise ValueError("Unsupported executable")
    for directory in ("/usr/sbin", "/usr/bin", "/sbin", "/bin"):
        path = Path(directory) / tool
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise FileNotFoundError(f"{tool} is not installed. See README.md for system packages.")


def launch_arguments(command):
    program = executable(command.tool)
    args = list(command.args)
    if command.privileged and os.geteuid() != 0:
        return executable("pkexec"), [program, *args]
    return program, args


def identifier(value):
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Enter a valid SELinux name containing letters, digits, and underscores.")
    return value


def ports(value):
    value = value.strip()
    if not re.fullmatch(r"\d+(?:-\d+)?", value):
        raise ValueError("Enter one port or an inclusive range, such as 8080 or 8000-8010.")
    bounds = [int(p) for p in value.split("-")]
    if any(p < 1 or p > 65535 for p in bounds) or bounds[0] > bounds[-1]:
        raise ValueError("Ports must be 1–65535, with the range in ascending order.")
    return "-".join(map(str, bounds))


def absolute_path(value):
    value = value.strip()
    if not value.startswith("/") or "\x00" in value or "\n" in value:
        raise ValueError("Enter an absolute path without NUL or newline characters.")
    return value


def mode_command(mode):
    if mode not in ("Enforcing", "Permissive"):
        raise ValueError("Choose Enforcing or Permissive.")
    return Command("setenforce", ("1" if mode == "Enforcing" else "0",), True, True)


def boolean_command(name, enabled, persistent):
    return Command("setsebool", (("-P",) if persistent else ()) +
                   (identifier(name), "on" if enabled else "off"), True, True)


def port_command(action, protocol, port, selinux_type=""):
    if action not in ("add", "modify", "delete") or protocol not in ("tcp", "udp", "sctp", "dccp"):
        raise ValueError("Invalid port operation or protocol.")
    args = ("port", "--" + action, "-p", protocol)
    if action != "delete":
        args += ("-t", identifier(selinux_type))
    return Command("semanage", args + (ports(port),), True, True)


def context_command(action, pattern, selinux_type="", file_type="a"):
    if action not in ("add", "modify", "delete") or file_type not in "afdcbslp" or len(file_type) != 1:
        raise ValueError("Invalid context operation or file type.")
    args = ("fcontext", "--" + action, "-f", file_type)
    if action != "delete":
        args += ("-t", identifier(selinux_type))
    return Command("semanage", args + (absolute_path(pattern),), True, True)


def restore_command(path, recursive=False, preview=True):
    args = ("-v",) + (("-R",) if recursive else ()) + (("-n",) if preview else ())
    return Command("restorecon", args + (absolute_path(path),), True, not preview)


def module_command(action, value):
    if action == "install":
        args = ("-i", absolute_path(value))
    elif action == "remove":
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", value):
            raise ValueError("Enter a valid module name without spaces or leading option characters.")
        args = ("-r", value)
    else:
        raise ValueError("Invalid module operation.")
    return Command("semodule", args, True, True)


def parse_booleans(output):
    return [list(m.groups()) for line in output.splitlines()
            if (m := re.fullmatch(r"\s*(\w+)\s+-->\s+(on|off)\s*", line))]


def parse_ports(output):
    return [list(m.groups()) for line in output.splitlines()
            if (m := re.fullmatch(r"\s*(\w+)\s+(tcp|udp|sctp|dccp)\s+(.+?)\s*", line))]


def parse_status(output):
    return dict(line.split(":", 1) for line in output.splitlines() if ":" in line)


FILE_TYPES = {"a": "all files", "f": "regular file", "d": "directory", "c": "character device",
              "b": "block device", "s": "socket", "l": "symbolic link", "p": "named pipe"}


class Demo:
    """In-memory fixtures. No processes or filesystem changes are performed."""
    def __init__(self):
        self.mode = "Enforcing"
        self.booleans = {"httpd_can_network_connect": "off", "httpd_enable_cgi": "on",
                         "ssh_sysadm_login": "off", "virt_use_nfs": "off", "use_nfs_home_dirs": "off"}
        self.port_rows = [["http_port_t", "tcp", "80, 443, 8080"], ["ssh_port_t", "tcp", "22"],
                          ["dns_port_t", "udp", "53"]]
        self.local_port_rows = [["http_port_t", "tcp", "8443"]]
        self.contexts = {"/srv/www(/.*)?": ("a", "httpd_sys_content_t")}
        self.modules = {"apache", "ssh", "container"}

    def run(self, cmd):
        a = cmd.args
        if cmd.tool == "sestatus":
            return f"SELinux status: enabled\nSELinuxfs mount: /sys/fs/selinux\nSELinux root directory: /etc/selinux\nLoaded policy name: targeted\nCurrent mode: {self.mode.lower()}\nMode from config file: enforcing\nPolicy MLS status: enabled\nMax kernel policy version: 33\n"
        if cmd.tool == "setenforce":
            self.mode = "Enforcing" if a[0] == "1" else "Permissive"
        elif cmd.tool == "getsebool":
            return "\n".join(f"{k} --> {v}" for k, v in sorted(self.booleans.items()))
        elif cmd.tool == "setsebool":
            self.booleans[a[-2]] = a[-1]
        elif cmd.tool == "semanage" and a[0] == "port":
            if "-l" in a:
                rows = self.local_port_rows if "-C" in a else self.port_rows + self.local_port_rows
                return "\n".join("    ".join(row) for row in rows)
            protocol, value = a[a.index("-p") + 1], a[-1]
            self.local_port_rows = [r for r in self.local_port_rows if not (r[1] == protocol and r[2] == value)]
            if "--delete" not in a:
                self.local_port_rows.append([a[a.index("-t") + 1], protocol, value])
        elif cmd.tool == "semanage" and a[0] == "fcontext":
            if "-l" in a:
                local = "\n".join(f"{p}    {FILE_TYPES[kind]}    system_u:object_r:{t}:s0"
                                    for p, (kind, t) in self.contexts.items())
                return local if "-C" in a else "/var/www(/.*)?    all files    system_u:object_r:httpd_sys_content_t:s0\n" + local
            if "--delete" in a:
                self.contexts.pop(a[-1], None)
            else:
                self.contexts[a[-1]] = (a[a.index("-f") + 1], a[a.index("-t") + 1])
        elif cmd.tool == "restorecon":
            return f"{'Would relabel' if '-n' in a else 'Relabeled'} {a[-1]} to system_u:object_r:httpd_sys_content_t:s0\n"
        elif cmd.tool == "semodule":
            if "-l" in a:
                return "\n".join(sorted(self.modules))
            if "-i" in a:
                self.modules.add(Path(a[-1]).stem)
            else:
                self.modules.discard(a[-1])
        elif cmd.tool == "ausearch":
            return 'Illustrative demo event (not from this host):\ntype=AVC msg=audit(0.0:42): avc: denied { name_connect } comm="httpd" scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:port_t:s0 tclass=tcp_socket\n'
        return "Demo change applied in memory only.\n"
