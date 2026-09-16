from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "zcounter-ui.sh"
BAT_LAUNCHER = REPO_ROOT / "zcounter-ui.bat"
FAKE_WEBHOOK_VALUE = "fake-discord-webhook-test-value"


def extract_discord_env_block(script_path: Path) -> str:
    content = script_path.read_text(encoding="utf-8")
    match = re.search(r"if \[ -z \"\$\{DISCORD_WEBHOOK_URL:-\}\" \][\s\S]*?\nfi", content)
    if match is None:
        raise AssertionError(f"discord.env block not found in {script_path}")
    return match.group(0)


def create_temp_home_with_discord_env(value: str) -> Path:
    home = Path(tempfile.mkdtemp(prefix="zcounter-discord-env-"))
    config_dir = home / ".config" / "discord"
    config_dir.mkdir(parents=True)
    (config_dir / "discord.env").write_text(
        f"DISCORD_WEBHOOK_URL='{value}'\n",
        encoding="utf-8",
    )
    return home


def run_discord_env_block(script_path: Path, home: Path, *, preset_env: str | None = None) -> subprocess.CompletedProcess[str]:
    block = extract_discord_env_block(script_path)
    preset = ""
    if preset_env is not None:
        preset = f"export DISCORD_WEBHOOK_URL={preset_env}\n"
    script = f"""
set -euo pipefail
export HOME={home}
{preset}{block}
python3 -c "import os; print(os.environ.get('DISCORD_WEBHOOK_URL', ''))"
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)


class ZCounterUiLauncherTests(unittest.TestCase):
    def test_launcher_exports_discord_webhook_after_sourcing_discord_env(self) -> None:
        block = extract_discord_env_block(LAUNCHER)
        self.assertIn("export DISCORD_WEBHOOK_URL", block)
        self.assertIn("discord/discord.env", block)

    def test_bat_launcher_uses_shell_script(self) -> None:
        content = BAT_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("bash zcounter-ui.sh", content)

    def test_discord_env_is_visible_to_child_process(self) -> None:
        home = create_temp_home_with_discord_env(FAKE_WEBHOOK_VALUE)
        try:
            result = run_discord_env_block(LAUNCHER, home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), FAKE_WEBHOOK_VALUE)
            self.assertNotIn("discord.com/api/webhooks", result.stdout + result.stderr)
        finally:
            import shutil

            shutil.rmtree(home)

    def test_missing_discord_env_leaves_child_value_empty(self) -> None:
        home = Path(tempfile.mkdtemp(prefix="zcounter-discord-env-missing-"))
        try:
            result = run_discord_env_block(LAUNCHER, home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "")
        finally:
            import shutil

            shutil.rmtree(home)

    def test_existing_env_takes_priority_over_discord_env_file(self) -> None:
        home = create_temp_home_with_discord_env("from-file")
        try:
            result = run_discord_env_block(LAUNCHER, home, preset_env="from-env")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "from-env")
        finally:
            import shutil

            shutil.rmtree(home)


if __name__ == "__main__":
    unittest.main()
