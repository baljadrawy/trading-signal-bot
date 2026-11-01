"""Tests for ops/compose-safe (read-only Compose helper), plus the WP-F03 build-policy guard.

The helper tests are stdlib unittest with subprocess mocked. The build-policy guard (WP-F03 test 2; R9.d2;
docs/ops/LEARNER_BUILD_HAZARD_DESIGN.md section 6.1, T2-1 to T2-7) parses the tracked docker-compose.yml
statically: no Docker, no `compose config`, no .env file, and no configuration value is printed.

Run: python -m pytest tests/test_compose_safe.py -q
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(os.path.dirname(_HERE), "ops", "compose-safe")


def _load():
    loader = importlib.machinery.SourceFileLoader("compose_safe", _SCRIPT)
    spec = importlib.util.spec_from_loader("compose_safe", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


cs = _load()

HASH = "166d2d9965cbefa6bf036fce1a47d5e04e273146e6010a93ff75674a2fb0b1b5"


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class ComposeSafeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = self.tmp.name
        self.compose = os.path.join(self.project, "docker-compose.yml")
        with open(self.compose, "w", encoding="utf-8") as fh:
            fh.write("services: {}\n")
        patcher = mock.patch.object(cs.subprocess, "run")
        self.run_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.run_mock.return_value = _completed()

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cs.main(["--project-dir", self.project, *args])
        return rc, out.getvalue(), err.getvalue()

    def base(self):
        return ["docker", "compose", "-p", "trading-signal-bot", "-f", self.compose]

    def assert_refused(self, *args, contains=None):
        rc, _, err = self.call(*args)
        self.assertEqual(rc, 2, args)
        self.run_mock.assert_not_called()
        if contains:
            self.assertIn(contains, err)
        return err

    # --- rejections -----------------------------------------------------
    def test_unknown_command_rejected(self):
        self.assert_refused("frobnicate", contains="unknown subcommand")

    def test_missing_subcommand_rejected(self):
        self.assert_refused(contains="missing subcommand")

    def test_unknown_service_rejected(self):
        self.assert_refused("logs", "postgres", contains="unknown service")
        self.assert_refused("render-hash", "xsch", contains="unknown service")
        # CR-2: claude_review is retired from the runtime definition.
        self.assert_refused("inspect", "claude_review", contains="unknown service")

    def test_learner_rejected(self):
        for sub in ("logs", "inspect", "render-hash"):
            err = self.assert_refused(sub, "continuous_learner")
            self.assertIn("owner authorization", err)

    def test_learner_rejected_for_every_subcommand_regardless_of_profile(self):
        # The learner profile is default-startup protection only, not an authorization
        # control: the helper must refuse the learner everywhere, in any position.
        cases = [
            ("status", "continuous_learner"),
            ("services", "continuous_learner"),
            ("logs", "continuous_learner"),
            ("logs", "continuous_learner", "--tail", "10"),
            ("logs", "telegram", "continuous_learner"),
            ("inspect", "continuous_learner"),
            ("render-hash", "continuous_learner"),
            ("continuous_learner", "status"),
            ("continuous_learner",),
        ]
        for args in cases:
            with self.subTest(args=args):
                err = self.assert_refused(*args)
                self.assertIn("owner authorization", err)
        with mock.patch.dict(os.environ, {"COMPOSE_PROFILES": "learner"}):
            for sub in ("status", "logs", "inspect", "render-hash"):
                err = self.assert_refused(sub, "continuous_learner")
                self.assertIn("owner authorization", err)

    def test_profile_flag_rejected_in_any_position(self):
        variants = [
            ("--profile", "learner", "status"),
            ("status", "--profile", "learner"),
            ("logs", "telegram", "--profile", "learner"),
            ("render-hash", "--profile", "learner", "telegram"),
            ("inspect", "telegram", "--profile=learner"),
            ("--profile=learner", "services"),
            ("services", "--profile"),
        ]
        for args in variants:
            with self.subTest(args=args):
                err = self.assert_refused(*args)
                self.assertIn("--profile", err)

    def test_compose_profiles_env_not_inherited(self):
        with mock.patch.dict(os.environ, {"COMPOSE_PROFILES": "learner", "COMPOSE_FILE": "x.yml"}):
            self.call("status")
        env = self.run_mock.call_args.kwargs["env"]
        self.assertNotIn("COMPOSE_PROFILES", env)
        self.assertNotIn("COMPOSE_FILE", env)
        self.assertNotIn("--profile", self.run_mock.call_args.args[0])

    def test_no_passthrough_or_learner_start(self):
        for args in (("status", "--", "up"), ("logs", "telegram", "--", "ps"),
                     ("status", "ps"), ("up", "continuous_learner"),
                     ("start", "continuous_learner"), ("run", "continuous_learner")):
            with self.subTest(args=args):
                self.assert_refused(*args)

    def test_optimizer_rejected(self):
        for sub in ("logs", "inspect", "render-hash"):
            err = self.assert_refused(sub, "optimizer")
            self.assertIn("owner authorization", err)

    def test_each_dangerous_token_rejected(self):
        tokens = ["up", "down", "start", "stop", "restart", "rm", "create", "run", "build",
                  "pull", "push", "prune", "exec", "kill", "-v", "--volumes",
                  "--remove-orphans", "--build", "--force-recreate"]
        for tok in tokens:
            with self.subTest(token=tok):
                # as subcommand, as trailing arg, and embedded after a valid request
                self.assert_refused(tok, contains="mutation")
                self.assert_refused("status", tok, contains="mutation")
                self.assert_refused("logs", "telegram", tok, contains="mutation")
                self.run_mock.reset_mock()

    # --- Class C forms: bare up/build/down/prune and friends (WP-F03) ----
    CLASS_C_FORMS = (
        ("up",), ("up", "-d"), ("up", "--build"), ("up", "-d", "--build"), ("up", "-d", "telegram"),
        ("up", "--build", "telegram"), ("up", "-d", "--remove-orphans"), ("build",), ("build", "telegram"),
        ("build", "--no-cache"), ("down",), ("down", "-v"), ("down", "--volumes"), ("down", "--remove-orphans"),
        ("prune",), ("system", "prune"), ("system", "prune", "-a"), ("image", "prune"), ("builder", "prune"),
        ("volume", "prune"), ("container", "prune"), ("network", "prune"), ("pull",), ("pull", "telegram"),
        ("start",), ("stop",), ("restart",), ("rm", "-f"), ("kill",), ("create",),
        ("run", "--rm", "-v", "/x:/app", "telegram"), ("status", "--build"), ("status", "--build=true"),
        ("logs", "telegram", "--remove-orphans"), ("services", "--force-recreate"),
    )

    def test_class_c_forms_refused_before_any_subprocess(self):
        for args in self.CLASS_C_FORMS:
            with self.subTest(args=args):
                self.assert_refused(*args, contains="mutation")
                self.run_mock.reset_mock()

    def test_class_c_forms_refused_for_learner_and_optimizer_and_under_compose_env(self):
        env = {"COMPOSE_PROFILES": "learner,disabled", "COMPOSE_FILE": "x.yml"}
        with mock.patch.dict(os.environ, env):
            for args in self.CLASS_C_FORMS:
                for svc in ("continuous_learner", "optimizer"):
                    for form in (args + (svc,), (svc,) + args):
                        with self.subTest(form=form):
                            self.assert_refused(*form)
                            self.run_mock.reset_mock()
            for form in (("up", "--profile", "learner", "continuous_learner"),
                         ("--profile", "learner", "up", "-d"), ("--profile=disabled", "up", "optimizer")):
                with self.subTest(form=form):
                    self.assert_refused(*form)

    def test_dangerous_flag_with_value_rejected(self):
        self.assert_refused("status", "--volumes=true", contains="mutation")
        self.assert_refused("status", "--remove-orphans=1", contains="mutation")

    def test_missing_project_file_rejected(self):
        os.remove(self.compose)
        for args in (("status",), ("services",), ("render-hash", "telegram"),
                     ("logs", "telegram"), ("inspect", "telegram")):
            with self.subTest(args=args):
                rc, _, err = self.call(*args)
                self.assertEqual(rc, 2)
                self.assertIn("does not exist", err)
        self.run_mock.assert_not_called()

    def test_no_full_config_command_possible(self):
        # There is no 'config' subcommand, and render-hash/services accept no extra args.
        self.assert_refused("config", contains="unknown subcommand")
        self.assert_refused("render", contains="unknown subcommand")
        self.assert_refused("render-hash", "telegram", "--format", contains="exactly one service")
        self.assert_refused("services", "--format", contains="takes no arguments")
        # Internal guard: even a hand-built full config argv is refused before subprocess.
        with self.assertRaises(cs.Refused):
            cs._run(self.base() + ["config"])
        with self.assertRaises(cs.Refused):
            cs._run(self.base() + ["config", "--format", "json"])
        self.run_mock.assert_not_called()

    def test_invalid_logs_arguments_rejected(self):
        self.assert_refused("logs", "telegram", "--follow", contains="unexpected")
        self.assert_refused("logs", "telegram", "--tail", "1;rm", contains="invalid --tail")
        self.assert_refused("logs", "telegram", "--since", "$(id)", contains="invalid --since")

    # --- accepted requests: exact argv -----------------------------------
    def test_status_exact_argv(self):
        self.run_mock.return_value = _completed("NAME STATUS\n")
        rc, out, _ = self.call("status")
        self.assertEqual(rc, 0)
        argv = self.run_mock.call_args.args[0]
        self.assertEqual(argv, self.base() + ["ps", "--all"])
        self.assertNotIn("shell", self.run_mock.call_args.kwargs)

    def test_render_hash_exact_argv(self):
        self.run_mock.return_value = _completed(f"telegram {HASH}\n")
        rc, out, _ = self.call("render-hash", "telegram")
        self.assertEqual(rc, 0)
        self.assertEqual(self.run_mock.call_args.args[0],
                         self.base() + ["config", "--hash", "telegram"])
        self.assertEqual(out.strip(), f"telegram {HASH}")

    def test_render_hash_suppresses_unexpected_output(self):
        self.run_mock.return_value = _completed("services:\n  telegram:\n    environment:\n      X: secret\n")
        rc, out, err = self.call("render-hash", "telegram")
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertNotIn("secret", err)

    def test_services_exact_argv(self):
        self.run_mock.return_value = _completed("scanner\ntelegram\n")
        rc, out, _ = self.call("services")
        self.assertEqual(rc, 0)
        self.assertEqual(self.run_mock.call_args.args[0], self.base() + ["config", "--services"])

    def test_explicit_project_and_file_always_present(self):
        self.run_mock.return_value = _completed(f"telegram {HASH}\n")
        for args in (("status",), ("services",), ("render-hash", "telegram"),
                     ("logs", "telegram")):
            self.run_mock.reset_mock()
            self.call(*args)
            argv = self.run_mock.call_args.args[0]
            self.assertEqual(argv[:6], self.base(), args)

    def test_default_project_dir(self):
        self.assertEqual(cs.DEFAULT_PROJECT_DIR, "/home/tradmin/trading-signal-bot")
        project_dir, sub, _ = cs.parse_args(["status"])
        self.assertEqual(project_dir, "/home/tradmin/trading-signal-bot")
        self.assertEqual(sub, "status")

    def test_logs_exact_argv_and_redaction(self):
        self.run_mock.return_value = _completed(
            "Authorization: Bearer abcDEF123456\n"
            "https://api.telegram.org/bot123456789:AAbbCCddEEff_gg-hh/sendMessage\n"
        )
        rc, out, _ = self.call("logs", "telegram", "--since", "30m", "--tail", "50")
        self.assertEqual(rc, 0)
        self.assertEqual(self.run_mock.call_args.args[0],
                         self.base() + ["logs", "--no-color", "--tail", "50", "--since", "30m", "telegram"])
        self.assertNotIn("abcDEF123456", out)
        self.assertNotIn("AAbbCCddEEff_gg-hh", out)
        self.assertIn("Bearer [REDACTED]", out)
        self.assertIn("bot123456789:[REDACTED]", out)

    def test_inspect_uses_container_and_hides_env(self):
        payload = [{
            "Id": "abc", "Name": "/trading_telegram", "Image": "sha256:1",
            "Created": "t", "RestartCount": 0,
            "State": {"Status": "running", "Running": True, "StartedAt": "s",
                      "FinishedAt": "f", "ExitCode": 0, "Health": {"Status": "healthy"}},
            "Config": {"Image": "img:tag", "Env": ["TELEGRAM_BOT_TOKEN=supersecret"],
                       "Labels": {"com.docker.compose.config-hash": HASH, "other": "x"}},
            "NetworkSettings": {"Networks": {"n1": {"IPAddress": "172.0.0.2"}}},
        }]
        self.run_mock.return_value = _completed(json.dumps(payload))
        rc, out, _ = self.call("inspect", "telegram")
        self.assertEqual(rc, 0)
        self.assertEqual(self.run_mock.call_args.args[0], ["docker", "inspect", "trading_telegram"])
        self.assertNotIn("supersecret", out)
        self.assertNotIn("Env", out)
        self.assertIn(HASH, out)

    def test_service_container_mapping(self):
        self.assertEqual(cs.SERVICES, {
            "telegram": "trading_telegram", "trade_tracker": "trading_tracker",
            "scanner": "trading_scanner", "analyzer": "trading_analyzer",
            "signal_engine": "trading_signal_engine",
        })

    def test_no_mutation_subcommands_exist(self):
        for sub in cs.SUBCOMMANDS:
            self.assertNotIn(sub, cs.DENIED_TOKENS)
        self.assertEqual(set(cs.SUBCOMMANDS), {"status", "services", "logs", "inspect", "render-hash"})

    def test_nonzero_docker_exit_propagates(self):
        self.run_mock.return_value = _completed(returncode=1, stderr="Bearer tok123\n")
        rc, _, err = self.call("status")
        self.assertEqual(rc, 1)
        self.assertNotIn("tok123", err)


# ======================================================================
# WP-F03 test 2: build policy over the tracked docker-compose.yml (T2-1 to T2-7)
# ======================================================================
ROOT = pathlib.Path(_HERE).parent
COMPOSE_FILE = ROOT / "docker-compose.yml"

# The reviewed learner Compose state. "build_refused" today: the learner still has `build:` and only the
# compose-safe refusal, the profile and the procedure keep it from being built. The PR that applies Diff 1 of
# docs/ops/LEARNER_BUILD_HAZARD_DESIGN.md (section 4.1) must switch this to "pinned" in the same commit; an
# unreviewed change of the Compose file then fails T2-1, and a fixed hazard with a stale switch fails the
# strict xfails below.
LEARNER_COMPOSE_STATE = "build_refused"
REVIEWED_STATES = {
    "build_refused": {"build_services": {"optimizer", "continuous_learner"}, "build_profiles": {"disabled", "learner"}},
    "pinned": {"build_services": {"optimizer"}, "build_profiles": {"disabled"}},
}
# LB-OD-2 is undecided; this reproduces the current value (docker-compose.yml:L219), it chooses nothing.
LEARNER_RESTART_POLICY = "unless-stopped"
LEARNER = "continuous_learner"
LIFECYCLE_WORDS = ("up", "start", "run", "build")

_HAZARD_OPEN = LEARNER_COMPOSE_STATE == "build_refused"
_HAZARD_REASON = ("LB-01/LB-16 (LEARNER_BUILD_HAZARD_DESIGN.md): continuous_learner still builds from the working "
                  "tree; the image pin is owner decision LB-OD-1, applied by the Diff 1 Compose PR and installed by "
                  "WP-G33 (Class B). Switch LEARNER_COMPOSE_STATE to 'pinned' in that PR")


def _strip_comment(line):
    """Drop a YAML comment: '#' at line start or after whitespace, outside quotes."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _comment_of(line):
    stripped = _strip_comment(line)
    rest = line[len(stripped):].lstrip()
    return rest[1:] if rest.startswith("#") else ""


def parse_compose_services(text):
    """Minimal stdlib parser (pattern of ops/provenance/parity_inventory.py compose_images): two-space service keys
    under top-level `services:`, four-space attributes. Returns {service: {attr: value}}; `profiles` becomes a list
    (flow or block style); a nested mapping such as `build:` is present with value ''."""
    services, in_services, svc, block_key = {}, False, None, None
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if not line.startswith(" "):
            in_services, svc, block_key = line.startswith("services:"), None, None
            continue
        if not in_services:
            continue
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if m:
            svc, block_key = m.group(1), None
            services[svc] = {}
            continue
        if svc is None:
            continue
        m = re.match(r"^    ([A-Za-z0-9_<]+):\s*(.*)$", line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            if key == "profiles":
                services[svc][key] = re.findall(r"[\"']?([A-Za-z0-9_.-]+)[\"']?", value.strip("[]")) if value else []
            else:
                services[svc][key] = value.strip("\"'")
            block_key = key if value == "" else None
            continue
        m = re.match(r"^      - [\"']?([A-Za-z0-9_.-]+)[\"']?\s*$", line)
        if m and block_key == "profiles":
            services[svc]["profiles"].append(m.group(1))
    return services


def build_policy_violations(services, state, owner_only, allowed):
    """T2-1 to T2-4 and T2-7 as one pure check. Returns a sorted list of problems (names only, never values)."""
    expected = REVIEWED_STATES[state]
    problems = []
    built = {name for name, attrs in services.items() if "build" in attrs}
    if built != expected["build_services"]:
        problems.append(f"T2-1: services with build: {sorted(built)} != reviewed {sorted(expected['build_services'])}")
    for name in sorted(built):
        profiles = services[name].get("profiles") or []
        if not profiles or not set(profiles) <= expected["build_profiles"]:
            problems.append(f"T2-2: {name} builds without an allow-listed profile")
        if name not in owner_only:
            problems.append(f"T2-3: {name} builds but compose-safe does not refuse it")
        if name in allowed:
            problems.append(f"T2-3: {name} builds but compose-safe allows it")
    for name in sorted(set(services) - built):
        if not services[name].get("image") or services[name].get("pull_policy") != "never":
            problems.append(f"T2-4: {name} has no build: but is not image: + pull_policy: never")
    for name in sorted(set(allowed) - set(services)):
        problems.append(f"T2-4: compose-safe service {name} is not in the Compose file")
    for name in ("continuous_learner", "optimizer"):
        if name not in owner_only:
            problems.append(f"T2-7: {name} is no longer refused by compose-safe")
    return problems


def unsafe_lifecycle_comments(text):
    """T2-6: comment lines that show a `docker compose` lifecycle command without --no-build (build: always)."""
    hits = []
    for n, raw in enumerate(text.splitlines(), 1):
        comment = _comment_of(raw)
        m = re.search(r"docker[ -]compose\b(.*)", comment)
        if not m:
            continue
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", m.group(1))
        if "build" in words or (any(w in words for w in LIFECYCLE_WORDS) and "--no-build" not in m.group(1)):
            hits.append(n)
    return hits


def release_image_refs():
    refs = set()
    for record in sorted((ROOT / "deploy").glob("*/IMAGES.md")):
        refs.update(re.findall(r"`([a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+)`", record.read_text(encoding="utf-8")))
    return refs


def _services():
    return parse_compose_services(COMPOSE_FILE.read_text(encoding="utf-8"))


def test_learner_state_switch_is_a_reviewed_state():
    assert LEARNER_COMPOSE_STATE in REVIEWED_STATES


def test_build_policy_on_the_tracked_compose_file():
    """T2-1, T2-2, T2-3, T2-4, T2-7 against the live compose-safe SERVICES and OWNER_ONLY_SERVICES."""
    services = _services()
    assert {"scanner", "analyzer", "signal_engine", "trade_tracker", "telegram", "optimizer", LEARNER} <= set(services)
    assert build_policy_violations(services, LEARNER_COMPOSE_STATE, cs.OWNER_ONLY_SERVICES, cs.SERVICES) == []


def test_every_build_service_is_refused_by_the_helper_for_every_subcommand():
    """T2-3 by behaviour, not only by set membership."""
    built = sorted(name for name, attrs in _services().items() if "build" in attrs)
    assert built
    for name in built:
        for argv in (["status", name], ["services", name], ["logs", name], ["inspect", name],
                     ["render-hash", name], [name]):
            with pytest.raises(cs.Refused, match="owner authorization"):
                cs.parse_args(argv)


def test_owner_only_services_keep_learner_and_optimizer():
    """T2-7: pinning must never remove the refusal."""
    assert {"continuous_learner", "optimizer"} <= cs.OWNER_ONLY_SERVICES
    assert not ({"continuous_learner", "optimizer"} & set(cs.SERVICES))


@pytest.mark.xfail(_HAZARD_OPEN, strict=True, reason=_HAZARD_REASON)
def test_learner_is_pinned_to_a_recorded_release_image():
    """T2-5 (target state after Diff 1): no build:, image: from a committed release record, pull_policy: never,
    the LB-OD-2 restart outcome, profile unchanged."""
    learner = _services()[LEARNER]
    assert "build" not in learner
    assert learner.get("image") in release_image_refs()
    assert learner.get("pull_policy") == "never"
    assert learner.get("restart") == LEARNER_RESTART_POLICY
    assert learner.get("profiles") == ["learner"]


@pytest.mark.xfail(_HAZARD_OPEN, strict=True, reason=(
    "LB-12 (LEARNER_BUILD_HAZARD_DESIGN.md): the optimizer comment at docker-compose.yml:L181-182 shows "
    "`docker compose up -d optimizer` without --no-build; replaced by the Diff 1 comment hunk (LB-OD-1 PR, "
    "installed by WP-G33)"))
def test_compose_comments_show_no_unsafe_lifecycle_command():
    """T2-6."""
    assert unsafe_lifecycle_comments(COMPOSE_FILE.read_text(encoding="utf-8")) == []


def test_hazard_today_is_exactly_the_documented_one():
    """Keeps the strict xfails honest: today the learner builds with context `.` and the only unsafe comments are
    the two optimizer lines, so the xfails cannot mask a different defect."""
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    learner = parse_compose_services(text)[LEARNER]
    if _HAZARD_OPEN:
        assert "build" in learner and "image" not in learner
        assert learner.get("profiles") == ["learner"]
        hits = unsafe_lifecycle_comments(text)
        assert len(hits) == 2
        lines = text.splitlines()
        assert all("optimizer" in "\n".join(lines[h - 1:h + 2]) for h in hits)


def test_yaml_cross_check_if_available():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    ours = _services()
    assert set(doc["services"]) == set(ours)
    for name, attrs in doc["services"].items():
        assert ("build" in attrs) == ("build" in ours[name]), name
        for key in ("image", "pull_policy", "restart"):
            assert (str(attrs[key]) if key in attrs else None) == ours[name].get(key), (name, key)
        assert list(attrs.get("profiles") or []) == (ours[name].get("profiles") or []), name


# --- the guard logic itself, on synthetic Compose text -------------------

_SYNTHETIC = """\
x-anchor: &a
  read_only: true
services:
  scanner:
    <<: *a
    image: tsb-s:1   # a comment with # inside
    pull_policy: never
  optimizer:
    profiles: ["disabled"]
    build:
      context: .
  continuous_learner:
    build:
      context: .
    profiles:
      - learner
    restart: unless-stopped
#    build:
volumes:
  data:
"""


def test_parser_reads_attributes_profiles_and_ignores_comments():
    svc = parse_compose_services(_SYNTHETIC)
    assert set(svc) == {"scanner", "optimizer", "continuous_learner"}
    assert svc["scanner"]["image"] == "tsb-s:1" and "build" not in svc["scanner"]
    assert svc["optimizer"]["profiles"] == ["disabled"]
    assert svc["continuous_learner"]["profiles"] == ["learner"]
    assert "data" not in svc


def test_policy_flags_a_new_build_on_a_running_service():
    svc = parse_compose_services(_SYNTHETIC.replace("    image: tsb-s:1   # a comment with # inside\n",
                                                    "    build: .\n"))
    problems = build_policy_violations(svc, "build_refused", {"continuous_learner", "optimizer"}, {"scanner": "c"})
    assert any(p.startswith("T2-1") for p in problems)
    assert any("T2-3: scanner builds but compose-safe allows it" == p for p in problems)


def test_policy_flags_missing_profile_missing_pin_and_lost_refusal():
    svc = parse_compose_services(_SYNTHETIC.replace('    profiles: ["disabled"]\n', "")
                                 .replace("    pull_policy: never\n", ""))
    problems = build_policy_violations(svc, "build_refused", {"optimizer"}, {"scanner": "c", "telegram": "t"})
    assert "T2-2: optimizer builds without an allow-listed profile" in problems
    assert "T2-3: continuous_learner builds but compose-safe does not refuse it" in problems
    assert "T2-4: scanner has no build: but is not image: + pull_policy: never" in problems
    assert "T2-4: compose-safe service telegram is not in the Compose file" in problems
    assert "T2-7: continuous_learner is no longer refused by compose-safe" in problems


def test_policy_after_diff1_requires_learner_without_build():
    svc = parse_compose_services(_SYNTHETIC)
    owner = {"continuous_learner", "optimizer"}
    assert any(p.startswith("T2-1") for p in build_policy_violations(svc, "pinned", owner, {"scanner": "c"}))
    pinned = parse_compose_services(_SYNTHETIC.replace(
        "  continuous_learner:\n    build:\n      context: .\n",
        "  continuous_learner:\n    image: tsb-l:1\n    pull_policy: never\n"))
    assert build_policy_violations(pinned, "pinned", owner, {"scanner": "c"}) == []


def test_unsafe_lifecycle_comment_detection():
    text = ("  # restart with `docker compose up -d optimizer`\n"
            "  # canonical: docker compose -p p up -d --no-deps --no-build --pull never --force-recreate svc\n"
            "  # never `docker compose build`\n"
            "  image: x:1   # docker compose run --no-build svc\n"
            "  # docker compose ps is read-only\n")
    assert unsafe_lifecycle_comments(text) == [1, 3]


if __name__ == "__main__":
    unittest.main()
