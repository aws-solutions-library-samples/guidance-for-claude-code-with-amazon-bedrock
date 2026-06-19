# MDM Templates for Claude Cowork 3P (Amazon Bedrock)

Enterprise deployment templates for managing Claude Desktop with Amazon Bedrock as the third-party inference provider. Use these to push configuration via your MDM solution (Intune, Omnissa Workspace ONE, Jamf, etc.).

## Quick Start

**Recommended:** Use `ccwb cowork generate` to auto-generate these from your deployment profile:

```bash
# Generate all formats (JSON, macOS, Windows .reg, ADMX, Intune script)
poetry run ccwb cowork generate --format all

# Generate only ADMX templates for Group Policy / Intune
poetry run ccwb cowork generate --format admx

# Generate only Intune platform script
poetry run ccwb cowork generate --format ps1
```

Generated files are pre-populated with your Bedrock region, profile name, and model aliases.

## Templates

| File | Use With | Method |
|------|----------|--------|
| `windows/ClaudeCowork3P.admx` + `en-US/ClaudeCowork3P.adml` | Intune, Omnissa UEM, AD GPO | Import ADMX template |
| `windows/Set-CoworkPolicy.ps1` | Intune, Omnissa | Platform script (user context) |

## Windows: ADMX (Group Policy / Intune / Omnissa)

### Intune

1. Go to **Devices → Configuration → Import ADMX**
2. Upload `ClaudeCowork3P.admx` and `en-US/ClaudeCowork3P.adml`
3. Create a configuration profile → Administrative Templates (imported)
4. Configure policies under **Claude Cowork 3P (Bedrock)**:
   - Enable "Inference Provider" (sets to `bedrock`)
   - Set "Bedrock Region" (e.g., `us-east-1`)
   - Set "AWS Profile Name" (default: `ClaudeCode`)
   - Set "Model Aliases" (default: `["opus","sonnet","haiku"]`)
5. Assign to user/device groups

### Omnissa Workspace ONE (VMware UEM)

1. Navigate to **Devices → Profiles & Resources → Profiles → Add → Windows**
2. Choose **Administrative Templates** payload
3. Import `ClaudeCowork3P.admx` + `ClaudeCowork3P.adml`
4. Configure the policies under "Claude Cowork 3P (Bedrock)"
5. Assign to Smart Groups

### Active Directory Group Policy

1. Copy `ClaudeCowork3P.admx` to `C:\Windows\PolicyDefinitions\`
2. Copy `en-US\ClaudeCowork3P.adml` to `C:\Windows\PolicyDefinitions\en-US\`
3. Open Group Policy Editor → User Configuration → Administrative Templates
4. Navigate to "Claude Cowork 3P (Bedrock)" and configure policies

## Windows: Intune Platform Script

For environments that prefer script-based deployment over ADMX:

1. Edit `Set-CoworkPolicy.ps1` — update the `$config` hashtable with your values
2. In Intune: **Devices → Scripts and remediations → Platform scripts → Add**
3. Settings:
   - Run this script using the logged on credentials: **Yes** (writes to HKCU)
   - Run script in 64 bit PowerShell Host: **Yes**

## Registry Path

All CoWork 3P settings are written to:

```
HKCU\SOFTWARE\Policies\Claude
```

Claude Desktop reads this path at launch and treats values as managed MDM policy (highest precedence, cannot be overridden by users).

## Verification

After deployment, verify in Claude Desktop:
- Open **Settings → About** → should show "Managed by your organization"
- Or check registry: `reg query "HKCU\SOFTWARE\Policies\Claude"`

## Relationship to Anthropic's Official ADMX

Anthropic ships `ClaudeCode.admx` ([examples/mdm](https://github.com/anthropics/claude-code/tree/main/examples/mdm)) for **Claude Code** managed settings (permissions, bypass mode). That template targets `HKLM\SOFTWARE\Policies\ClaudeCode\Settings` (a single JSON blob).

This CCWB template (`ClaudeCowork3P.admx`) targets **Claude Desktop / Cowork 3P** settings under `HKCU\SOFTWARE\Policies\Claude` with individual policy entries for each Bedrock configuration value. The two templates are complementary — deploy both for full coverage of Claude Code + Claude Desktop.

## See Also

- [COWORK_3P.md](../../assets/docs/COWORK_3P.md) — Full CoWork 3P setup guide
- [Anthropic MDM docs](https://code.claude.com/docs/en/settings#settings-files)
- [Claude Cowork 3P setup](https://support.claude.com/en/articles/14680741)
