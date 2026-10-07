import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import (Command, Demo, absolute_path, boolean_command, context_command,
                     launch_arguments, mode_command, module_command, parse_booleans,
                     parse_ports, parse_status, port_command, ports, restore_command)


class BackendTests(unittest.TestCase):
    def test_parse_tools_with_headers_whitespace_and_ranges(self):
        self.assertEqual(parse_booleans("a --> on\nb --> off\nnoise\n"), [["a", "on"], ["b", "off"]])
        self.assertEqual(parse_ports("SELinux Port Type Proto Port Number\nhttp_port_t tcp 80, 443\ncustom_t udp 8000-8010"),
                         [["http_port_t", "tcp", "80, 443"], ["custom_t", "udp", "8000-8010"]])
        self.assertEqual(parse_status("Current mode: enforcing\nnoise"), {"Current mode": " enforcing"})

    def test_invalid_ports(self):
        for value in ["0", "65536", "90-80", "80,81", "--help", "80;id", "", "1-2-3"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ports(value)
        self.assertEqual(ports(" 08080 "), "8080")
        self.assertEqual(ports("1-65535"), "1-65535")

    def test_boolean_persistence_and_injection(self):
        self.assertEqual(boolean_command("httpd_can_network_connect", True, True).args,
                         ("-P", "httpd_can_network_connect", "on"))
        self.assertEqual(boolean_command("virt_use_nfs", False, False).args, ("virt_use_nfs", "off"))
        for name in ["--help", "a;id", "a b", "$(id)"]:
            with self.assertRaises(ValueError):
                boolean_command(name, True, False)

    def test_mutation_arguments(self):
        self.assertEqual(mode_command("Permissive").args, ("0",))
        with self.assertRaises(ValueError):
            mode_command("Disabled")
        self.assertEqual(port_command("delete", "tcp", "8080").args, ("port", "--delete", "-p", "tcp", "8080"))
        self.assertEqual(port_command("modify", "udp", "8000-8010", "http_port_t").args,
                         ("port", "--modify", "-p", "udp", "-t", "http_port_t", "8000-8010"))
        self.assertEqual(context_command("add", "/a b(/.*)?", "httpd_sys_content_t").args[-1], "/a b(/.*)?")
        self.assertEqual(context_command("delete", "/srv/www", file_type="d").args,
                         ("fcontext", "--delete", "-f", "d", "/srv/www"))
        self.assertFalse(restore_command("/srv/www", True, True).mutation)
        self.assertEqual(restore_command("/srv/www", True, True).args, ("-v", "-R", "-n", "/srv/www"))
        self.assertTrue(restore_command("/srv/www", False, False).mutation)
        self.assertEqual(module_command("install", "/tmp/example.pp").args, ("-i", "/tmp/example.pp"))
        self.assertEqual(module_command("remove", "example-module").args, ("-r", "example-module"))
        with self.assertRaises(ValueError):
            module_command("remove", "--help")

    def test_absolute_paths(self):
        for value in ["relative", "--help", "/tmp/\x00x", "/tmp/\nx"]:
            with self.assertRaises(ValueError):
                absolute_path(value)
        self.assertEqual(absolute_path("/tmp/a; b$(id)"), "/tmp/a; b$(id)")

    def test_pkexec_routes_only_privileged_commands(self):
        with patch("backend.executable", side_effect=lambda value: "/usr/bin/" + value), patch("backend.os.geteuid", return_value=1000):
            self.assertEqual(launch_arguments(mode_command("Enforcing")), ("/usr/bin/pkexec", ["/usr/bin/setenforce", "1"]))
            self.assertEqual(launch_arguments(Command("sestatus")), ("/usr/bin/sestatus", []))
        with patch("backend.executable", return_value="/usr/sbin/setenforce"), patch("backend.os.geteuid", return_value=0):
            self.assertEqual(launch_arguments(mode_command("Enforcing")), ("/usr/sbin/setenforce", ["1"]))

    def test_demo_state_updates(self):
        demo = Demo()
        demo.run(mode_command("Permissive"))
        self.assertIn("Current mode: permissive", demo.run(Command("sestatus")))
        demo.run(boolean_command("virt_use_nfs", True, True))
        self.assertIn("virt_use_nfs --> on", demo.run(Command("getsebool")))
        demo.run(port_command("add", "tcp", "8443", "http_port_t"))
        self.assertIn("8443", demo.run(Command("semanage", ("port", "-l"))))
        demo.run(port_command("delete", "tcp", "8443"))
        self.assertNotIn("8443", demo.run(Command("semanage", ("port", "-l"))))
        self.assertNotIn("ssh_port_t", demo.run(Command("semanage", ("port", "-l", "-C"))))
        self.assertIn("ssh_port_t", demo.run(Command("semanage", ("port", "-l"))))
        demo.run(context_command("add", "/srv/app", "httpd_sys_content_t", "d"))
        local = demo.run(Command("semanage", ("fcontext", "-l", "-C")))
        self.assertIn("/srv/app    directory    system_u:object_r:httpd_sys_content_t:s0", local)
        self.assertIn("/srv/www(/.*)?    all files    ", local)
        demo.run(context_command("delete", "/srv/app", file_type="d"))
        self.assertNotIn("/srv/app", demo.run(Command("semanage", ("fcontext", "-l", "-C"))))
        demo.run(module_command("install", "/tmp/custom.pp"))
        self.assertIn("custom", demo.run(Command("semodule", ("-l",))))
        demo.run(module_command("remove", "custom"))
        self.assertNotIn("custom", demo.run(Command("semodule", ("-l",))))


if __name__ == "__main__":
    unittest.main()
