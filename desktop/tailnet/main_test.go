package main

import (
	"bytes"
	"log"
	"net/http"
	"net/http/httptest"
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

func testIdentityStatus() *ipnstate.Status {
	return &ipnstate.Status{
		Self: &ipnstate.PeerStatus{DNSName: "EvoFlux.example.ts.net."},
		TailscaleIPs: []netip.Addr{
			netip.MustParseAddr("100.64.0.5"),
			netip.MustParseAddr("fd7a:115c:a1e0::5"),
		},
	}
}

func TestHostIdentityAllows(t *testing.T) {
	id := newHostIdentity(testIdentityStatus())
	cases := []struct {
		host string
		want bool
	}{
		{"evoflux.example.ts.net", true},
		{"evoflux", true},
		{"100.64.0.5", true},
		{"[fd7a:115c:a1e0::5]", true},
		{"EVOFLUX.Example.TS.net", true},
		{"EvoFlux", true},
		{"evoflux.example.ts.net.", true},
		{"evoflux.", true},
		{"evoflux.example.ts.net:443", true},
		{"evoflux.example.ts.net.:8080", true},
		{"evoflux:80", true},
		{"100.64.0.5:80", true},
		{"[fd7a:115c:a1e0::5]:443", true},
		{"[FD7A:115C:A1E0::5]", true},
		{"other.example.ts.net", false},
		{"other.example.ts.net:443", false},
		{"evoflux.other.ts.net", false},
		{"evoflux.example.ts.net.evil.example", false},
		{"evil.example", false},
		{"evil.example:80", false},
		{"100.64.0.6", false},
		{"[fd7a:115c:a1e0::6]", false},
		{"127.0.0.1:80", false},
		{"", false},
	}
	for _, tc := range cases {
		if got := id.allows(tc.host); got != tc.want {
			t.Errorf("allows(%q) = %v, want %v", tc.host, got, tc.want)
		}
	}
}

func TestHostIdentityUnknownRefusesEverything(t *testing.T) {
	var id *hostIdentity
	if id.allows("evoflux.example.ts.net") {
		t.Fatal("nil identity must refuse")
	}
	if !newHostIdentity(&ipnstate.Status{}).empty() {
		t.Fatal("status without Self or IPs must give an empty identity")
	}
}

func TestRefreshIdentityKeepsPreviousOnEmptyStatus(t *testing.T) {
	a := &tailnetApp{}
	a.refreshIdentity(testIdentityStatus())
	a.refreshIdentity(&ipnstate.Status{})
	if !a.identity.Load().allows("evoflux") {
		t.Fatal("identity lost after an empty status")
	}
	a.refreshIdentity(&ipnstate.Status{Self: &ipnstate.PeerStatus{DNSName: "renamed.example.ts.net."}})
	if a.identity.Load().allows("evoflux") || !a.identity.Load().allows("renamed") {
		t.Fatal("identity not refreshed after a name change")
	}
}

func TestProxyHandlerRefusesForeignHostBeforeProxying(t *testing.T) {
	a := &tailnetApp{}
	a.refreshIdentity(testIdentityStatus())
	handler := a.proxyHandler()

	for _, host := range []string{"other.example.ts.net", "evil.example", "100.64.9.9", "[fd7a:115c:a1e0::9]"} {
		request := httptest.NewRequest(http.MethodGet, "/", nil)
		request.Host = host
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, request)
		if recorder.Code != http.StatusForbidden {
			t.Errorf("Host %q: status %d, want 403", host, recorder.Code)
		}
	}

	// An own Host passes the check and reaches the next gate (no local client here).
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.Host = "evoflux.example.ts.net"
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusServiceUnavailable {
		t.Errorf("own Host: status %d, want 503 from the identity gate", recorder.Code)
	}

	// Before the identity is known every Host is refused.
	cold := &tailnetApp{}
	request = httptest.NewRequest(http.MethodGet, "/", nil)
	request.Host = "evoflux.example.ts.net"
	recorder = httptest.NewRecorder()
	cold.proxyHandler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusForbidden {
		t.Errorf("unknown identity: status %d, want 403", recorder.Code)
	}
}

func TestTailnetHostFallsBackToIP(t *testing.T) {
	status := &ipnstate.Status{TailscaleIPs: []netip.Addr{netip.MustParseAddr("100.64.0.5")}}
	if got := tailnetHost(status); got != "100.64.0.5" {
		t.Fatalf("tailnetHost() = %q", got)
	}
}
