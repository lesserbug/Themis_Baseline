package main

import "fmt"

// Keep the protocol fault bound independent of the injected attack count.
// -1 preserves the historical b=F default; an explicit zero means no attackers.
func resolveByzantineCount(n, faultBound uint64, requested int64) (uint64, error) {
	if n == 0 || faultBound >= n {
		return 0, fmt.Errorf("requires 0 <= f < n")
	}
	if requested == -1 {
		return faultBound, nil
	}
	if requested < 0 || uint64(requested) > faultBound {
		return 0, fmt.Errorf("byzantine-count must be between 0 and f (or -1 to use f)")
	}
	return uint64(requested), nil
}
