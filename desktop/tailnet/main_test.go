package main

import (
	"bytes"
	"log"
	"net/netip"
	"os"
	"strings"
	"testing"

	"tailscale.com/ipn/ipnstate"
)

func TestCaptureUserLogPrintsEachLoginURLOnce(t *testing.T) {
	var out bytes.Buffer
	log.SetOutput(&out)
	log.SetFlags(0)
	t.Cleanup(func() { log.SetOutput(os.Stderr); log.SetFlags(log.LstdFlags) })

	const loginLine = "To start this tsnet server, restart with TS_AUTHKEY set, or go to: %s"
	a := &tailnetApp{}
	a.captureUserLog(loginLine, "https://login.tailscale.com/a/first")
	a.captureUserLog(loginLine, "https://login.tailscale.com/a/first")
	a.captureUserLog("unrelated message")
	a.captureUserLog(loginLine, "https://login.tailscale.com/a/second")

	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("expected 3 log lines, got %d:\n%s", len(lines), out.String())
	}
	if strings.Contains(out.String(), "login.tailscale.com") {
		t.Fatalf("login URL leaked into the log:\n%s", out.String())
	}
	if a.authURL != "https://login.tailscale.com/a/second" {
		t.Fatalf("authURL = %q", a.authURL)
	}
}

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
