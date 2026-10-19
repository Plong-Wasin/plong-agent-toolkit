"""Behavioral tests use fake OAuth grants/services and isolated config roots."""

from datetime import datetime, timezone
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/account-fallback/skills/claude-accounts/scripts/accounts.py"
spec = importlib.util.spec_from_file_location("claude_accounts", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def grant(name, expires=None):
    return {"accessToken": name, "refreshToken": "refresh-" + name,
            "expiresAt": expires or (time.time() + 3600) * 1000,
            "scopes": ["user:profile", "user:inference"], "subscriptionType": "max"}


def limits(five=10, weekly=20, reset=None):
    return m.normalize_usage({"five_hour": {"utilization": five, "resets_at": reset or time.time() + 3600},
                              "seven_day": {"utilization": weekly, "resets_at": time.time() + 86400}})


class FakeApi:
    def __init__(self):
        self.usages = {"main": limits(), "backup": limits()}
        self.calls = []
        self.fail = set()
        self.refreshes = 0

    def identity(self, credential):
        return {"account": credential["accessToken"].split(":")[0], "organization": "org"}

    def usage(self, credential):
        name = credential["accessToken"].split(":")[0]
        self.calls.append(name)
        if name in self.fail:
            raise m.ApiError(429, 120)
        return self.usages[name]

    def refresh(self, credential):
        self.refreshes += 1
        return grant(credential["accessToken"].split(":")[0] + ":refreshed")


class Accounts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.api = FakeApi()
        self.store = m.Store(self.base / "private", self.api)
        m.private_dir(self.store.root)
        self.target = self.base / "orca profile with spaces"
        m.private_dir(self.target)
        self.write(self.target, "main")
        self.store.add("main", self.target, 1)
        source = self.base / "backup"
        m.private_dir(source)
        self.write(source, "backup")
        self.store.add("backup", source, 2)
        self.clean_env = patch.dict(os.environ, {}, clear=True)
        self.clean_env.start()
        self.store.enable(self.target)

    def tearDown(self):
        self.clean_env.stop()
        self.temp.cleanup()

    def write(self, directory, name, **kwargs):
        m.write_json(directory / ".credentials.json", {"claudeAiOauth": grant(name, **kwargs), "mcpOAuth": {"keep": "connector"}})

    def current(self):
        return m.oauth(m.read_json(self.target / ".credentials.json"))["accessToken"]

    def test_fallback_and_return_after_primary_reset(self):
        self.api.usages["main"] = limits(five=94)
        self.assertIn("main → backup", self.store.select(self.target))
        self.assertEqual(self.current(), "backup")
        main = self.store.account("main")
        main["usage"]["limits"]["five_hour"]["resets_at"] = time.time() - 1
        self.api.usages["main"] = limits(five=1)
        self.assertIn("backup → main", self.store.select(self.target))
        self.assertEqual(self.current(), "main")
        self.assertEqual(self.api.calls.count("main"), 2)

    def test_decimal_thresholds_and_usage_compare_exactly(self):
        self.store.data["thresholds"] = {"five_hour": 92.5, "seven_day": 95}
        self.api.usages["main"] = limits(five=92.4)
        self.assertIsNone(self.store.select(self.target))
        self.store.account("main").pop("usage")
        self.api.usages["main"] = limits(five=92.5)
        self.assertIn("main → backup", self.store.select(self.target))

    def test_decimal_statusline_reading_crosses_decimal_threshold(self):
        self.store.data["thresholds"] = {"five_hour": 92.5, "seven_day": 95}
        self.store.usage("main")
        self.statusline("s1", 92.51)
        self.assertIn("main → backup", self.store.select(self.target))
        self.assertEqual(self.store.account("main")["statusline"]["limits"]["five_hour"]["percent"], 92.51)

    def test_cli_accepts_decimal_thresholds(self):
        result = self.run_cli("configure", "--five-hour", "92.5", "--weekly", "94.75")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["thresholds"], {"five_hour": 92.5, "seven_day": 94.75})
        result = self.run_cli("configure", "--account", "backup", "--five-hour", "88.8")
        self.assertEqual(result.returncode, 0, result.stderr)
        backup = next(a for a in json.loads(result.stdout)["accounts"] if a["name"] == "backup")
        self.assertEqual(backup["thresholds"], {"five_hour": 88.8, "seven_day": 94.75})

    def test_exhausted_primary_is_not_polled_before_its_reset(self):
        self.api.usages["main"] = limits(five=94)
        self.store.select(self.target)
        self.store.account("main")["usage"]["at"] -= 1000
        self.assertIsNone(self.store.select(self.target))
        self.assertEqual(self.current(), "backup")
        self.assertEqual(self.api.calls.count("main"), 1)
        with self.assertRaisesRegex(m.Refused, "main: at threshold until"):
            self.api.usages["backup"] = limits(weekly=99)
            self.store.account("backup").pop("usage")
            self.store.select(self.target)

    def test_independent_weekly_threshold_and_per_account_override(self):
        self.store.data["thresholds"] = {"five_hour": 90, "seven_day": 95}
        self.store.account("main")["thresholds"] = {"seven_day": 80}
        self.api.usages["main"] = limits(five=5, weekly=80)
        self.assertIn("backup", self.store.select(self.target))
        self.assertEqual(self.store.thresholds("main"), {"five_hour": 90, "seven_day": 80})

    def test_exhausted_accounts_fail_closed_without_mutating_credentials(self):
        self.api.usages.update(main=limits(five=93), backup=limits(weekly=95))
        before = (self.target / ".credentials.json").read_bytes()
        with self.assertRaisesRegex(m.Refused, "No eligible"):
            self.store.select(self.target)
        self.assertEqual((self.target / ".credentials.json").read_bytes(), before)

    def test_unknown_usage_backoff_is_account_specific(self):
        self.api.fail.add("main")
        self.store.select(self.target)
        self.store.select(self.target)
        self.assertEqual(self.current(), "backup")
        self.assertEqual(self.api.calls, ["main", "backup"])
        self.assertIn("retry_at", self.store.account("main")["usage"])
        self.assertNotIn("retry_at", self.store.account("backup")["usage"])

    def test_refresh_is_archived_and_mcp_state_survives_round_trip(self):
        self.write(self.target, "main:native-refresh")
        self.api.usages["main"] = limits(99)
        self.store.select(self.target)
        self.assertEqual(self.store.credential("main")["accessToken"], "main:native-refresh")
        self.assertEqual(m.read_json(self.target / ".credentials.json")["mcpOAuth"], {"keep": "connector"})
        self.api.usages["main"] = limits()
        self.store.account("main").pop("usage")
        self.store.select(self.target)
        self.assertEqual(self.current(), "main:native-refresh")

    def test_external_login_is_not_silently_archived_as_previous_account(self):
        self.write(self.target, "someone-else")
        with self.assertRaisesRegex(m.Refused, "another account"):
            self.store.select(self.target)
        self.assertEqual(self.store.credential("main")["accessToken"], "main")
        self.assertEqual(self.current(), "someone-else")

    def test_expired_saved_account_refreshes_before_reuse(self):
        self.store.save_credential("backup", grant("backup", (time.time() - 20) * 1000))
        self.api.usages["main"] = limits(99)
        self.store.select(self.target)
        self.assertEqual(self.current(), "backup:refreshed")
        self.assertEqual(self.api.refreshes, 1)
        self.assertEqual(self.store.credential("backup")["accessToken"], self.current())

    def profile(self, directory, name, **extra):
        m.write_json(directory / ".claude.json", {
            "oauthAccount": {"accountUuid": name, "organizationUuid": "org", "emailAddress": name + "@example.com"},
            "projects": {"keep": True}, **extra})

    def identity(self):
        return m.read_json(self.target / ".claude.json").get("oauthAccount")

    def test_switch_moves_cached_identity_with_credential(self):
        source = self.base / "backup"
        self.profile(self.target, "main")
        self.profile(source, "backup")
        self.store.add("main", self.target, 1)
        self.store.add("backup", source, 2)
        self.api.usages["main"] = limits(five=94)
        self.store.select(self.target)
        self.assertEqual(self.identity()["emailAddress"], "backup@example.com")
        self.assertEqual(m.read_json(self.target / ".claude.json")["projects"], {"keep": True})
        main = self.store.account("main")
        main["usage"]["limits"]["five_hour"]["resets_at"] = time.time() - 1
        self.api.usages["main"] = limits(five=1)
        self.store.select(self.target)
        self.assertEqual(self.identity()["emailAddress"], "main@example.com")

    def test_switch_without_snapshot_drops_stale_identity(self):
        self.profile(self.target, "main")
        self.api.usages["main"] = limits(five=94)
        self.store.select(self.target)
        self.assertEqual(self.current(), "backup")
        self.assertIsNone(self.identity())
        self.assertEqual(m.read_json(self.target / ".claude.json")["projects"], {"keep": True})

    def test_identity_of_another_account_is_not_archived(self):
        source = self.base / "backup"
        self.profile(source, "someone-else")
        self.store.add("backup", source, 2)
        self.assertFalse((self.store.home("backup") / "oauth-account.json").exists())

    def test_default_profile_uses_home_level_global_config(self):
        with patch.object(m.Path, "home", return_value=self.base):
            default = (self.base / ".claude").resolve()
            self.assertEqual(m.global_config(default), self.base / ".claude.json")
            m.private_dir(default)
            (default / ".claude.json").write_text("{}")
            self.assertEqual(m.global_config(default), default / ".claude.json")
        self.assertEqual(m.global_config(self.target), self.target / ".claude.json")

    def test_refresh_of_bound_account_publishes_rotated_grant_to_target(self):
        self.write(self.target, "main", expires=(time.time() - 20) * 1000)
        self.store.save_credential("main", m.oauth(m.read_json(self.target / ".credentials.json")))
        self.store.sync_target(self.target)
        self.store.refresh("main")
        self.assertEqual(self.current(), "main:refreshed")
        self.assertEqual(self.store.credential("main")["accessToken"], self.current())

    def test_native_refresh_lock_refuses_swap_and_preserves_existing_lock(self):
        self.api.usages["main"] = limits(99)
        lock = self.target / ".oauth_refresh.lock"
        lock.mkdir()
        with self.assertRaisesRegex(m.Refused, "busy"):
            self.store.select(self.target)
        self.assertEqual(self.current(), "main")
        self.assertTrue(lock.is_dir())
        self.assertFalse(Path(str(self.target) + ".lock").exists())

    def test_server_limit_cooldown_prevents_immediate_bounce(self):
        self.store.select(self.target, failed=True)
        self.assertEqual(self.current(), "backup")
        self.assertIsNone(self.store.select(self.target))
        self.store.account("main")["blocked_until"] = time.time() - 1
        self.store.select(self.target)
        self.assertEqual(self.current(), "main")

    def test_disabled_account_is_skipped_even_if_first(self):
        self.store.account("main")["enabled"] = False
        self.store.select(self.target)
        self.assertEqual(self.current(), "backup")
        self.assertNotIn("main", self.api.calls)

    def test_private_files_and_status_never_expose_tokens(self):
        self.store.select(self.target)
        status = json.dumps(self.store.status(self.target))
        self.assertNotIn("accessToken", status)
        self.assertNotIn("refreshToken", status)
        self.assertNotIn("refresh-main", status)
        for path in (self.store.path, self.store.home("main") / ".credentials.json", self.target / ".credentials.json"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.home("main").stat().st_mode & 0o777, 0o700)

    def test_auth_override_refuses_activation(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "fake-env-token"}):
            with self.assertRaisesRegex(m.Refused, "overrides"):
                self.store.enable(self.target)

    def test_symlink_credentials_are_preserved_and_refused(self):
        path = self.target / ".credentials.json"
        original = self.base / "original.json"
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaisesRegex(m.Refused, "symbolic"):
            self.store.select(self.target)
        self.assertTrue(path.is_symlink())

    def test_same_identity_cannot_be_registered_twice(self):
        with self.assertRaisesRegex(m.Refused, "already saved"):
            self.store.add("duplicate", self.target, 3)

    def test_api_backoff_overrides_previously_cached_low_usage(self):
        self.store.usage("main")
        self.api.fail.add("main")
        with self.assertRaises(m.ApiError):
            self.store.usage("main", force=True)
        self.store.select(self.target)
        self.assertEqual(self.current(), "backup")
        self.assertEqual(self.api.calls.count("main"), 2)

    def test_disabled_profile_is_not_modified_by_background_refresh_or_relogin(self):
        self.store.data["targets"][str(self.target)]["enabled"] = False
        original = (self.target / ".credentials.json").read_bytes()
        self.store.save_credential("main", grant("main", (time.time() - 20) * 1000))
        self.store.refresh("main")
        self.assertEqual((self.target / ".credentials.json").read_bytes(), original)
        source = self.base / "new-login"
        m.private_dir(source)
        self.write(source, "main:new-login")
        self.store.add("main", source, 1)
        self.assertEqual((self.target / ".credentials.json").read_bytes(), original)

    def test_native_refresh_is_shared_across_enabled_profiles_even_with_cached_usage(self):
        second = self.base / "terminal profile"
        m.private_dir(second)
        self.write(second, "main")
        self.store.enable(second)
        self.store.usage("main")
        self.write(self.target, "main:newest", expires=(time.time() + 7200) * 1000)
        self.store.select(second)
        self.assertEqual(self.store.credential("main")["accessToken"], "main:newest")
        self.assertEqual(m.oauth(m.read_json(second / ".credentials.json"))["accessToken"], "main:newest")
        self.assertEqual(self.api.calls.count("main"), 1)

    def test_older_profile_cannot_overwrite_later_archived_grant(self):
        newer = grant("main:newer", (time.time() + 7200) * 1000)
        self.store.save_credential("main", newer)
        self.write(self.target, "main:older", expires=(time.time() + 1000) * 1000)
        self.store.select(self.target)
        self.assertEqual(self.current(), "main:newer")
        self.assertEqual(self.store.credential("main"), newer)

    def test_stale_empty_native_locks_can_recover_after_killed_hook(self):
        for lock in (self.target / ".oauth_refresh.lock", Path(str(self.target) + ".lock")):
            lock.mkdir()
            os.utime(lock, (time.time() - 120, time.time() - 120))
        self.api.usages["main"] = limits(99)
        self.store.select(self.target)
        self.assertEqual(self.current(), "backup")
        self.assertFalse((self.target / ".oauth_refresh.lock").exists())

    def test_replaced_native_lock_prevents_writes_and_is_not_released(self):
        path = self.target / ".oauth_refresh.lock"
        moved = self.target / ".original-lock"
        original = (self.target / ".credentials.json").read_bytes()
        with m.native_locks([self.target]):
            path.rename(moved)
            path.mkdir()
            with self.assertRaisesRegex(m.Refused, "lock changed"):
                self.write(self.target, "main:should-not-be-written")
        self.assertTrue(path.is_dir())
        self.assertEqual((self.target / ".credentials.json").read_bytes(), original)

    def test_manager_recovery_checks_full_command_including_global_target_option(self):
        def payload(command):
            return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
        self.assertTrue(m.management_call(payload(f'python3 "{SCRIPT}" --config-dir "/profile with spaces" disable')))
        self.assertFalse(m.management_call(payload(f'python3 "{SCRIPT}" status; echo unrelated')))
        self.assertFalse(m.management_call(payload(f'python3 "{SCRIPT}" status && echo unrelated')))
        self.assertFalse(m.management_call(payload(f'python3 "{SCRIPT}" hook')))

    def test_login_is_preserved_if_post_browser_verification_is_temporarily_unavailable(self):
        args = m.parser().parse_args(["login", "third", "--priority", "3"])

        def native(command, env, cwd):
            self.write(Path(cwd), "third")
            return subprocess.CompletedProcess(command, 0)

        with patch.object(m.shutil, "which", return_value="/fake/claude"), patch.object(m.subprocess, "run", side_effect=native), patch.object(self.api, "identity", side_effect=m.ApiError(429)):
            with self.assertRaisesRegex(m.Refused, "Login profile preserved"):
                m.login(self.store, args)
        preserved = list(self.store.root.glob("login-*"))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(m.oauth(m.read_json(preserved[0] / ".credentials.json"))["accessToken"], "third")
        self.assertNotIn("third", self.store.data["accounts"])

    def test_relogin_updates_bound_copy_without_losing_connector_credentials(self):
        source = self.base / "new login"
        m.private_dir(source)
        self.write(source, "main:new-login")
        self.store.add("main", source, 1)
        self.assertEqual(self.current(), "main:new-login")
        self.assertEqual(m.read_json(self.target / ".credentials.json")["mcpOAuth"], {"keep": "connector"})

    def test_relogin_does_not_overwrite_a_profile_changed_to_another_identity(self):
        self.write(self.target, "foreign")
        source = self.base / "new login"
        m.private_dir(source)
        self.write(source, "main:new-login")
        with self.assertRaisesRegex(m.Refused, "changed accounts"):
            self.store.add("main", source, 1)
        self.assertEqual(self.current(), "foreign")
        self.assertEqual(self.store.credential("main")["accessToken"], "main")

    def test_login_delegates_to_native_cli_in_isolated_directory(self):
        args = m.parser().parse_args(["login", "third", "--priority", "3", "--email", "example@example.com"])
        original = (self.target / ".credentials.json").read_bytes()

        def native(command, env, cwd):
            self.assertEqual(command, ["/fake/claude", "auth", "login", "--claudeai", "--email", "example@example.com"])
            self.assertNotEqual(env["CLAUDE_CONFIG_DIR"], str(self.target))
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], cwd)
            self.assertNotIn("ORCA_CLAUDE_PROFILE_POINTER", env)
            self.write(Path(cwd), "third")
            return subprocess.CompletedProcess(command, 0)

        with patch.object(m.shutil, "which", return_value="/fake/claude"), patch.object(m.subprocess, "run", side_effect=native), patch.dict(os.environ, {"ORCA_CLAUDE_PROFILE_POINTER": "/fake/pointer"}):
            m.login(self.store, args)
        self.assertEqual(self.store.credential("third")["accessToken"], "third")
        self.assertEqual((self.target / ".credentials.json").read_bytes(), original)
        self.assertEqual(list(self.store.root.glob("login-*")), [])

    def run_cli(self, *args, input=None, script=SCRIPT):
        env = dict(os.environ, HOME=str(self.base), CLAUDE_CONFIG_DIR=str(self.target), CLAUDE_ACCOUNT_FALLBACK_HOME=str(self.store.root))
        return subprocess.run([sys.executable, str(script), *args], input=input, text=True, capture_output=True, env=env, cwd=self.base)

    def statusline(self, session, five, started=None, account_age=0):
        transcript = self.base / f"{session}.jsonl"
        stamp = datetime.fromtimestamp(started or time.time(), timezone.utc).isoformat()
        transcript.write_text(json.dumps({"type": "mode"}) + "\n" + json.dumps({"timestamp": stamp}) + "\n")
        self.store.data.setdefault("statusline", {})[str(self.target)] = {"previous": None, "installed_at": 0}
        m.record_statusline(self.store, self.target, {
            "session_id": session, "transcript_path": str(transcript),
            "rate_limits": {"five_hour": {"used_percentage": five, "resets_at": time.time() + 3600},
                            "seven_day": {"used_percentage": 20, "resets_at": time.time() + 86400}}})

    def test_fresh_statusline_reading_replaces_usage_request(self):
        self.store.usage("main")
        self.store.account("main")["usage"]["at"] -= 100
        self.statusline("s1", 94)
        self.assertIn("main → backup", self.store.select(self.target))
        self.assertEqual(self.api.calls.count("main"), 1)
        self.assertEqual(self.store.account("main")["statusline"]["limits"]["five_hour"]["percent"], 94)

    def test_statusline_reset_time_returns_to_primary_after_one_confirmation(self):
        self.store.usage("main")
        self.statusline("s1", 94)
        self.assertIn("main → backup", self.store.select(self.target))
        # Only the statusline reading proves main is exhausted now.
        self.store.account("main").pop("usage")
        self.store.select(self.target)
        self.assertEqual((self.current(), self.api.calls.count("main")), ("backup", 1))
        self.store.account("main")["statusline"]["limits"]["five_hour"]["resets_at"] = time.time() - 1
        self.api.usages["main"] = limits(five=0)
        self.assertIn("backup → main", self.store.select(self.target))
        self.assertEqual(self.api.calls.count("main"), 2)

    def test_statusline_keeps_model_specific_weekly_limit_from_api(self):
        self.api.usages["main"] = m.normalize_usage({
            "five_hour": {"utilization": 10, "resets_at": time.time() + 3600},
            "seven_day": {"utilization": 10, "resets_at": time.time() + 86400},
            "seven_day_opus": {"utilization": 99, "resets_at": time.time() + 86400}})
        self.store.usage("main")
        self.statusline("s1", 5)
        self.assertEqual(self.store.usage("main")["seven_day_opus"]["percent"], 99)

    def test_session_started_before_switch_is_not_attributed_to_new_account(self):
        self.api.usages["main"] = limits(five=94)
        self.store.select(self.target)
        self.store.usage("backup")
        self.store.account("backup")["usage"]["at"] -= 100
        # This session was open with main's credential before the switch.
        self.statusline("old", 1, started=time.time() - 3600)
        self.store.usage("backup")
        self.assertEqual(self.api.calls.count("backup"), 2)
        self.assertNotIn("statusline", self.store.account("backup"))

    def age_statusline(self, session, seconds):
        old = time.time() - seconds
        os.utime(self.base / f"{session}.jsonl", (old, old))

    def test_stale_statusline_and_due_api_reading_calls_api(self):
        self.store.usage("main")
        self.store.account("main")["usage"]["at"] -= 100
        self.statusline("s1", 94)
        self.age_statusline("s1", 61)
        self.store.select(self.target)
        self.assertEqual(self.api.calls.count("main"), 2)
        self.assertEqual(self.current(), "main")

    def test_newer_of_stale_statusline_and_cached_api_reading_wins(self):
        self.store.data["cache_ttl"] = 180
        self.store.usage("main")
        self.store.account("main")["usage"]["at"] -= 150
        # Idle for 90 seconds, but its last response came after the API call.
        self.statusline("s1", 94)
        self.age_statusline("s1", 90)
        self.assertIn("main → backup", self.store.select(self.target))
        self.assertEqual(self.api.calls.count("main"), 1)

    def test_older_statusline_does_not_override_cached_api_reading(self):
        self.store.data["cache_ttl"] = 180
        self.statusline("s1", 94)
        self.age_statusline("s1", 90)
        self.store.usage("main")
        self.assertIsNone(self.store.select(self.target))
        self.assertEqual(self.current(), "main")
        self.assertEqual(self.api.calls.count("main"), 1)

    def test_configured_intervals_are_validated_and_reported(self):
        result = self.run_cli("configure", "--cache-ttl", "180", "--statusline-fresh", "45", "--api-max-age", "900")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual((output["cache_ttl"], output["statusline_fresh"], output["api_max_age"]), (180, 45, 900))
        self.assertNotEqual(self.run_cli("configure", "--statusline-fresh", "601").returncode, 0)
        self.assertNotEqual(self.run_cli("configure", "--account", "main", "--cache-ttl", "30").returncode, 0)

    def test_statusline_reading_with_passed_reset_is_unusable(self):
        self.assertIsNone(m.statusline_usage({"five_hour": {"used_percentage": 50, "resets_at": time.time() - 1},
                                              "seven_day": {"used_percentage": 1}}, time.time()))
        self.assertIsNone(m.statusline_usage({"five_hour": {"used_percentage": 50}}, time.time()))

    def test_cli_statusline_install_wraps_and_uninstall_restores(self):
        previous = {"type": "command", "command": "printf inner:; cat >/dev/null", "padding": 1}
        m.write_json(self.target / "settings.json", {"statusLine": previous, "keep": True})
        result = self.run_cli("statusline", "install")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = m.read_json(self.target / "settings.json")
        self.assertIn("statusline run", settings["statusLine"]["command"])
        self.assertEqual(settings["statusLine"]["padding"], 1)
        payload = json.dumps({"session_id": "abc", "rate_limits": {
            "five_hour": {"used_percentage": 3, "resets_at": time.time() + 3600},
            "seven_day": {"used_percentage": 4, "resets_at": time.time() + 86400}}})
        env = dict(os.environ, HOME=str(self.base), CLAUDE_CONFIG_DIR=str(self.target), CLAUDE_ACCOUNT_FALLBACK_HOME=str(self.store.root))
        rendered = subprocess.run(settings["statusLine"]["command"], shell=True, input=payload, text=True,
                                  capture_output=True, env=env, cwd=self.base)
        self.assertEqual(rendered.stdout, "inner:")
        snapshot = m.read_json(self.store.root / "statusline/abc.json")
        self.assertEqual((snapshot["account"], snapshot["rate_limits"]["five_hour"]["used_percentage"]), ("main", 3))
        result = self.run_cli("statusline", "uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(m.read_json(self.target / "settings.json"), {"statusLine": previous, "keep": True})

    def test_cli_sets_order_and_thresholds_without_network_or_tokens(self):
        result = self.run_cli("configure", "--five-hour", "88", "--weekly", "91")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("order", "backup", "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual([a["name"] for a in output["accounts"]], ["backup", "main"])
        self.assertEqual(output["thresholds"], {"five_hour": 88, "seven_day": 91})
        result = self.run_cli("configure", "--weekly", "101")
        self.assertNotEqual(result.returncode, 0)

    def test_relocated_package_hooks_block_with_cached_exhausted_accounts(self):
        folder = self.base / "relocated plugin"
        shutil.copytree(ROOT / "plugins/account-fallback", folder)
        self.api.usages.update(main=limits(99), backup=limits(99))
        for name in ("main", "backup"):
            self.store.usage(name)
        manifest = json.loads((folder / ".claude-plugin/plugin.json").read_text())
        env = dict(os.environ, HOME=str(self.base), CLAUDE_CONFIG_DIR=str(self.target), CLAUDE_ACCOUNT_FALLBACK_HOME=str(self.store.root), CLAUDE_PLUGIN_ROOT=str(folder))
        # Make any accidental network access in the relocated child fail this
        # test, including StopFailure's normal forced usage re-check.
        site = self.base / "network guard"
        site.mkdir()
        (site / "sitecustomize.py").write_text(
            "import urllib.request\n"
            "def deny(*args, **kwargs):\n"
            "    raise AssertionError('Tests must not call live OAuth services')\n"
            "urllib.request.OpenerDirector.open = deny\n"
        )
        env["PYTHONPATH"] = str(site)
        for event in ("UserPromptSubmit", "PreToolUse", "StopFailure"):
            if event == "StopFailure":
                self.store.account("main")["usage"]["retry_at"] = time.time() + 120
                self.store.save()
            command = manifest["hooks"][event][0]["hooks"][0]["command"]
            result = subprocess.run(command, shell=True, input=json.dumps({"hook_event_name": event, "error": "rate_limit"}), env=env, cwd=self.base, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            if event == "UserPromptSubmit":
                self.assertEqual(output["decision"], "block")
            elif event == "PreToolUse":
                self.assertFalse(output["continue"])
                self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
            else:
                self.assertIn("systemMessage", output)


class UsageParsing(unittest.TestCase):
    def test_null_window_is_unused_but_missing_window_is_unknown(self):
        value = m.normalize_usage({"five_hour": None, "seven_day": None})
        self.assertEqual([x["percent"] for x in value.values()], [0, 0])
        with self.assertRaises(m.Refused):
            m.normalize_usage({"five_hour": None})

    def test_model_specific_weekly_limit_and_locked_reason(self):
        value = m.normalize_usage({"five_hour": None, "seven_day": None, "seven_day_opus": {"utilization": 5, "locked_reason": "limit"}})
        self.assertEqual(value["seven_day_opus"]["percent"], 100)

    def test_invalid_percent_is_not_treated_as_zero(self):
        for invalid in (-1, 101, True, "90", float("nan")):
            with self.subTest(value=invalid), self.assertRaises(m.Refused):
                m.normalize_usage({"five_hour": {"utilization": invalid}, "seven_day": None})


class OAuthHttpIntegration(unittest.TestCase):
    """Exercise the real HTTP client against a local fixture service only."""

    def setUp(self):
        self.state = {"requests": [], "limited": set(), "five_hour": {"main": 99, "backup": 1}, "bad_refresh": False}
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, value, status=200, **headers):
                data = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for key, value in headers.items():
                    self.send_header(key.replace("_", "-"), str(value))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                authorization = self.headers.get("Authorization", "")
                name = authorization.removeprefix("Bearer ").split(":")[0]
                state["requests"].append((self.path, authorization))
                if self.path == "/redirect":
                    self.respond({}, 302, Location="/sink")
                elif self.path == "/profile":
                    self.respond({"account": {"uuid": name}, "organization": {"uuid": "org"}})
                elif name in state["limited"]:
                    self.respond({"error": "private-response-must-not-be-printed"}, 429, Retry_After=120)
                else:
                    self.respond({"five_hour": {"utilization": state["five_hour"][name], "resets_at": time.time() + 3600}, "seven_day": None})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                state["requests"].append((self.path, body))
                name = body["refresh_token"].removeprefix("refresh-").split(":")[0]
                self.respond({"access_token": name + ":renewed", "refresh_token": "refresh-" + name + ":renewed", "expires_in": -1 if state["bad_refresh"] else 3600})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.urls = patch.multiple(m, API=self.url + "/", TOKEN_URL=self.url + "/token")
        self.urls.start()

    def tearDown(self):
        self.urls.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_http_profile_usage_refresh_and_file_switch_work_together(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            base = Path(directory)
            store = m.Store(base / "private", m.Api())
            m.private_dir(store.root)
            for name in ("main", "backup"):
                profile = base / name
                m.private_dir(profile)
                m.write_json(profile / ".credentials.json", {"claudeAiOauth": grant(name), "mcpOAuth": {"keep": name}})
                store.add(name, profile, 1 if name == "main" else 2)
            store.enable(base / "main")
            expired = store.credential("backup")
            expired["expiresAt"] = (time.time() - 20) * 1000
            store.save_credential("backup", expired)
            # This archived grant was verified when imported; time passing
            # does not make its account identity unknown.
            store.account("backup")["verified"] = m.digest(expired)
            store.select(base / "main")
            self.assertEqual(m.oauth(m.read_json(base / "main/.credentials.json"))["accessToken"], "backup:renewed")
            self.assertEqual(m.read_json(base / "main/.credentials.json")["mcpOAuth"], {"keep": "main"})
            requests = self.state["requests"]
            exchanges = [body for path, body in requests if path == "/token"]
            self.assertEqual(len(exchanges), 1)
            self.assertEqual(exchanges[0]["client_id"], m.CLIENT_ID)
            self.assertIn(("/usage", "Bearer backup:renewed"), requests)

    def test_http_backoff_does_not_expose_response_body(self):
        self.state["limited"].add("main")
        with self.assertRaises(m.ApiError) as caught:
            m.Api().usage(grant("main"))
        self.assertEqual(caught.exception.retry, 120)
        self.assertNotIn("private-response", str(caught.exception))

    def test_http_redirect_is_not_followed_with_bearer_credentials(self):
        with self.assertRaises(m.ApiError):
            m.Api().request(self.url + "/redirect", token="main")
        self.assertEqual([path for path, _ in self.state["requests"]], ["/redirect"])

    def test_malformed_refresh_response_is_not_adopted(self):
        self.state["bad_refresh"] = True
        with self.assertRaisesRegex(m.Refused, "incomplete"):
            m.Api().refresh(grant("main"))


if __name__ == "__main__":
    unittest.main()
