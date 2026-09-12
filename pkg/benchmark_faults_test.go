package main

import "testing"

func TestResolveByzantineCount(t *testing.T) {
	for _, tc := range []struct {
		name      string
		n, f      uint64
		requested int64
		want      uint64
		invalid   bool
	}{
		{"legacy", 20, 4, -1, 4, false},
		{"honest", 20, 4, 0, 0, false},
		{"partial", 20, 4, 2, 2, false},
		{"bound", 20, 4, 4, 4, false},
		{"no-faults", 20, 0, -1, 0, false},
		{"negative", 20, 4, -2, 0, true},
		{"over-bound", 20, 4, 5, 0, true},
		{"empty", 0, 0, -1, 0, true},
		{"invalid-bound", 4, 4, -1, 0, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := resolveByzantineCount(tc.n, tc.f, tc.requested)
			if (err != nil) != tc.invalid || got != tc.want {
				t.Fatalf("got %d, %v; want %d, invalid=%v", got, err, tc.want, tc.invalid)
			}
		})
	}
}
