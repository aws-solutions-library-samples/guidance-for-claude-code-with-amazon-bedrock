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

## Storage Notes
- **Google:** client_secret stored in config.json (non-confidential)
- **Azure:** client_secret stored in OS keyring (confidential)

## Examples
```python
# Python Profile dataclass
@dataclass
class Profile:
    new_field: str = ""

# Go ProfileConfig struct  
type ProfileConfig struct {
    NewField string `json:"new_field"`
}
```

## Related Issues
Missing fields cause silent failures in credential process.