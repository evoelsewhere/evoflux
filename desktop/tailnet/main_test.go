package main

import (
	"net/netip"
	"testing"

	"tailscale.com/ipn/ipnstate"
)

func TestTailnetHostPrefersMagicDNS(t *testing.T) {
	status := &ipnstate.Status{
		Self:         &ipnstate.PeerStatus{DNSName: "evoflux.example.ts.net."},
		TailscaleIPs: []netip.Addr{netip.MustParseAddr("100.64.0.5")},
	}
	if got := tailnetHost(status); got != "evoflux.example.ts.net" {
		t.Fatalf("tailnetHost() = %q", got)
	}
}

func TestTailnetHostFallsBackToIP(t *testing.T) {
	status := &ipnstate.Status{TailscaleIPs: []netip.Addr{netip.MustParseAddr("100.64.0.5")}}
	if got := tailnetHost(status); got != "100.64.0.5" {
		t.Fatalf("tailnetHost() = %q", got)
	}
}
