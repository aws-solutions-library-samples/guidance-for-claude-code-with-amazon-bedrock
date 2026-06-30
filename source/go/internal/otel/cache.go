package otel

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// currentCacheSchemaVersion identifies the shape of headers this binary
// produces. Bump this whenever the set of emitted headers changes so that
// upgraded binaries re-extract the JWT instead of serving stale cached
// headers written by an older version. Cache files without a schema version
// (or with a lower one) are treated as a miss by ReadCachedHeaders.
//
//	v1  initial 10-header set (no version field)
//	v2  adds x-project (driven by the AWS session-tag claim)
//	v3  adds x-persona (persona-based access, resolved from the groups claim)
const currentCacheSchemaVersion = 3

// cacheEntry is the JSON structure of {profile}-otel-headers.json.
type cacheEntry struct {
	SchemaVersion int               `json:"schema_version"`
	Headers       map[string]string `json:"headers"`
	TokenExp      int64             `json:"token_exp"`
	CachedAt      int64             `json:"cached_at"`
}

// CacheDir returns the path to ~/.claude-code-session/, creating it if needed.
func CacheDir() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(home, ".claude-code-session")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	return dir, nil
}

// ReadCachedHeaders returns cached headers if available.
// Headers are static user attributes (email, department, etc.) that don't change
// when the JWT token expires, so we return them even if the token has expired.
// This prevents triggering browser re-authentication just for telemetry headers.
func ReadCachedHeaders(profile string) (map[string]string, error) {
	dir, err := CacheDir()
	if err != nil {
		return nil, err
	}

	data, err := os.ReadFile(filepath.Join(dir, profile+"-otel-headers.json"))
	if err != nil {
		return nil, err
	}

	var entry cacheEntry
	if err := json.Unmarshal(data, &entry); err != nil {
		return nil, err
	}

	if entry.SchemaVersion < currentCacheSchemaVersion {
		// Stale cache from an older binary; force re-extraction so the new
		// header set takes effect on first launch after upgrade.
		return nil, fmt.Errorf("cache schema %d < %d; refreshing", entry.SchemaVersion, currentCacheSchemaVersion)
	}

	if entry.Headers == nil {
		return nil, fmt.Errorf("cache empty")
	}

	// An empty (non-nil) headers map means the last extraction produced no
	// attributes — typically because no monitoring token was available. Unlike
	// populated attributes (which are static and served past token expiry to
	// avoid re-auth), an empty result must NOT be served forever: once it
	// expires we report a miss so the helper retries credential-process and can
	// recover real attribution. While still within TTL we serve it as a hit to
	// keep telemetry export off the credential-process hot path. An empty entry
	// without a positive TTL (e.g. hand-written or from an older code path) is
	// also treated as a miss rather than a permanent hit.
	if len(entry.Headers) == 0 && (entry.TokenExp <= 0 || time.Now().Unix() >= entry.TokenExp) {
		return nil, fmt.Errorf("empty-headers cache expired or untimed; refreshing")
	}

	return entry.Headers, nil
}

// EmptyHeadersWriteSafe reports whether the empty-headers path may overwrite the
// cache for profile without risking the loss of still-valid attribution.
//
// emitEmptyHeaders is reached only after a Layer-1 miss, but a miss is not proof
// the cache is empty: ReadCachedHeaders also returns an error for a transient
// read failure (e.g. a Windows AV lock or a torn read mid-write) over a perfectly
// good populated entry. Unconditionally writing {} in that window would clobber
// real attribution for the whole empty-headers TTL. This function therefore only
// authorizes a write when it can positively confirm there is nothing worth
// keeping — an absent file, or a readable entry that is empty or schema-stale
// (which Layer 1 would discard anyway). Any ambiguous read (non-ENOENT error, or
// an existing-but-unparseable file) returns false so we refuse to overwrite.
func EmptyHeadersWriteSafe(profile string) bool {
	dir, err := CacheDir()
	if err != nil {
		return false
	}

	data, err := os.ReadFile(filepath.Join(dir, profile+"-otel-headers.json"))
	if err != nil {
		// An absent file is safe to create; any other error is ambiguous (it may
		// be a transient lock over a valid entry) so we refuse to overwrite.
		return os.IsNotExist(err)
	}

	var entry cacheEntry
	if err := json.Unmarshal(data, &entry); err != nil {
		// Existing but unparseable — don't risk clobbering real attribution.
		return false
	}

	// A schema-stale entry is going to be re-extracted regardless (Layer 1 will
	// not serve it), so its contents carry no attribution we'd lose.
	if entry.SchemaVersion < currentCacheSchemaVersion {
		return true
	}

	// Otherwise only a current-schema entry with no populated headers is safe to
	// overwrite — that is exactly the set Layer 1 would NOT serve as attribution.
	return len(entry.Headers) == 0
}

// WriteCachedHeaders writes both the metadata cache and the raw headers file atomically.
func WriteCachedHeaders(profile string, headers map[string]string, tokenExp int64) error {
	dir, err := CacheDir()
	if err != nil {
		return err
	}

	// Write main cache file
	entry := cacheEntry{
		SchemaVersion: currentCacheSchemaVersion,
		Headers:       headers,
		TokenExp:      tokenExp,
		CachedAt:      time.Now().Unix(),
	}
	entryData, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	if err := atomicWrite(filepath.Join(dir, profile+"-otel-headers.json"), entryData); err != nil {
		return err
	}

	// Write raw headers companion file
	rawData, err := json.Marshal(headers)
	if err != nil {
		return err
	}
	return atomicWrite(filepath.Join(dir, profile+"-otel-headers.raw"), rawData)
}

// atomicWrite writes data to a temp file then renames, with 0600 permissions.
func atomicWrite(path string, data []byte) error {
	dir := filepath.Dir(path)
	f, err := os.CreateTemp(dir, ".tmp-*")
	if err != nil {
		return err
	}
	tmpPath := f.Name()

	if _, err := f.Write(data); err != nil {
		f.Close()
		os.Remove(tmpPath)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmpPath)
		return err
	}
	if err := os.Chmod(tmpPath, 0600); err != nil {
		os.Remove(tmpPath)
		return err
	}
	if err := os.Rename(tmpPath, path); err != nil {
		os.Remove(tmpPath)
		return err
	}
	return nil
}
