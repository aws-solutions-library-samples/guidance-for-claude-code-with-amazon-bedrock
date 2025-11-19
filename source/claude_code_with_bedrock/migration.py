# ABOUTME: Configuration migration utilities for Claude Code with Bedrock
# ABOUTME: Handles automatic migration from legacy config format to new profile-per-file structure

"""Configuration migration from legacy format to new structure."""

import json
import shutil
from datetime import datetime


def migrate_legacy_config() -> bool:
    """Migrate configuration from legacy location to new structure.

    Migrates from:
        source/.ccwb-config/config.json (all profiles in one file)
    To:
        ~/.ccwb/config.json (global config with active profile)
        ~/.ccwb/profiles/*.json (individual profile files)

    Returns:
        True if migration successful, False otherwise.
    """
    from .config import Config, Profile

    legacy_config_file = Config.LEGACY_CONFIG_FILE
    new_config_dir = Config.CONFIG_DIR
    new_profiles_dir = Config.PROFILES_DIR

    if not legacy_config_file.exists():
        print("No legacy configuration found to migrate.")
        return False

    print("🔄 Migrating configuration to new location...")
    print(f"   From: {legacy_config_file}")
    print(f"   To:   {new_config_dir}")

    try:
        # Load legacy config
        with open(legacy_config_file) as f:
            legacy_data = json.load(f)

        # Extract profiles and default profile
        legacy_profiles = legacy_data.get("profiles", {})
        active_profile_name = legacy_data.get("default_profile") or "ClaudeCode"

        if not legacy_profiles:
            print("⚠️  Warning: No profiles found in legacy config")
            return False

        # Create new directory structure
        new_config_dir.mkdir(parents=True, exist_ok=True)
        new_profiles_dir.mkdir(parents=True, exist_ok=True)

        # Migrate each profile to individual file
        migrated_count = 0
        for profile_name, profile_data in legacy_profiles.items():
            try:
                # Ensure profile has schema_version
                profile_data["schema_version"] = "2.0"
                profile_data["name"] = profile_name

                # Create Profile object to validate/migrate
                profile = Profile.from_dict(profile_data)

                # Save to individual file
                profile_path = new_profiles_dir / f"{profile_name}.json"
                with open(profile_path, "w") as f:
                    json.dump(profile.to_dict(), f, indent=2)

                print(f"   ✓ Migrated profile: {profile_name}")
                migrated_count += 1

            except Exception as e:
                print(f"   ✗ Failed to migrate profile {profile_name}: {e}")

        if migrated_count == 0:
            print("✗ Migration failed: No profiles were migrated successfully")
            return False

        # Create new global config
        new_config_data = {
            "schema_version": "2.0",
            "active_profile": active_profile_name,
            "profiles_dir": str(new_profiles_dir),
        }

        with open(Config.CONFIG_FILE, "w") as f:
            json.dump(new_config_data, f, indent=2)

        print(f"   ✓ Created global config with active profile: {active_profile_name}")

        # Create backup of legacy config
        backup_path = legacy_config_file.with_suffix(f".json.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy(legacy_config_file, backup_path)
        print(f"   ✓ Backed up legacy config: {backup_path}")

        print("\n✅ Migration complete!")
        print(f"   Migrated {migrated_count} profile(s)")
        print(f"   New config location: {new_config_dir}")
        print(f"   Active profile: {active_profile_name}")
        print("\n   You can safely delete the legacy config after verifying:")
        print(f"   {Config.LEGACY_CONFIG_DIR}")

        return True

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        return False


def check_migration_needed() -> bool:
    """Check if migration from legacy config is needed.

    Returns:
        True if migration is needed, False otherwise.
    """
    from .config import Config

    return not Config.CONFIG_FILE.exists() and Config.LEGACY_CONFIG_FILE.exists()
