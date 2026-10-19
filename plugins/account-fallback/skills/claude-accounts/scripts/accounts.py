#!/usr/bin/env python3
"""Manage Claude subscription accounts and file-based usage fallback (Linux)."""

import argparse
from contextlib import contextmanager, redirect_stderr
from datetime import datetime
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


API = "https://api.anthropic.com/api/oauth/"
# Claude Code 2.1.300's public OAuth client and token endpoint. These internal
# endpoints/lock conventions are compatibility dependencies, not a plugin API.
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
DEFAULTS = {"five_hour": 93, "seven_day": 95}
# Seconds, configurable with `configure`:
#   cache_ttl         minimum gap between usage API calls for one account
#   statusline_fresh  a statusline reading this recent makes an API call unnecessary
#                     (an idle session re-renders old numbers, so older ones only
#                     compete with the API cache on age)
#   api_max_age       oldest API reading whose model-specific weekly limits are
#                     reused next to a fresh statusline reading
TIMING = {"cache_ttl": 60, "statusline_fresh": 60, "api_max_age": 600}
PLAIN_LIMITS = ("five_hour", "session", "seven_day", "weekly_all")
_NATIVE_LOCKS = []
AUTH_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_BASE_URL", "CLAUDE_CODE_CUSTOM_OAUTH_URL", "CLAUDE_LOCAL_OAUTH_API_BASE",
    "CLAUDE_SECURESTORAGE_CONFIG_DIR",
)


class Refused(Exception):
    pass


class ApiError(Refused):
    def __init__(self, status=0, retry=30):
        self.status, self.retry = status, retry
        super().__init__(f"OAuth service unavailable (HTTP {status or 'network'}); retry later")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path, default=None):
    if path.is_symlink():
        raise Refused("Refusing a symbolic-link credential/configuration file")
    if not path.exists():
        if default is not None:
            return default
        raise Refused("Credential/configuration file is missing; import or log in first")
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError):
        raise Refused("Credential/configuration JSON could not be read") from None
    if not isinstance(value, dict):
        raise Refused("Expected a JSON object")
    return value


def private_dir(path):
    if path.is_symlink():
        raise Refused("Refusing a symbolic-link private directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def write_json(path, value):
    check_locks()
    if path.is_symlink():
        raise Refused("Refusing to replace a symbolic-link file")
    fd, temporary = tempfile.mkstemp(prefix=".fallback-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def oauth(document):
    value = document.get("claudeAiOauth")
    if not isinstance(value, dict) or not isinstance(value.get("accessToken"), str) or not value["accessToken"]:
        raise Refused("No subscription OAuth credential; run login or import")
    if not value.get("subscriptionType"):
        raise Refused("Credential is not marked as a subscription login; log in with a subscription account")
    return value


def active_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser().resolve()


def global_config(directory):
    """Claude Code's global config, which caches the signed-in identity (oauthAccount).

    With CLAUDE_CONFIG_DIR it lives inside that directory; the default
    ~/.claude profile keeps it beside the directory as ~/.claude.json.
    """
    inside = directory / ".claude.json"
    if not inside.exists() and directory == (Path.home() / ".claude").resolve():
        return Path.home() / ".claude.json"
    return inside


def check_file_auth(directory):
    if sys.platform != "linux":
        raise Refused("Credential-file fallback currently supports Linux/WSL only")
    if any(os.environ.get(key) for key in AUTH_ENV) or "CLAUDE_SECURESTORAGE_CONFIG_DIR" in os.environ:
        raise Refused("Environment authentication/routing overrides file login; use a subscription file-auth session")
    # apiKeyHelper can override subscription auth without an environment token.
    settings = [directory / "settings.json", Path.cwd() / ".claude/settings.json",
                Path.cwd() / ".claude/settings.local.json", Path("/etc/claude-code/managed-settings.json")]
    for path in settings:
        if path.exists() and read_json(path).get("apiKeyHelper"):
            raise Refused("apiKeyHelper overrides file authentication; use a subscription file-auth session")


def epoch(value):
    try:
        number = float(value) if isinstance(value, (int, float)) else datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, AttributeError):
        return None


def normalize_usage(document):
    limits = {}
    for key, entry in document.items():
        kind = "five_hour" if key in ("five_hour", "session") else "seven_day" if key.startswith("seven_day") or key.startswith("weekly") else None
        if not kind:
            continue
        if entry is None:
            limits[key] = {"kind": kind, "percent": 0, "resets_at": None}
        elif isinstance(entry, dict):
            percent = entry.get("utilization")
            if entry.get("locked_reason") is not None:
                percent = 100
            if isinstance(percent, (int, float)) and not isinstance(percent, bool) and math.isfinite(percent) and 0 <= percent <= 100:
                limits[key] = {"kind": kind, "percent": percent, "resets_at": epoch(entry.get("resets_at"))}
    for entry in document.get("limits", []) or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("kind", "")
        kind = "five_hour" if key in ("session", "five_hour") else "seven_day" if key.startswith(("weekly", "seven_day")) else None
        percent = entry.get("percent")
        if kind and isinstance(percent, (int, float)) and not isinstance(percent, bool) and math.isfinite(percent) and 0 <= percent <= 100:
            limits[key] = {"kind": kind, "percent": percent, "resets_at": epoch(entry.get("resets_at"))}
    if {entry["kind"] for entry in limits.values()} != set(DEFAULTS):
        raise Refused("Usage response does not contain both 5-hour and weekly limits")
    return limits


def statusline_usage(document, now):
    """5-hour/weekly limits from the statusline's rate_limits, or None.

    Claude Code reads them off its own model responses, so they cost no
    request, but carry no model-specific weekly limits. A window whose reset
    time has passed belongs to the previous window and makes the reading unusable.
    """
    if not isinstance(document, dict):
        return None
    limits = {}
    for kind in DEFAULTS:
        entry = document.get(kind)
        if not isinstance(entry, dict):
            return None
        percent, resets = entry.get("used_percentage"), epoch(entry.get("resets_at"))
        if (not isinstance(percent, (int, float)) or isinstance(percent, bool) or
                not math.isfinite(percent) or not 0 <= percent <= 100 or (resets is not None and resets <= now)):
            return None
        limits[kind] = {"kind": kind, "percent": percent, "resets_at": resets}
    return limits


def newest(limits, at, live):
    """API limits, with the 5-hour/weekly ones replaced by a newer statusline reading."""
    if not live or live[0] < at:
        return limits
    other = {key: item for key, item in limits.items() if key not in PLAIN_LIMITS}
    return {**other, **live[1]}


def mtime(path):
    try:
        return Path(path).stat().st_mtime
    except (OSError, TypeError, ValueError):
        return 0


def transcript_started(path):
    """Time of the first timestamped transcript entry, or None."""
    try:
        with open(path, "rb") as stream:
            for line in stream.read(65536).splitlines():
                try:
                    started = epoch(json.loads(line).get("timestamp"))
                except (ValueError, AttributeError):
                    continue
                if started is not None:
                    return started
    except (OSError, TypeError, ValueError):
        pass
    return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self, deadline=None):
        self.deadline = deadline or time.monotonic() + 20

    def request(self, url, token=None, body=None):
        check_locks()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ApiError()
        headers = {"Content-Type": "application/json", "User-Agent": "claude-account-fallback/1", "anthropic-beta": "oauth-2025-04-20"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers, data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=min(4, remaining)) as response:
                value = json.load(response)
            if not isinstance(value, dict):
                raise ApiError()
            return value
        except urllib.error.HTTPError as error:
            retry = error.headers.get("Retry-After", "60" if error.code == 429 else "30")
            error.close()
            try:
                retry = max(1, min(3600, int(retry)))
            except ValueError:
                retry = 60
            # Never include response bodies, request headers, or token endpoint payloads.
            raise ApiError(error.code, retry) from None
        except (OSError, ValueError):
            raise ApiError() from None

    def identity(self, credential):
        profile = self.request(API + "profile", credential["accessToken"])
        account, organization = profile.get("account", {}), profile.get("organization", {})
        if not account.get("uuid") or not organization.get("uuid"):
            raise Refused("OAuth profile did not provide account and organization identity")
        return {"account": account["uuid"], "organization": organization["uuid"]}

    def usage(self, credential):
        return normalize_usage(self.request(API + "usage", credential["accessToken"]))

    def refresh(self, credential):
        if not credential.get("refreshToken"):
            raise Refused("Saved account has no refresh token; log in again")
        result = self.request(TOKEN_URL, body={
            "grant_type": "refresh_token", "refresh_token": credential["refreshToken"],
            "client_id": credential.get("clientId") or CLIENT_ID,
            "scope": " ".join(credential.get("scopes", [])),
        })
        token, expires = result.get("access_token"), result.get("expires_in")
        refresh_token = result.get("refresh_token") or credential["refreshToken"]
        if (not isinstance(token, str) or not token or not isinstance(refresh_token, str) or
                not isinstance(expires, (int, float)) or isinstance(expires, bool) or
                not math.isfinite(expires) or expires <= 0):
            raise Refused("OAuth refresh response is incomplete; log in again")
        updated = dict(credential, accessToken=token, refreshToken=refresh_token,
                       expiresAt=int((time.time() + expires) * 1000))
        if isinstance(result.get("scope"), str):
            updated["scopes"] = result["scope"].split()
        if isinstance(result.get("refresh_token_expires_in"), (int, float)):
            updated["refreshTokenExpiresAt"] = int((time.time() + result["refresh_token_expires_in"]) * 1000)
        return updated


def lock_identity(path):
    stat = path.lstat()
    return stat.st_dev, stat.st_ino, stat.st_ctime_ns


def check_locks():
    for path, identity, started in _NATIVE_LOCKS:
        try:
            valid = not path.is_symlink() and lock_identity(path) == identity and time.monotonic() - started < 45
        except OSError:
            valid = False
        if not valid:
            raise Refused("OAuth refresh lock changed or expired; retry without writing credentials")


@contextmanager
def native_locks(directories):
    """Participate in 2.1.300's proper-lockfile mkdir locks; never steal one.

    Hold for one bounded exchange/write only (under the native 60-second stale
    timeout). These private conventions may change in later Claude versions.
    """
    acquired = []
    try:
        for directory in sorted(set(directories), key=str):
            for path in (directory / ".oauth_refresh.lock", Path(str(directory) + ".lock")):
                try:
                    path.mkdir(mode=0o700)
                except FileExistsError:
                    # Match proper-lockfile's stale timeout. A killed hook can
                    # leave empty lock directories; never remove an active,
                    # nonempty or symlinked lock, and never wait inside a hook.
                    if path.is_symlink() or not path.is_dir() or time.time() - path.stat().st_mtime <= 60:
                        raise Refused("Claude token refresh/login is busy; retry at the next hook") from None
                    try:
                        path.rmdir()
                        path.mkdir(mode=0o700)
                    except OSError:
                        raise Refused("Claude token refresh/login is busy; retry at the next hook") from None
                record = (path, lock_identity(path), time.monotonic())
                acquired.append(record)
                _NATIVE_LOCKS.append(record)
        yield
    finally:
        for record in reversed(acquired):
            path, identity, _ = record
            _NATIVE_LOCKS.remove(record)
            # A stopped process may resume after another process reclaimed its
            # stale lock. Never release that new owner's directory.
            try:
                if not path.is_symlink() and lock_identity(path) == identity:
                    path.rmdir()
            except FileNotFoundError:
                pass


class Store:
    def __init__(self, root=None, api=None):
        self.root = Path(root or os.environ.get("CLAUDE_ACCOUNT_FALLBACK_HOME") or
                         Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "claude-account-fallback").expanduser()
        self.api = api or Api()
        self.path = self.root / "config.json"
        self.data = read_json(self.path, {"version": 1, "thresholds": dict(DEFAULTS), "cache_ttl": 60, "accounts": {}, "targets": {}})
        if self.data.get("version") != 1:
            raise Refused("Unsupported account configuration version")

    @contextmanager
    def locked(self):
        private_dir(self.root)
        lock = self.root / "manager.lock"
        if lock.is_symlink():
            raise Refused("Refusing a symbolic-link manager lock")
        with lock.open("a") as stream:
            os.fchmod(stream.fileno(), 0o600)
            until = time.monotonic() + 2
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= until:
                        raise Refused("Account manager is busy; retry shortly") from None
                    time.sleep(0.05)
            self.data = read_json(self.path, self.data)
            yield self

    def save(self):
        write_json(self.path, self.data)

    def account(self, name):
        if name not in self.data["accounts"]:
            raise Refused("Unknown account name; run status")
        return self.data["accounts"][name]

    def home(self, name):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", name):
            raise Refused("Account name must use 1–48 lowercase letters, digits, underscores or hyphens")
        return self.root / "accounts" / name

    def credential(self, name):
        return oauth(read_json(self.home(name) / ".credentials.json"))

    def save_credential(self, name, credential):
        home = self.home(name)
        private_dir(self.root / "accounts")
        private_dir(home)
        path = home / ".credentials.json"
        document = read_json(path, {})
        document["claudeAiOauth"] = credential
        write_json(path, document)

    def save_profile(self, name, directory):
        """Archive the cached identity of `name` from a profile signed in as it.

        Claude Code reads the account/organization shown in auth status and
        used for the session from oauthAccount, not from the credential, so a
        switch must carry it along. Only a snapshot matching the verified
        identity is kept.
        """
        identity = self.account(name)["identity"]
        cached = read_json(global_config(directory), {}).get("oauthAccount")
        if (isinstance(cached, dict) and cached.get("accountUuid") == identity["account"] and
                cached.get("organizationUuid") == identity["organization"]):
            path = self.home(name) / "oauth-account.json"
            if read_json(path, {}).get("oauthAccount") != cached:
                write_json(path, {"oauthAccount": cached})

    def publish_profile(self, name, directory):
        """Point a profile's cached identity at `name` after its credential moved there.

        Without an archived snapshot the stale identity is removed, so Claude
        Code fetches the profile of the new credential instead of reusing it.
        """
        path = global_config(directory)
        if not path.exists():
            return
        document = read_json(path)
        cached = read_json(self.home(name) / "oauth-account.json", {}).get("oauthAccount")
        if document.get("oauthAccount") == cached:
            return
        if cached:
            document["oauthAccount"] = cached
        else:
            document.pop("oauthAccount", None)
        write_json(path, document)

    def identify(self, name, credential):
        account = self.account(name)
        fingerprint = digest(credential)
        if fingerprint != account.get("verified"):
            if self.api.identity(credential) != account["identity"]:
                raise Refused("Active credential belongs to another account; import/re-enable explicitly")
            account["verified"] = fingerprint

    def bound_dirs(self, name):
        return [Path(path) for path, binding in self.data["targets"].items()
                if binding.get("enabled") and binding.get("active") == name]

    def sync_target(self, directory):
        binding = self.data["targets"].get(str(directory))
        if not binding or not binding.get("active"):
            return
        name = binding["active"]
        live = oauth(read_json(directory / ".credentials.json"))
        if digest(live) != binding.get("fingerprint"):
            self.identify(name, live)
            # A second profile can still hold an older grant. Never archive it
            # over the later native refresh already captured from a sibling.
            if live.get("expiresAt", 0) >= self.credential(name).get("expiresAt", 0):
                self.save_credential(name, live)
            binding["fingerprint"] = digest(live)

    def publish(self, name, directories, credential):
        for directory in directories:
            binding = self.data["targets"][str(directory)]
            document = read_json(directory / ".credentials.json")
            live = oauth(document)
            if digest(live) != binding["fingerprint"]:
                raise Refused("Credential changed during synchronization; retry shortly")
            if digest(live) != digest(credential):
                document["claudeAiOauth"] = credential
                write_json(directory / ".credentials.json", document)
                binding["fingerprint"] = digest(credential)
        self.save()

    def sync_account(self, name):
        directories = self.bound_dirs(name)
        with native_locks(directories + [self.home(name)]):
            for directory in directories:
                self.sync_target(directory)
            credential = self.credential(name)
            self.identify(name, credential)
            self.publish(name, directories, credential)
            return credential

    def add(self, name, directory, priority):
        self.home(name)
        document = read_json(directory / ".credentials.json")
        credential = oauth(document)
        identity = self.api.identity(credential)
        for other, account in self.data["accounts"].items():
            if other != name and account["identity"] == identity:
                raise Refused("This account/organization is already saved under another name")
        old = self.data["accounts"].get(name)
        if old and old["identity"] != identity:
            raise Refused("Name already belongs to a different account; choose a new name")
        bound = self.bound_dirs(name)
        private_dir(self.home(name))
        with native_locks(bound + [self.home(name)]):
            documents = {}
            for target in bound:
                document = read_json(target / ".credentials.json")
                live = oauth(document)
                if digest(live) != self.data["targets"][str(target)]["fingerprint"]:
                    if self.api.identity(live) != identity:
                        raise Refused("Bound profile changed accounts; disable/re-enable that target before re-login")
                documents[target] = document
            # A new login grant supersedes this account's archived grant. Keep
            # bound copies in sync rather than importing the old chain again.
            self.save_credential(name, credential)
            self.data["accounts"][name] = {
                "priority": priority, "enabled": old.get("enabled", True) if old else True,
                "thresholds": old.get("thresholds", {}) if old else {},
                "identity": identity, "verified": digest(credential),
            }
            self.save_profile(name, directory)
            self.save()
            for target, document in documents.items():
                document["claudeAiOauth"] = credential
                write_json(target / ".credentials.json", document)
                self.data["targets"][str(target)]["fingerprint"] = digest(credential)
            self.save()

    def enable(self, directory):
        check_file_auth(directory)
        credential = oauth(read_json(directory / ".credentials.json"))
        identity = self.api.identity(credential)
        matches = [name for name, account in self.data["accounts"].items() if account["identity"] == identity]
        if not matches:
            raise Refused("Import the current account first, then enable fallback")
        name = matches[0]
        if credential.get("expiresAt", 0) >= self.credential(name).get("expiresAt", 0):
            self.save_credential(name, credential)
            self.account(name)["verified"] = digest(credential)
        self.data["targets"][str(directory)] = {"enabled": True, "active": name, "fingerprint": digest(credential),
                                                "switched_at": time.time()}
        self.save_profile(name, directory)
        self.save()
        self.sync_account(name)

    def refresh(self, name):
        account = self.account(name)
        directories = self.bound_dirs(name)
        with native_locks(directories + [self.home(name)]):
            for directory in directories:
                self.sync_target(directory)
            credential = self.credential(name)
            # Another managed target may have supplied a newly refreshed grant.
            if credential.get("expiresAt", 0) > (time.time() + 60) * 1000:
                self.publish(name, directories, credential)
                return credential
            updated = self.api.refresh(credential)
            self.save_credential(name, updated)
            account.pop("verified", None)
            # Persist the rotated grant before any further network operation.
            self.save()
            self.publish(name, directories, updated)
            return updated

    def statusline_limits(self, name, now):
        """Newest live statusline reading of `name` as (at, limits), or None.

        A running session keeps the credential it started with, which can be
        the previous account after a switch. A snapshot counts only for a
        session that started after the target last changed account (and after
        the statusline was installed), so its numbers belong to `name`.
        """
        best = None
        for path in sorted((self.root / "statusline").glob("*.json")):
            try:
                snapshot = read_json(path)
            except Refused:
                continue
            binding = self.data["targets"].get(snapshot.get("config_dir"), {})
            since = max(binding.get("switched_at", math.inf), self.data.get("statusline", {}).get(snapshot.get("config_dir"), {}).get("installed_at", math.inf))
            started = snapshot.get("started")
            if (not binding.get("enabled") or binding.get("active") != name or snapshot.get("account") != name or
                    snapshot.get("first_account") != name or not isinstance(started, (int, float)) or started < since):
                continue
            # The numbers come from the last model response, so the reading is as
            # old as the older of the snapshot and the transcript.
            at = min(mtime(path), mtime(snapshot.get("transcript_path")))
            limits = statusline_usage(snapshot.get("rate_limits"), now)
            if limits and (best is None or at > best[0]):
                best = (at, limits)
        return best

    def timing(self, key):
        return self.data.get(key, TIMING[key])

    def usage(self, name, force=False):
        """Plan limits of `name` from the newer of its statusline and API readings.

        The API is called only when no session's statusline changed within
        statusline_fresh seconds and the last API reading is at least cache_ttl
        seconds old (or covers a window that has since reset).
        """
        account, now = self.account(name), time.time()
        cached = account.get("usage", {})
        live = None if force else self.statusline_limits(name, now)
        if live:
            account["statusline"] = {"at": live[0], "limits": live[1]}
        limits = cached.get("limits")
        usable = limits and not any(item["resets_at"] is not None and item["resets_at"] <= now for item in limits.values())
        # A working session keeps its statusline current. The API reading only
        # has to supply the model-specific weekly limits, so it may be older.
        if (live and now - live[0] <= self.timing("statusline_fresh") and usable and
                now - cached["at"] <= self.timing("api_max_age")):
            self.save()
            return newest(limits, cached["at"], live)
        if now < cached.get("retry_at", 0):
            raise Refused("Usage service is in backoff; account eligibility is unknown")
        try:
            credential = self.sync_account(name)
            if credential.get("expiresAt", 0) <= (now + 60) * 1000:
                credential = self.refresh(name)
            self.identify(name, credential)
            if usable and now - cached["at"] < self.timing("cache_ttl") and not force:
                return newest(limits, cached["at"], live)
            limits = self.api.usage(credential)
            account["usage"] = {"at": now, "limits": limits}
            return limits
        except Refused as error:
            account["usage"] = {**cached, "retry_at": now + (error.retry if isinstance(error, ApiError) else 30), "error": str(error)}
            # Unknown/stale usage never makes an account eligible.
            raise
        finally:
            self.save()

    def thresholds(self, name):
        return {**self.data["thresholds"], **self.account(name).get("thresholds", {})}

    def exhausted_until(self, name, now):
        """When the latest known reading of `name` stops proving it is at a threshold, or None.

        Usage only grows within a window, so a limit at its threshold stays
        there until its reset time. Until then no request is needed to know the
        account is ineligible; afterwards the API confirms it before reuse. The
        statusline reading saved while the account was active counts too.
        """
        account, thresholds, until = self.account(name), self.thresholds(name), None
        api, live = account.get("usage", {}), account.get("statusline", {})
        # A newer API reading supersedes an older statusline one.
        readings = [api] if live.get("at", 0) < api.get("at", 0) else [api, live]
        for reading in readings:
            for item in (reading.get("limits") or {}).values():
                resets = item.get("resets_at")
                if resets is not None and resets > now and item["percent"] >= thresholds[item["kind"]]:
                    until = max(until or resets, resets)
        return until

    def eligible(self, name, force=False):
        now = time.time()
        if now < self.account(name).get("blocked_until", 0):
            return False
        if not force and self.exhausted_until(name, now):
            return False
        thresholds = self.thresholds(name)
        return all(item["percent"] < thresholds[item["kind"]] for item in self.usage(name, force).values())

    def switch(self, directory, name):
        binding = self.data["targets"][str(directory)]
        previous = binding["active"]
        if previous == name:
            return None
        # Catch a refresh from any other profile before adopting a saved grant.
        sources = self.bound_dirs(name)
        with native_locks([directory, self.home(name)] + sources):
            self.sync_target(directory)
            for source in sources:
                self.sync_target(source)
            candidate = self.credential(name)
            self.identify(name, candidate)
            document = read_json(directory / ".credentials.json")
            before = oauth(document)
            if digest(before) != binding["fingerprint"]:
                raise Refused("Credential changed during selection; retry shortly")
            # Keep the outgoing identity current before the profile forgets it.
            self.save_profile(previous, directory)
            document["claudeAiOauth"] = candidate
            write_json(directory / ".credentials.json", document)
            binding.update(active=name, fingerprint=digest(candidate), switched_at=time.time())
            self.save()
            self.publish_profile(name, directory)
        return f"Claude account fallback: {previous} → {name} (priority {self.account(name)['priority']})."

    def select(self, directory, failed=False):
        binding = self.data["targets"][str(directory)]
        self.sync_account(binding["active"])
        current = binding["active"]
        if failed:
            try:
                self.usage(current, force=True)
            except Refused:
                pass
            # A server 429 overrides a low/lagging usage percentage. A short
            # cooldown avoids A→B→A loops while the usage endpoint catches up.
            self.account(current)["blocked_until"] = time.time() + 300
            self.save()
        failures = []
        for name in sorted(self.data["accounts"], key=lambda n: (self.account(n)["priority"], n)):
            if not self.account(name)["enabled"]:
                continue
            try:
                if self.eligible(name):
                    return self.switch(directory, name)
                until = self.exhausted_until(name, time.time())
                failures.append(f"{name}: at threshold until {datetime.fromtimestamp(until).strftime('%Y-%m-%d %H:%M')}"
                                if until else f"{name}: at threshold or cooling down")
            except Refused as error:
                failures.append(f"{name}: {error}")
        raise Refused("No eligible subscription account. " + "; ".join(failures))

    def status(self, directory):
        binding = self.data["targets"].get(str(directory), {})
        return {"thresholds": self.data["thresholds"], **{key: self.timing(key) for key in TIMING},
                "config_dir": str(directory), "target": {"enabled": binding.get("enabled", False), "active": binding.get("active"),
                                                         "statusline": str(directory) in self.data.get("statusline", {})},
                "accounts": [{"name": name, "priority": account["priority"], "enabled": account["enabled"],
                              "thresholds": self.thresholds(name), "usage": account.get("usage"),
                              "statusline": account.get("statusline"),
                              "blocked_until": account.get("blocked_until")}
                             for name, account in sorted(self.data["accounts"].items(), key=lambda pair: (pair[1]["priority"], pair[0]))]}


def statusline_copy(store):
    # Plugin updates move the plugin directory, so settings.json points at a copy.
    return store.root / "bin" / "accounts.py"


def statusline_command(store):
    return f"python3 {shlex.quote(str(statusline_copy(store)))} statusline run"


def refresh_statusline_copy(store):
    copy, source = statusline_copy(store), Path(__file__).resolve()
    if copy.is_file() and not copy.is_symlink() and copy.resolve() != source and copy.read_bytes() != source.read_bytes():
        shutil.copyfile(source, copy)
        copy.chmod(0o600)


def install_statusline(store, directory):
    """Wrap the profile's statusline so its plan usage is recorded per session."""
    settings_path = directory / "settings.json"
    settings = read_json(settings_path, {})
    private_dir(store.root)
    private_dir(store.root / "bin")
    shutil.copyfile(Path(__file__).resolve(), statusline_copy(store))
    statusline_copy(store).chmod(0o600)
    command = statusline_command(store)
    current = settings.get("statusLine")
    if isinstance(current, dict) and current.get("command") == command:
        return
    store.data.setdefault("statusline", {})[str(directory)] = {"previous": current, "installed_at": time.time()}
    store.save()
    settings["statusLine"] = {**(current if isinstance(current, dict) else {}), "type": "command", "command": command}
    write_json(settings_path, settings)


def uninstall_statusline(store, directory):
    settings_path = directory / "settings.json"
    entry = store.data.get("statusline", {}).pop(str(directory), None)
    settings = read_json(settings_path, {})
    current = settings.get("statusLine")
    if isinstance(current, dict) and current.get("command") == statusline_command(store):
        previous = (entry or {}).get("previous")
        if previous:
            settings["statusLine"] = previous
        else:
            settings.pop("statusLine")
        write_json(settings_path, settings)


def record_statusline(store, directory, payload):
    """Save this session's plan usage for the hook, tagged with the account in use."""
    session = payload.get("session_id")
    binding = store.data["targets"].get(str(directory), {})
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session) or not binding.get("enabled"):
        return
    folder = store.root / "statusline"
    private_dir(store.root)
    private_dir(folder)
    path, now = folder / f"{session}.json", time.time()
    old = read_json(path, {})
    transcript = payload.get("transcript_path") if isinstance(payload.get("transcript_path"), str) else None
    started = old.get("started")
    if not isinstance(started, (int, float)):
        # A session already running before its first snapshot (e.g. before the
        # statusline was installed) is dated by its transcript instead.
        first = transcript_started(transcript)
        started = min(now, first) if first else now
    rate_limits = payload.get("rate_limits")
    write_json(path, {
        "config_dir": str(directory), "account": binding.get("active"),
        "first_account": old.get("first_account", binding.get("active")), "started": started,
        "transcript_path": transcript, "rate_limits": rate_limits if isinstance(rate_limits, dict) else None,
    })
    # Snapshots of sessions untouched for a day are of no further use.
    for other in folder.glob("*.json"):
        if now - mtime(other) > 86400:
            other.unlink(missing_ok=True)


def run_statusline():
    """Statusline entry point: record the snapshot, then render the previous statusline."""
    raw, inner = sys.stdin.buffer.read(), None
    try:
        store, directory = Store(), active_dir()
        previous = store.data.get("statusline", {}).get(str(directory), {}).get("previous")
        if isinstance(previous, dict) and previous.get("type", "command") == "command":
            inner = previous.get("command")
        record_statusline(store, directory, json.loads(raw))
    except (Refused, OSError, ValueError, TypeError, KeyError, AttributeError):
        # The statusline must keep rendering even when state is unreadable.
        pass
    if isinstance(inner, str) and inner and "statusline run" not in inner:
        sys.stdout.flush()
        return subprocess.run(["bash", "-c", inner], input=raw).returncode
    return 0


def management_call(payload):
    """Allow the installed manager itself to recover config at a blocked limit."""
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") != "Bash":
        return False
    try:
        command = payload.get("tool_input", {}).get("command", "")
        tokens = shlex.split(command) if isinstance(command, str) else command
        if not (len(tokens) >= 3 and Path(tokens[0]).name in ("python", "python3") and
                Path(tokens[1]).resolve() == Path(__file__).resolve()):
            return False
        # Parse the entire invocation. A valid manager prefix must not exempt
        # an appended shell command, pipeline, or a second Python program.
        with redirect_stderr(io.StringIO()):
            args = parser().parse_args(tokens[2:])
        return args.command != "hook"
    except (ValueError, TypeError, SystemExit):
        return False


def emit_block(event, message):
    if event == "UserPromptSubmit":
        print(json.dumps({"decision": "block", "reason": message}))
    elif event == "PreToolUse":
        print(json.dumps({"continue": False, "stopReason": message, "hookSpecificOutput": {
            "hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": message}}))
    elif event in ("SessionStart", "Stop", "StopFailure"):
        print(json.dumps({"systemMessage": message}))
    else:
        print(json.dumps({"continue": False, "stopReason": message}))


def hook():
    event = "UserPromptSubmit"
    try:
        payload = json.load(sys.stdin)
        event = payload.get("hook_event_name", event)
        directory = active_dir()
        store = Store(api=Api(time.monotonic() + 14))
        if event == "SessionStart":
            try:
                refresh_statusline_copy(store)
            except OSError:
                pass
        binding = store.data["targets"].get(str(directory), {})
        if not binding.get("enabled") or management_call(payload):
            return 0
        check_file_auth(directory)
        with store.locked():
            if not store.data["targets"].get(str(directory), {}).get("enabled"):
                return 0
            if event == "StopFailure" and payload.get("error") != "rate_limit":
                return 0
            if event == "SessionStart":
                store.sync_account(binding["active"])
                return 0
            message = store.select(directory, failed=event == "StopFailure")
            if message:
                print(json.dumps({"systemMessage": message + " Subsequent requests may adopt the new credential; live switching remains experimental."}))
        return 0
    except (Refused, OSError, ValueError, TypeError, KeyError) as error:
        # Avoid raw exception strings from JSON/config/native operations: a
        # malformed credential may otherwise appear in a decoder traceback.
        detail = str(error) if isinstance(error, Refused) else "Account state could not be read or updated; run the manager status command"
        emit_block(event, "Claude account fallback: " + detail)
        return 0


def percent(value):
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 100:
        raise argparse.ArgumentTypeError("Use a percentage greater than 0 and at most 100")
    return number


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Use a positive integer")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config-dir", type=Path, help="target Claude config directory; defaults to CLAUDE_CONFIG_DIR or ~/.claude")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("status", "enable", "disable", "check", "hook"):
        commands.add_parser(name)
    for name in ("login", "import"):
        command = commands.add_parser(name)
        command.add_argument("name")
        command.add_argument("--priority", type=positive, required=True)
        if name == "import":
            command.add_argument("--from-config-dir", type=Path)
        else:
            command.add_argument("--email")
    command = commands.add_parser("configure")
    command.add_argument("--account", help="override thresholds for this account only")
    command.add_argument("--five-hour", type=percent)
    command.add_argument("--weekly", type=percent)
    command.add_argument("--cache-ttl", type=positive, help="minimum seconds between usage API calls per account, global only, maximum 3600")
    command.add_argument("--statusline-fresh", type=positive, help="seconds a statusline reading stands in for an API call, global only, maximum 600")
    command.add_argument("--api-max-age", type=positive, help="oldest API reading, in seconds, reused for model-specific limits next to a fresh statusline, global only, maximum 86400")
    command = commands.add_parser("priority")
    command.add_argument("name")
    command.add_argument("rank", type=positive)
    command = commands.add_parser("order")
    command.add_argument("names", nargs="+", help="all account names in preferred order")
    command = commands.add_parser("account")
    command.add_argument("name")
    command.add_argument("action", choices=("enable", "disable"))
    command = commands.add_parser("statusline", help="read plan usage from the statusline instead of only the usage API")
    command.add_argument("action", choices=("install", "uninstall", "run"))
    return result


def login(store, args):
    store.home(args.name)
    check_file_auth(active_dir())
    executable = shutil.which("claude")
    if not executable:
        raise Refused("Claude CLI was not found on PATH")
    private_dir(store.root)
    # A fresh login has its own directory and native settings. It never logs
    # the active Claude/Orca session out, and doesn't hold our manager lock.
    directory = tempfile.mkdtemp(prefix="login-", dir=store.root)
    try:
        env = dict(os.environ, CLAUDE_CONFIG_DIR=directory)
        for key in list(env):
            if key.startswith("ORCA_") or key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
                env.pop(key)
        command = [executable, "auth", "login", "--claudeai"]
        if args.email:
            command += ["--email", args.email]
        completed = subprocess.run(command, env=env, cwd=directory)
        if completed.returncode:
            raise Refused("Claude login did not complete; saved accounts were preserved")
        # The human can take minutes in the browser. Start the API deadline
        # after login, rather than expiring it while waiting for that person.
        if isinstance(store.api, Api):
            store.api = Api()
        with store.locked():
            store.add(args.name, Path(directory), args.priority)
    except (Refused, OSError):
        if (Path(directory) / ".credentials.json").is_file():
            raise Refused(f"Login profile preserved at {directory}. Retry with import {args.name} --priority {args.priority} --from-config-dir {shlex.quote(directory)}") from None
        shutil.rmtree(directory)
        raise
    else:
        shutil.rmtree(directory)


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "hook":
        return hook()
    if args.command == "statusline" and args.action == "run":
        return run_statusline()
    try:
        store = Store()
        directory = (args.config_dir.expanduser().resolve() if args.config_dir else active_dir())
        if args.command == "login":
            login(store, args)
        elif args.command == "status":
            print(json.dumps(store.status(directory), indent=2))
            return 0
        else:
            with store.locked():
                if args.command == "import":
                    source = args.from_config_dir.expanduser().resolve() if args.from_config_dir else directory
                    check_file_auth(source)
                    store.add(args.name, source, args.priority)
                elif args.command == "enable":
                    store.enable(directory)
                elif args.command == "disable":
                    if str(directory) in store.data["targets"]:
                        store.data["targets"][str(directory)]["enabled"] = False
                elif args.command == "configure":
                    target = store.account(args.account).setdefault("thresholds", {}) if args.account else store.data["thresholds"]
                    if args.five_hour is not None:
                        target["five_hour"] = args.five_hour
                    if args.weekly is not None:
                        target["seven_day"] = args.weekly
                    for key, limit in (("cache_ttl", 3600), ("statusline_fresh", 600), ("api_max_age", 86400)):
                        value = getattr(args, key)
                        if value is not None:
                            if args.account or value > limit:
                                raise Refused(f"--{key.replace('_', '-')} is global and must be 1–{limit} seconds")
                            store.data[key] = value
                elif args.command == "priority":
                    store.account(args.name)["priority"] = args.rank
                elif args.command == "order":
                    if len(set(args.names)) != len(args.names) or set(args.names) != set(store.data["accounts"]):
                        raise Refused("Order must list every saved account exactly once")
                    for rank, name in enumerate(args.names, 1):
                        store.account(name)["priority"] = rank
                elif args.command == "account":
                    store.account(args.name)["enabled"] = args.action == "enable"
                elif args.command == "statusline":
                    if args.action == "install":
                        install_statusline(store, directory)
                    else:
                        uninstall_statusline(store, directory)
                elif args.command == "check":
                    check_file_auth(directory)
                    if not store.data["targets"].get(str(directory), {}).get("enabled"):
                        raise Refused("Enable fallback for this config directory first")
                    message = store.select(directory)
                    if message:
                        print(message)
                store.save()
        print(json.dumps(store.status(directory), indent=2))
        return 0
    except (Refused, OSError, ValueError, TypeError, KeyError) as error:
        detail = str(error) if isinstance(error, Refused) else "Account operation failed; existing state was preserved where possible"
        print("Claude account fallback: " + detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
