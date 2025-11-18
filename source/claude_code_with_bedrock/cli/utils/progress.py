# ABOUTME: Progress tracking for multi-step CLI operations
# ABOUTME: Saves and restores wizard state to allow resuming interrupted sessions

"""Progress tracking utilities for CLI wizards."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class WizardProgress:
    """Tracks and persists wizard progress."""

    def __init__(self, wizard_name: str = "init"):
        self.wizard_name = wizard_name
        self.progress_file = self._get_progress_file()
        self.data: dict[str, Any] = self._load_progress()

    def _get_progress_file(self) -> Path:
        """Get the path to the progress file."""
        # Store in user's home directory
        config_dir = Path.home() / ".claude-code-with-bedrock"
        config_dir.mkdir(exist_ok=True)
        return config_dir / f".{self.wizard_name}_progress.json"

    def _load_progress(self) -> dict[str, Any]:
        """Load existing progress if available."""
        if self.progress_file.exists():
            try:
                with open(self.progress_file) as f:
                    data = json.load(f)
                    # Check if progress is recent (within 24 hours)
                    saved_time = datetime.fromisoformat(data.get("timestamp", ""))
                    if (datetime.now() - saved_time).days < 1:
                        return data
            except Exception:
                pass
        return {"step": "start", "data": {}, "timestamp": datetime.now().isoformat()}

    def save_step(self, step: str, step_data: dict[str, Any]) -> None:
        """Save progress for a specific step."""
        self.data["step"] = step
        self.data["data"].update(step_data)
        self.data["timestamp"] = datetime.now().isoformat()

        with open(self.progress_file, "w") as f:
            json.dump(self.data, f, indent=2)

    def get_saved_data(self) -> dict[str, Any]:
        """Get all saved data."""
        return self.data.get("data", {})

    def get_last_step(self) -> str:
        """Get the last completed step."""
        return self.data.get("step", "start")

    def has_saved_progress(self) -> bool:
        """Check if there's saved progress to resume."""
        return self.get_last_step() != "start" and bool(self.data.get("data"))

    def clear(self) -> None:
        """Clear saved progress."""
        if self.progress_file.exists():
            self.progress_file.unlink()
        self.data = {"step": "start", "data": {}, "timestamp": datetime.now().isoformat()}

    def get_summary(self) -> str:
        """Get a summary of saved progress."""
        if not self.has_saved_progress():
            return "No saved progress"

        data = self.get_saved_data()
        step = self.get_last_step()

        summary_parts = []
        if step == "okta_complete":
            summary_parts.append(f"✓ Okta: {data.get('okta', {}).get('domain', 'Not set')}")
        if step in ["aws_complete", "monitoring_complete", "bedrock_complete"]:
            summary_parts.append(f"✓ Okta: {data.get('okta', {}).get('domain', 'Not set')}")
            summary_parts.append(f"✓ AWS Region: {data.get('aws', {}).get('region', 'Not set')}")
        if step == "monitoring_complete":
            summary_parts.append(
                f"✓ Monitoring: {'Enabled' if data.get('monitoring', {}).get('enabled') else 'Disabled'}"
            )
        if step == "bedrock_complete":
            summary_parts.append(
                f"✓ Monitoring: {'Enabled' if data.get('monitoring', {}).get('enabled') else 'Disabled'}"
            )
            regions = data.get("aws", {}).get("allowed_bedrock_regions", [])
            summary_parts.append(f"✓ Bedrock Regions: {len(regions)} selected")

        return "\n".join(summary_parts)
