// Package persona implements the persona-resolution algorithm shared across the
// ccwb system. It is the Go half of the parity contract in spec
// persona-based-access §4.3: the Python resolver
// (claude_code_with_bedrock/persona_resolution.py), the quota Lambdas, and this
// package must all resolve the same persona for the same inputs. The shared
// fixtures in source/tests/fixtures/persona_resolution_cases.json are the parity
// oracle; any change here must keep those cases passing in both languages.
package persona

import "ccwb-go/internal/config"

// Resolve returns the single persona that applies to a user, following the
// declared-order algorithm from spec §4.3:
//
//  1. The first persona (in declared order — order IS precedence) whose Group
//     appears in the user's groups wins.
//  2. Otherwise, if a non-empty fallback names a declared persona, that persona
//     is returned.
//  3. Otherwise nil.
//
// Group membership is tested by exact string equality. A nil result means "no
// persona applies"; it is deliberately NOT an error so this function stays in
// exact parity with the Python resolver, which returns None for every
// no-result case (no match + no fallback, and fallback naming an unknown
// persona). Callers decide whether a nil persona is fatal — the credential
// helper treats it as a hard-deny and exits non-zero, while the quota Lambda
// falls back to its user/default policy lookup.
//
// The error return is part of the contract (design §2.6) for forward
// compatibility but is always nil today; there is no malformed-input condition
// the algorithm can encounter.
func Resolve(groups []string, personas []config.PersonaConfig, fallback string) (*config.PersonaConfig, error) {
	// Build a set of the user's groups for O(1) membership across the list.
	groupSet := make(map[string]struct{}, len(groups))
	for _, g := range groups {
		groupSet[g] = struct{}{}
	}

	// Declared order is precedence: return the first persona whose group matches.
	for i := range personas {
		if _, ok := groupSet[personas[i].Group]; ok {
			return &personas[i], nil
		}
	}

	// No group matched — use the named fallback if it exists.
	if fallback != "" {
		for i := range personas {
			if personas[i].Name == fallback {
				return &personas[i], nil
			}
		}
	}

	return nil, nil
}
