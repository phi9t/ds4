#!/usr/bin/env python3
"""Scan staged or tracked text for PII, secrets, and machine identifiers.

The default mode is pre-commit friendly: scan staged added/modified/copied/
renamed files and fail on high-confidence findings. Use --redact on explicit
files or --all when intentionally scrubbing historical artifacts.
"""

from __future__ import annotations

import argparse
import dataclasses
import ipaddress
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable


INLINE_ALLOW = ("privacy-scrub: allow", "pii-scrub: allow")
MAX_BYTES = 5 * 1024 * 1024


@dataclasses.dataclass(frozen=True)
class Rule:
    kind: str
    severity: str
    pattern: re.Pattern[str]
    replacement: str | Callable[[re.Match[str]], str]
    description: str
    validator: Callable[[str], bool] | None = None


@dataclasses.dataclass(frozen=True)
class Finding:
    path: str
    line: int
    column: int
    kind: str
    severity: str
    text: str
    description: str


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def repo_root() -> Path:
    proc = git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(proc.stdout.strip()).resolve()


def git_lines(repo: Path, *args: str) -> list[str]:
    out = git(repo, *args).stdout
    return [line for line in out.splitlines() if line]


def staged_paths(repo: Path) -> list[str]:
    return git_lines(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR")


def tracked_paths(repo: Path) -> list[str]:
    return git_lines(repo, "ls-files")


def staged_bytes(repo: Path, rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f":{rel}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def working_bytes(repo: Path, rel: str) -> bytes | None:
    path = repo / rel
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def is_probably_binary(data: bytes) -> bool:
    return b"\0" in data[:4096]


def decode_text(data: bytes) -> str | None:
    if is_probably_binary(data) or len(data) > MAX_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def private_ipv4(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return isinstance(addr, ipaddress.IPv4Address) and addr.is_private and not addr.is_loopback


def non_example_email(value: str) -> bool:
    local, domain = value.rsplit("@", 1)
    local = local.lower()
    domain = domain.lower()
    if local in {"noreply", "no-reply", "donotreply", "do-not-reply"}:
        return False
    if domain in {
        "example.com",
        "example.org",
        "example.net",
        "localhost",
        "invalid",
        "users.noreply.github.com",
    }:
        return False
    return not domain.endswith((".example", ".invalid", ".test"))


def machine_id_replacement(match: re.Match[str]) -> str:
    return f"{match.group(1)}=<MACHINE_ID>"


def git_user_replacement(match: re.Match[str]) -> str:
    return f"{match.group(1)}<USER>"


def preserve_path_punctuation(placeholder: str) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        suffix = ""
        while value and value[-1] in "`.,;:":
            suffix = value[-1] + suffix
            value = value[:-1]
        return placeholder + suffix

    return replace


def ssh_endpoint(value: str) -> bool:
    user, host = value.rsplit("@", 1)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{1,31}", user):
        return False
    host = host.strip("[]")
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.lower() == "sha256" or host.lower().startswith("sha256:"):
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # A bare, non-example hostname in an SSH endpoint is machine-identifying.
        return "." not in host and len(host) >= 4 and re.search(r"[A-Za-z]", host) is not None
    return isinstance(addr, ipaddress.IPv4Address) and addr.is_private


def build_rules(repo: Path) -> list[Rule]:
    user = os.environ.get("USER") or ""
    home = str(Path.home())
    hostnames = {socket.gethostname(), socket.getfqdn()}
    hostnames = {h for h in hostnames if h and h not in {"localhost", "localhost.localdomain"}}
    private_host_patterns = [
        r"dgx" + r"spark\d+",
        r"mac-" + r"m5max-" + r"(?:it|us)",
        "strix" + "halo",
    ]
    git_user_prefix = "Git " + "user:"

    rules: list[Rule] = [
        Rule(
            "secret.private_key",
            "error",
            re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
            "<REDACTED_PRIVATE_KEY>",
            "private key material",
        ),
        Rule(
            "secret.github_token",
            "error",
            re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,255}\b|\bgithub_pat_[A-Za-z0-9_]{20,255}\b"),
            "<REDACTED_GITHUB_TOKEN>",
            "GitHub token",
        ),
        Rule(
            "secret.huggingface_token",
            "error",
            re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
            "<REDACTED_HF_TOKEN>",
            "Hugging Face token",
        ),
        Rule(
            "secret.aws_access_key",
            "error",
            re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
            "<REDACTED_AWS_KEY>",
            "AWS access key id",
        ),
        Rule(
            "secret.openai_key",
            "error",
            re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
            "<REDACTED_API_KEY>",
            "OpenAI-style API key",
        ),
        Rule(
            "machine.mac_address",
            "error",
            re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"),
            "<MAC_ADDRESS>",
            "MAC address",
        ),
        Rule(
            "machine.gpu_uuid",
            "error",
            re.compile(r"\bGPU-[0-9A-Fa-f-]{24,}\b"),
            "<GPU_UUID>",
            "GPU UUID",
        ),
        Rule(
            "machine.private_hostname",
            "error",
            re.compile(r"\b(?:" + "|".join(private_host_patterns) + r")\b"),
            "<PRIVATE_HOST>",
            "known private DS4 host name",
        ),
        Rule(
            "machine.ssh_endpoint",
            "error",
            re.compile(r"\b[A-Za-z0-9._-]+@[A-Za-z0-9._:-]+\b"),
            "<SSH_ENDPOINT>",
            "SSH-style user and host endpoint",
            ssh_endpoint,
        ),
        Rule(
            "machine.machine_id",
            "error",
            re.compile(r"\b(machine[-_ ]?id|host[-_ ]?id|product[-_ ]?uuid)\s*[:=]\s*[0-9A-Fa-f]{16,64}\b", re.IGNORECASE),
            machine_id_replacement,
            "machine or host id",
        ),
        Rule(
            "machine.git_user",
            "error",
            re.compile(r"\b(" + re.escape(git_user_prefix) + r"\s*)[A-Za-z0-9._-]+\b"),
            git_user_replacement,
            "Git user identity from captured environment",
        ),
        Rule(
            "machine.private_ip",
            "error",
            re.compile(r"(?<![\d.])(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2}(?![\d.])"),
            "<PRIVATE_IP>",
            "private IPv4 address",
            private_ipv4,
        ),
        Rule(
            "pii.email",
            "error",
            re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
            "<EMAIL>",
            "email address",
            non_example_email,
        ),
        Rule(
            "machine.home_path",
            "error",
            re.compile(r"(?:/data\d+)?/home/(?!ds4\b|runner\b|colab\b)[A-Za-z0-9._-]+(?:/[^\s\"'<>)]*)?"),
            preserve_path_punctuation("<HOME_PATH>"),
            "Linux home path",
        ),
        Rule(
            "machine.mac_home_path",
            "error",
            re.compile(r"/Users/(?!Shared\b)[A-Za-z0-9._-]+(?:/[^\s\"'<>)]*)?"),
            preserve_path_punctuation("<HOME_PATH>"),
            "macOS home path",
        ),
    ]

    for exact, kind, replacement, description in [
        (str(repo), "machine.repo_path", "<DS4_REPO>", "local repository path"),
        (home, "machine.home_path", "<HOME>", "local home directory"),
    ]:
        if exact and exact != "/":
            rules.append(Rule(kind, "error", re.compile(re.escape(exact)), replacement, description))

    if user and user not in {"root", "ds4"}:
        rules.append(
            Rule(
                "machine.username",
                "error",
                re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(user)}(?![A-Za-z0-9_-])"),
                "<USER>",
                "local username",
            )
        )

    for host in sorted(hostnames):
        if len(host) >= 4:
            rules.append(
                Rule(
                    "machine.hostname",
                    "error",
                    re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(host)}(?![A-Za-z0-9_-])"),
                    "<HOST>",
                    "local hostname",
                )
            )
    return rules


def line_for_offset(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start + 1


def allowed_line(text: str, offset: int) -> bool:
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    return any(marker in line for marker in INLINE_ALLOW)


def scan_text(path: str, text: str, rules: Iterable[Rule]) -> list[Finding]:
    findings: list[Finding] = []
    for rule in rules:
        for match in rule.pattern.finditer(text):
            value = match.group(0)
            if rule.validator and not rule.validator(value):
                continue
            if allowed_line(text, match.start()):
                continue
            line, column = line_for_offset(text, match.start())
            findings.append(Finding(path, line, column, rule.kind, rule.severity, value, rule.description))
    findings.sort(key=lambda f: (f.path, f.line, f.column, f.kind))
    return findings


def redact_text(text: str, rules: Iterable[Rule]) -> str:
    for rule in rules:
        def repl(match: re.Match[str], rule: Rule = rule) -> str:
            value = match.group(0)
            if rule.validator and not rule.validator(value):
                return value
            if allowed_line(text, match.start()):
                return value
            if callable(rule.replacement):
                return rule.replacement(match)
            return rule.replacement

        text = rule.pattern.sub(repl, text)
    return text


def collect_paths(repo: Path, args: argparse.Namespace) -> tuple[list[str], bool]:
    if args.files:
        return [str(Path(p)) for p in args.files], False
    if args.all:
        return tracked_paths(repo), False
    return staged_paths(repo), True


def print_findings(findings: list[Finding]) -> None:
    for f in findings:
        print(f"{f.path}:{f.line}:{f.column}: {f.severity}: {f.kind}: {f.description}", file=sys.stderr)


def run_self_test() -> int:
    home_root = Path("/", "data02", "home", "alice")
    repo = home_root / "workspace" / "ds4"
    rules = build_rules(repo)
    bad_email = "alice" + "@work" + ".internal"
    private_ip = ".".join(["192", "168", "1", "44"])
    github_token = "ghp_" + "abcdefghijklmnopqrstuvwxyzABCDE12345"
    machine_id = "0123456789abcdef" * 2
    ssh_target = "alice" + "@" + "buildbox"
    private_host = "mac-" + "m5max-us"
    git_user_sample = "Git " + "user: alice"
    sample = (
        f"path {repo}/docs/x\n"
        "email alice@example.invalid ok\n"
        f"email {bad_email}\n"
        f"ip {private_ip}\n"
        f"token {github_token}\n"
        f"machine-id={machine_id}\n"
        f"ssh {ssh_target}\n"
        f"host {private_host}\n"
        f"{git_user_sample}\n"
    )
    findings = scan_text("sample.txt", sample, rules)
    kinds = {f.kind for f in findings}
    required = {
        "machine.home_path",
        "pii.email",
        "machine.private_ip",
        "secret.github_token",
        "machine.machine_id",
        "machine.ssh_endpoint",
        "machine.private_hostname",
        "machine.git_user",
    }
    missing = required - kinds
    redacted = redact_text(sample, rules)
    bad_leftovers = [
        str(home_root) in redacted,
        bad_email in redacted,
        private_ip in redacted,
        "ghp_" in redacted,
        ssh_target in redacted,
        private_host in redacted,
        git_user_sample in redacted,
    ]
    if missing or any(bad_leftovers):
        print(f"self-test failed; missing={sorted(missing)} redacted={redacted!r}", file=sys.stderr)
        return 1
    print("privacy_scrub self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="scan staged files (default)")
    mode.add_argument("--all", action="store_true", help="scan all tracked files")
    parser.add_argument("--redact", action="store_true", help="rewrite scanned working-tree files with redactions")
    parser.add_argument("--self-test", action="store_true", help="run embedded unit checks")
    parser.add_argument("files", nargs="*", help="explicit files to scan")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    repo = repo_root()
    paths, staged = collect_paths(repo, args)
    if args.redact and staged:
        print("--redact requires explicit files or --all; it does not rewrite the Git index", file=sys.stderr)
        return 2
    if not paths:
        return 0

    rules = build_rules(repo)
    all_findings: list[Finding] = []
    changed = 0
    for rel in paths:
        data = staged_bytes(repo, rel) if staged else working_bytes(repo, rel)
        if data is None:
            continue
        text = decode_text(data)
        if text is None:
            continue
        findings = scan_text(rel, text, rules)
        all_findings.extend(findings)
        if args.redact and findings:
            redacted = redact_text(text, rules)
            if redacted != text:
                (repo / rel).write_text(redacted)
                changed += 1

    if args.redact:
        print(f"privacy_scrub: redacted {changed} file(s)", file=sys.stderr)
        return 0

    if all_findings:
        print("privacy_scrub: PII, secret, or machine-identifying text found", file=sys.stderr)
        print_findings(all_findings)
        print("privacy_scrub: redact or add an inline 'privacy-scrub: allow' comment for intentional examples", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
