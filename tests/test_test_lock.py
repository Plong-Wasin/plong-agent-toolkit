"""Exercise hook decisions and real runner serialization without running PHP/Docker."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/laravel-test-lock/hook-scripts"
PARALLEL = ROOT / "plugins/php-test-parallel-hook/hook-scripts"
RUNNER = SCRIPTS / "laravel-test-lock-run.sh"


class TestLock(unittest.TestCase):
    def hook(self, command, script="laravel-test-lock.sh"):
        env = os.environ.copy()
        env.pop("CLAUDE_TEST_LOCK", None)
        scripts = PARALLEL if script.startswith("php-artisan-test-parallel") else SCRIPTS
        return subprocess.run(
            ["python3", "-B", str(scripts / script)] if script.endswith(".py")
            else ["bash", str(scripts / script)],
            input=json.dumps({"tool_input": {"command": command}}),
            text=True, capture_output=True, env=env,
        )

    def test_unlocked_commands_are_blocked(self):
        for command in [
            "php artisan test", "./vendor/bin/phpunit", "vendor/bin/paratest",
            "vendor/bin/pest", "php ./vendor/bin/phpunit", "php artisan test --parallel",
            "docker compose exec -T php artisan test --parallel",
            "docker compose -p test -f compose.yml exec -T app php artisan test",
            "docker exec -w /app -e APP_ENV=testing container php artisan test",
            "docker run --rm --entrypoint php -v /repo:/app image artisan test",
            "docker compose exec app sh -lc 'php artisan test'",
            "docker-compose -f compose.yml exec app php artisan test",
            "docker exec app flock /tmp/php-artisan-test.lock php artisan test",
            f"docker exec app bash {RUNNER} 'php artisan test'",
            ["bash", "-lc", "docker compose exec app php artisan test"],
            "bash <<'EOF'\nphp artisan test\nEOF",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.hook(command).returncode, 2)

    def test_wrapped_commands_are_allowed(self):
        for command in [
            f"bash {RUNNER} 'docker compose exec -T app php artisan test --parallel'",
            f"{RUNNER} 'vendor/bin/phpunit'",
            "flock /tmp/php-artisan-test.lock docker compose exec -T app php artisan test",
            "flock /tmp/php-artisan-test.lock bash -lc 'php artisan test'",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.hook(command).returncode, 0)

    def test_mentions_do_not_count_as_execution_or_as_a_lock(self):
        for command in [
            "echo 'php artisan test'", "git status",
            "cat <<'EOF'\nphp artisan test\nEOF",
            "git commit -m \"$(cat <<'EOF'\nphp artisan test\nEOF\n)\"",
            "docker compose exec app echo 'php artisan test'",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.hook(command).returncode, 0)
        for command in [
            f"echo {RUNNER}; php artisan test",
            f"echo '{RUNNER}' && docker compose exec app php artisan test",
            f"bash {RUNNER} 'php artisan test'; vendor/bin/phpunit",
            "echo flock /tmp/php-artisan-test.lock; php artisan test",
            "flock /tmp/wrong.lock php artisan test",
            "flock -s /tmp/php-artisan-test.lock php artisan test",
            "echo php artisan test; docker compose exec app vendor/bin/pest",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.hook(command).returncode, 2)

    def test_legacy_hook_delegates_to_same_policy(self):
        for command in ["php artisan test", f"bash {RUNNER} 'docker exec app php artisan test'"]:
            self.assertEqual(
                self.hook(command, "php-artisan-test-lock.py").returncode,
                self.hook(command).returncode,
            )

    def test_parallel_policy_still_works_with_runner(self):
        for flag, blocked in [("", True), (" --parallel --processes=2", False)]:
            command = f"bash {RUNNER} 'docker compose exec app php artisan test{flag}'"
            result = self.hook(command, "php-artisan-test-parallel-check.py")
            self.assertEqual(bool(result.stdout.strip()) or result.returncode != 0, blocked)

    def test_parallel_policy_supports_codex_argv(self):
        for flag, blocked in [("", True), (" --parallel --processes=2", False)]:
            command = ["bash", "-lc", f"docker compose exec app php artisan test{flag}"]
            result = self.hook(command, "php-artisan-test-parallel-check.py")
            self.assertEqual(bool(result.stdout.strip()) or result.returncode != 0, blocked)

    @unittest.skipUnless(os.environ.get("RUN_DOCKER_LOCK_TESTS") == "1", "optional real Docker test")
    def test_real_docker_commands_share_host_queue_with_legacy_flock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "test.lock"
            env = dict(os.environ, CLAUDE_TEST_LOCK=str(lock))
            command = shlex.join([
                "docker", "run", "--rm", "--network", "none", "--read-only",
                "--mount", f"type=bind,src={root},dst=/work", "php:8.3-cli", "php", "-r",
                'file_put_contents("/work/events", "enter\\n", FILE_APPEND); '
                'usleep(200000); file_put_contents("/work/events", "exit\\n", FILE_APPEND);',
            ])
            processes = [
                subprocess.Popen(["bash", str(RUNNER), command], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE),
                subprocess.Popen(["flock", str(lock), "bash", "-c", command], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE),
            ]
            for process in processes:
                _, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual((root / "events").read_text().splitlines(), ["enter", "exit", "enter", "exit"])

    def test_runner_serializes_commands_and_preserves_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, CLAUDE_TEST_LOCK=str(root / "test.lock"))
            # Fake Docker executes the supplied command on the host. The lock must
            # surround the whole Docker invocation, without flock in the container.
            docker = root / "docker"
            docker.write_text('#!/bin/sh\nshift 3\nexec "$@"\n')
            docker.chmod(0o755)
            worker = root / "worker.py"
            worker.write_text(
                "import pathlib, sys, time\n"
                "p=pathlib.Path(sys.argv[1])\n"
                "with p.open('a') as f: f.write('enter\\n')\n"
                "time.sleep(0.15)\n"
                "with p.open('a') as f: f.write('exit\\n')\n"
            )
            log = root / "events"
            command = shlex.join([str(docker), "compose", "exec", "app", "python3", str(worker), str(log)])
            processes = [subprocess.Popen(["bash", str(RUNNER), command], env=env,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
            for process in processes:
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(log.read_text().splitlines(), ["enter", "exit", "enter", "exit"])
            result = subprocess.run(["bash", str(RUNNER), "exit 7"], env=env, capture_output=True)
            self.assertEqual(result.returncode, 7)
            env["CLAUDE_TEST_LOCK"] = str(root / "missing" / "lock")
            marker = root / "should-not-run"
            result = subprocess.run(["bash", str(RUNNER), f"touch {marker}"], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
