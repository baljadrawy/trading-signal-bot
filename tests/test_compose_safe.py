"""Tests for ops/compose-safe (read-only Compose helper). Stdlib unittest; subprocess is mocked.

Run: python3 -m unittest tests/test_compose_safe.py -v
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(os.path.dirname(_HERE), "ops", "compose-safe")


def _load():
    loader = importlib.machinery.SourceFileLoader("compose_safe", _SCRIPT)
    spec = importlib.util.spec_from_loader("compose_safe", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


cs = _load()
_REAL_RUN = subprocess.run  # captured before setUp patches subprocess.run

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
        self.assertEqual(set(cs.SUBCOMMANDS), {"status", "services", "logs", "inspect", "render-hash", "health"})

    # --- health: sealed-safe liveness (docs/ops/SEALED_SAFE_MONITORING.md) ---
    def test_health_exact_argv_per_service_and_ok(self):
        self.run_mock.return_value = _completed("running|healthy|0\n")
        rc, out, _ = self.call("health")
        self.assertEqual(rc, 0)
        argvs = [c.args[0] for c in self.run_mock.call_args_list]
        self.assertEqual(argvs, [["docker", "inspect", "--type", "container", "--format", cs.HEALTH_FORMAT, ctr]
                                 for ctr in cs.SERVICES.values()])
        for svc in cs.SERVICES:
            self.assertIn(f"{svc} OK state=running health=healthy restarts=0", out)
        self.assertTrue(out.rstrip().endswith("HEALTH OK alerts=0"))

    def test_health_format_names_no_environment_log_or_data_source(self):
        fields = set(__import__("re").findall(r"\.[A-Z][A-Za-z.]*", cs.HEALTH_FORMAT))
        self.assertEqual(fields, {".State.Status", ".State.Health", ".State.Health.Status", ".RestartCount"})
        for argv in cs.build_argv(self.project, "health", {}):
            joined = " ".join(argv)
            for word in ("logs", "exec", "psql", "Env", "Log", "Config", "evidence"):
                self.assertNotIn(word, joined)

    def test_health_alerts_on_unhealthy_stopped_starting_or_missing_check(self):
        replies = ["running|healthy|0\n", "running|unhealthy|0\n", "exited|unhealthy|3\n",
                   "running|starting|1\n", "running|none|0\n"]
        self.run_mock.side_effect = [_completed(r) for r in replies]
        rc, out, _ = self.call("health")
        self.assertEqual(rc, 1)
        self.assertIn("HEALTH ALERT alerts=4", out)
        self.assertEqual(out.count(" ALERT state="), 4)

    def test_health_fails_closed_and_suppresses_unexpected_output(self):
        replies = [_completed(returncode=1, stderr="Error: No such object: trading_telegram"),
                   _completed("running|healthy|0 TELEGRAM_BOT_TOKEN=supersecret\n"),
                   _completed("ok: age=12s errors=0\n"),
                   _completed(""), OSError("docker not found")]
        self.run_mock.side_effect = replies
        rc, out, err = self.call("health")
        self.assertEqual(rc, 1)
        self.assertIn("HEALTH ALERT alerts=5", out)
        for leaked in ("supersecret", "age=", "No such object"):
            self.assertNotIn(leaked, out + err)

    def test_health_timeout_is_bounded_alerts_and_suppresses_partial_output(self):
        replies = [subprocess.TimeoutExpired(cmd=["docker"], timeout=cs.HEALTH_TIMEOUT_SECONDS,
                                             output="running|healthy|0 TELEGRAM_BOT_TOKEN=supersecret",
                                             stderr="Bearer tok123 daemon stalled")]
        replies += [_completed("running|healthy|0\n")] * (len(cs.SERVICES) - 1)
        self.run_mock.side_effect = replies
        rc, out, err = self.call("health")
        self.assertEqual(rc, 1)
        self.assertIn("telegram ALERT inspect_timeout (output suppressed)", out)
        self.assertIn("HEALTH ALERT alerts=1", out)
        for leaked in ("supersecret", "tok123", "Bearer", "stalled"):
            self.assertNotIn(leaked, out + err)
        self.assertGreater(cs.HEALTH_TIMEOUT_SECONDS, 0)
        for call in self.run_mock.call_args_list:
            self.assertEqual(call.kwargs["timeout"], cs.HEALTH_TIMEOUT_SECONDS)

    def test_health_kills_a_hung_docker_call_and_alerts(self):
        bindir = tempfile.mkdtemp(dir=self.project)
        fake = os.path.join(bindir, "docker")
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\ncase "$*" in *trading_tracker) echo partial-secret; exec sleep 30;; esac\n'
                     'echo "running|healthy|0"\n')
        os.chmod(fake, 0o755)
        self.run_mock.side_effect = _REAL_RUN
        env = {"PATH": bindir + os.pathsep + os.environ.get("PATH", "")}
        with mock.patch.object(cs, "HEALTH_TIMEOUT_SECONDS", 0.5), mock.patch.dict(os.environ, env):
            started = time.monotonic()
            rc, out, err = self.call("health")
            elapsed = time.monotonic() - started
        self.assertEqual(rc, 1)
        self.assertLess(elapsed, 10)
        self.assertIn("trade_tracker ALERT inspect_timeout (output suppressed)", out)
        self.assertIn("HEALTH ALERT alerts=1", out)
        self.assertNotIn("partial-secret", out + err)

    def test_health_takes_no_arguments_and_never_targets_owner_only_services(self):
        self.assert_refused("health", "telegram", contains="takes no arguments")
        self.assert_refused("health", "continuous_learner", contains="separate")
        targets = {argv[-1] for argv in cs.build_argv(self.project, "health", {})}
        self.assertEqual(targets, set(cs.SERVICES.values()))

    def test_nonzero_docker_exit_propagates(self):
        self.run_mock.return_value = _completed(returncode=1, stderr="Bearer tok123\n")
        rc, _, err = self.call("status")
        self.assertEqual(rc, 1)
        self.assertNotIn("tok123", err)


if __name__ == "__main__":
    unittest.main()
