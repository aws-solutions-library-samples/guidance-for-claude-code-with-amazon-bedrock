# Config Sync

## Rule
Go `ProfileConfig` struct must match Python `Profile` dataclass. New fields need both sides + JSON tags.

## Why
`ccwb package` writes config.json from Python Profile → Go binary reads it into ProfileConfig struct. Missing fields from either side create silent failures.

## Implementation
When adding a field to Python `Profile` dataclass:
1. Add corresponding field to `source/go/internal/config/config.go` `ProfileConfig` struct
2. Add proper JSON tag in Go struct
3. Test that field is properly serialized/deserialized

## Init Round-Trip Safety

Every field that `_save_configuration` writes MUST be restored by `_check_existing_deployment`.
When adding a new profile field, update BOTH paths — save and reload.

```python
# In _save_configuration:
wizard_fields = {
    "new_field": config_data.get("section", {}).get("key", default),
}

# In _check_existing_deployment (MUST mirror the above):
config["section"]["key"] = getattr(profile, "new_field", default)
```

A round-trip test (save → reload → assert equality) must cover all fields.
PRs #436, #619, and #624 all fixed fields that were saved but not reloaded.

## Optional Section Safety

Optional config sections (`landing_page`, `codebuild`, `distribution`, `cowork_3p`) must be accessed via:
- `.get('section', {})` in dicts
- `getattr(profile, 'field', None)` on Profile objects

Re-running `ccwb init` after skipping a section must not crash.
New profile fields MUST have defaults (backward compat with old profiles).

## Storage Notes
- **Google:** client_secret stored in config.json (non-confidential)
- **Azure:** client_secret stored in OS keyring (confidential)

## Examples
```python
# Python Profile dataclass
@dataclass
class Profile:
    new_field: str = ""  # MUST have default

# Go ProfileConfig struct  
type ProfileConfig struct {
    NewField string `json:"new_field"`
}
```

## Related Issues
#436, #619, #624 — init round-trip data loss
Missing fields cause silent failures in credential process.