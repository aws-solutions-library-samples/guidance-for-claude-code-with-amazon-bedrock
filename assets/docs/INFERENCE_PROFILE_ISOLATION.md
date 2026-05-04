# Per-zone Bedrock inference profile isolation (GDPR)

This guide walks through enabling the optional per-zone inference-profile
isolation feature. With it, each compliance zone (e.g. `france`, `eu`,
`us`, `restricted`) has its own Bedrock application inference profiles.
Users in one zone cannot invoke another zone's profile — IAM denies
cross-zone invocation, denies invocation from any user who has no project
assignment, and binds each profile's data residency to the specific AWS
region it was created in.

## What composes the security boundary

Three IAM conditions, combined:

1. **Project + Zone required.** `bedrock:InvokeModel*` and `Converse*` are
   denied whenever the caller's STS session is missing either the
   `Project` or `Zone` principal tag. A user who isn't in any project
   group cannot invoke Bedrock at all.
2. **Zone tag match.** When tags are present, invocations are allowed
   only against application inference profiles whose `Zone` resource tag
   equals the caller's `Zone` principal tag.
3. **Region lock.** Additionally, the invoked profile's `ccwb:Region`
   resource tag must equal the call's `aws:RequestedRegion`. This closes
   the "accidentally created Zone=france profile in us-east-1" loophole
   at AWS, not at admin discipline.

Together these let you name zones anything you want — `france`, `mco`,
`restricted`, `production`, `sandbox` — without the IAM policy ever
needing to know AWS region prefixes.

## Recommended group naming

```
<prefix>-<zone>-<project>
```

Examples: `acmeprod-france-alpha`, `acmeprod-us-beta`,
`ccwb-okta-demo-eu-widgets`.

This is a convention, not a rule — ccwb prints the matching Okta claim
expression for whatever prefix you enter at `ccwb init` time. A
hyphen-free prefix is simpler; a multi-token prefix still works (the
wizard picks a `substringAfter` variant so the Okta expression never
needs to count dashes).

## Zone-name rules

Zone names must be:

- **One word**
- **Lowercase letters a-z only**
- **No digits, hyphens, underscores, uppercase letters, or special characters**
- **1–32 characters**
- **Not a reserved name** (`aws`, `amazon`, `bedrock`, `default`, `system`, `admin`)

Valid: `france`, `us`, `europe`, `restricted`, `production`, `sandbox`,
`mco`, `gdpr`.

Rejected: `France`, `us-east`, `eu_1`, `mco1`, `us-`, `eu1`.

The wizard and `ccwb inference-zone create --zone <name>` enforce this
at input time with a clear error message.

## One-time admin setup

1. **Enable the feature at init time.** Run `ccwb init` (or re-run it)
   and answer yes to:
   - "Enable per-project cost attribution?"
   - "Enforce per-zone inference-profile isolation (GDPR)?"
   Supply the Okta group-name prefix you'll use for your team.

2. **Create a zone with one or more models.** Run
   `ccwb inference-zone create` — an interactive wizard asks for:
   - Zone name (validated against the rule above).
   - Backing style: a specific AWS region (direct, single-region) or
     an AWS cross-region inference profile (multi-region routing).
   - Which Claude models to enable for this zone (Opus, Sonnet, Haiku —
     the wizard discovers available models live from Bedrock; falls
     back to the repo's hardcoded list if the API is unreachable).

   One inference profile is created per (zone × model) pair, tagged
   `Zone=<zone>`, `ccwb:Region=<region>`, `ccwb:Profile=<ccwb-profile>`,
   `ccwb:Model=<model-short>`. Each profile ARN is persisted in your
   ccwb profile for later reference.

3. **Add a zone to an existing zone.** Run
   `ccwb inference-zone create --zone france` again and select different
   models. The new profiles join the existing ones under the same zone
   tag. Users assigned to zone `france` can invoke any of them.

4. **Configure the Okta claims.** The `ccwb init` wizard prints both
   Project and Zone claim expressions at the end, pre-filled with your
   Okta group prefix. Paste them into your Okta Custom Authorization
   Server as ID-token claims with "Disable when empty string: yes". If
   a user isn't in a `<prefix>-<zone>-<project>` group, the claims
   aren't emitted, and the IAM Deny statement catches them at
   `InvokeModel` time.

5. **Deploy the new IAM policy.** `ccwb deploy` threads
   `EnforceProjectIsolation=true` into the CloudFormation stack.
   Existing customers with `enforce_project_isolation=false` are
   unaffected.

6. **Re-package and redistribute.** `ccwb package && ccwb distribute`
   pushes a new bundle. End users re-run their install script; the
   installer prints the per-zone ARNs and instructs each user to set
   their model inside Claude Code with:

   ```
   /model <arn provided by your team>
   ```

## Per-project day-to-day

Adding a new project to an existing zone = **zero AWS work**.

1. Create an Okta group named `<prefix>-<zone>-<project>` (e.g.
   `acmeprod-france-newteam`).
2. Assign users to it.
3. Assign the group to the Claude Code OIDC application.

Done. Users in the new group automatically get the right Project tag
for cost attribution and the right Zone tag for IAM routing. They set
`/model` to any of the zone's published ARNs on first use.

Adding a new **zone** requires `ccwb inference-zone create` plus one
Okta group creation. Still no redeployment of the CloudFormation stack.

## Multiple models per zone

A single zone commonly hosts all the Claude models your users need —
typically Opus, Sonnet, and Haiku. Run
`ccwb inference-zone create --zone france` and multi-select from the
model list. All selected models will be tagged `Zone=france`; IAM
treats them as independently authorized resources under the same zone
boundary.

Users in the `france` Okta group pick which model to invoke by setting
`/model <arn>` inside Claude Code — the admin sends them the ARN list
(get it from `ccwb inference-zone list --zone france`).

## Commands

```
ccwb inference-zone create                      # interactive wizard
ccwb inference-zone create --zone france        # skip the zone-name prompt
ccwb inference-zone list                        # all zones
ccwb inference-zone list --zone france          # one zone
ccwb inference-zone delete --zone france        # delete all models for the zone
ccwb inference-zone delete --zone france --model opus-4-6
```

`list` and `delete` both operate on the ccwb profile's cached ARN map,
which is kept in sync with Bedrock by the `create`/`delete` commands.
If you delete an inference profile directly in the AWS console, run
`ccwb inference-zone list` to see the stale entry, and
`ccwb inference-zone delete` to reconcile.

## Troubleshooting

**"Claude Code: no Zone assignment found on your Okta token."**
The user is authenticated but their Okta token has no `Zone` session
tag. Either they aren't in a `<prefix>-<zone>-<project>` group, or the
Zone claim in Okta was misconfigured. Have them run
`credential-process --profile <name> --show-tags` to see the actual
claim payload on their cached token.

**"AccessDenied: explicit deny in identity-based policy" on `InvokeModel`.**
IAM is enforcing: either the user has no `Project`/`Zone` session tag
(user is not in any project group), or their Zone tag doesn't match the
invoked profile's Zone tag, or the call's region doesn't match the
profile's `ccwb:Region` tag. Check CloudTrail for the failing call —
the request's `principalTags` and the invoked resource ARN reveal which.

**"No profiles recorded for zone 'france'."**
`ccwb inference-zone list` reads from the ccwb profile's cached ARN
map. If you created inference profiles outside of ccwb (via console or
raw AWS CLI), they won't appear here. Re-create via
`ccwb inference-zone create` for cleaner state.

**Case mismatch between Okta Zone value and Bedrock `Zone` tag.**
IAM string comparison is case-sensitive. `ccwb inference-zone create`
lowercases zone names at input time and tags the Bedrock resource with
the lowercased value, so this should be rare. Confirm by decoding the
cached Okta token; the claim value must match the tag value byte-for-byte.

**Cross-link:** for Project-tag cost attribution details (Cost Explorer,
CUR 2.0, Athena queries) see [COST_ATTRIBUTION.md](COST_ATTRIBUTION.md).
For upgrading an existing deployment from Org AS to CAS see
[UPGRADE_ORG_AS_TO_CAS.md](UPGRADE_ORG_AS_TO_CAS.md).
