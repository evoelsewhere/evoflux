package main

import (
	"bytes"
	"log"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"net/url"
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

func TestIdentityProxyReplacesForgedHeaders(t *testing.T) {
	for _, connection := range []string{
		"X-EvoFlux-Remote-Token, Tailscale-User-Login, X-EvoFlux-Remote-Proxy, X-EvoFlux-Device-Label",
		"",
	} {
		name := "without Connection"
		if connection != "" {
			name = "identity named in Connection"
		}
		t.Run(name, func(t *testing.T) {
			type receivedRequest struct {
				header http.Header
				host   string
				uri    string
			}
			received := make(chan receivedRequest, 1)
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				received <- receivedRequest{r.Header.Clone(), r.Host, r.RequestURI}
				w.WriteHeader(http.StatusNoContent)
			}))
			defer upstream.Close()
			target, err := url.Parse(upstream.URL + "/base?target=1")
			if err != nil {
				t.Fatal(err)
			}
			request := httptest.NewRequest(http.MethodGet, "https://evoflux.example.ts.net/api/a%2Fb?client=2", nil)
			request.RemoteAddr = "100.64.0.8:12345"
			wantHeaders := map[string]string{
				"Tailscale-User-Login":   "verified@example.com",
				"X-EvoFlux-Device-Label": "verified-phone",
				"X-EvoFlux-Remote-Proxy": proxyMarker,
				"X-EvoFlux-Remote-Token": "test-proxy-key",
			}
			for header := range wantHeaders {
				request.Header.Add(header, "forged")
				request.Header.Add(header, "also-forged")
			}
			if connection != "" {
				request.Header.Set("Connection", connection)
			}
			request = withProxyIdentity(request, "verified@example.com", "verified-phone")
			recorder := httptest.NewRecorder()
			newIdentityProxy(target, "test-proxy-key").ServeHTTP(recorder, request)
			if recorder.Code != http.StatusNoContent {
				t.Fatalf("proxy status = %d: %s", recorder.Code, recorder.Body.String())
			}
			got := <-received
			for header, want := range wantHeaders {
				if values := got.header.Values(header); len(values) != 1 || values[0] != want {
					t.Errorf("upstream %s = %q, want exactly [%q]", header, values, want)
				}
			}
			if got.host != "evoflux.example.ts.net" {
				t.Errorf("upstream Host = %q, want inbound tailnet Host", got.host)
			}
			if got.uri != "/base/api/a%2Fb?target=1&client=2" {
				t.Errorf("upstream URI = %q, want joined target and request", got.uri)
			}
			if got.header.Get("Connection") != "" {
				t.Errorf("upstream Connection = %q, want removed", got.header.Get("Connection"))
			}
		})
	}
}

func TestIdentityProxyOmitsUnverifiedIdentity(t *testing.T) {
	for _, attachEmptyIdentity := range []bool{false, true} {
		name := "missing identity"
		if attachEmptyIdentity {
			name = "empty login"
		}
		t.Run(name, func(t *testing.T) {
			received := make(chan http.Header, 1)
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				received <- r.Header.Clone()
				w.WriteHeader(http.StatusNoContent)
			}))
			defer upstream.Close()
			target, err := url.Parse(upstream.URL)
			if err != nil {
				t.Fatal(err)
			}
			request := httptest.NewRequest(http.MethodGet, "https://evoflux.example.ts.net/", nil)
			headers := []string{
				"Tailscale-User-Login", "X-EvoFlux-Device-Label",
				"X-EvoFlux-Remote-Proxy", "X-EvoFlux-Remote-Token",
			}
			for _, header := range headers {
				request.Header.Add(header, "forged")
				request.Header.Add(header, "also-forged")
			}
			if attachEmptyIdentity {
				request = withProxyIdentity(request, "", "verified-phone")
			}
			recorder := httptest.NewRecorder()
			newIdentityProxy(target, "test-proxy-key").ServeHTTP(recorder, request)
			if recorder.Code != http.StatusNoContent {
				t.Fatalf("proxy status = %d: %s", recorder.Code, recorder.Body.String())
			}
			got := <-received
			for _, header := range headers {
				if values, exists := got[http.CanonicalHeaderKey(header)]; exists {
					t.Errorf("upstream %s = %q, want header absent", header, values)
				}
			}
		})
	}
}

func TestIdentityProxyPreservesForwardedHeaders(t *testing.T) {
	cases := []struct {
		name       string
		remoteAddr string
		header     http.Header
		want       http.Header
	}{
		{
			name: "no forwarding headers", remoteAddr: "100.64.0.8:12345",
			want: http.Header{"X-Forwarded-For": {"100.64.0.8"}},
		},
		{
			name: "append existing chain", remoteAddr: "100.64.0.8:12345",
			header: http.Header{
				"X-Forwarded-For":  {"192.0.2.1", "192.0.2.2"},
				"X-Forwarded-Host": {"original.example"}, "X-Forwarded-Proto": {"https"},
				"Forwarded": {"for=192.0.2.1", "for=192.0.2.2"},
			},
			want: http.Header{
				"X-Forwarded-For":  {"192.0.2.1, 192.0.2.2, 100.64.0.8"},
				"X-Forwarded-Host": {"original.example"}, "X-Forwarded-Proto": {"https"},
				"Forwarded": {"for=192.0.2.1", "for=192.0.2.2"},
			},
		},
		{
			name: "connection removes inbound forwarding headers", remoteAddr: "100.64.0.8:12345",
			header: http.Header{
				"Connection":      {"x-forwarded-for, X-Forwarded-Host", "X-Forwarded-Proto, Forwarded"},
				"X-Forwarded-For": {"192.0.2.1"}, "X-Forwarded-Host": {"original.example"},
				"X-Forwarded-Proto": {"https"}, "Forwarded": {"for=192.0.2.1"},
			},
			want: http.Header{"X-Forwarded-For": {"100.64.0.8"}},
		},
		{
			name: "nil suppresses client IP", remoteAddr: "100.64.0.8:12345",
			header: http.Header{"X-Forwarded-For": nil}, want: http.Header{},
		},
		{
			name: "IPv6 client", remoteAddr: "[fd7a:115c:a1e0::8]:12345",
			want: http.Header{"X-Forwarded-For": {"fd7a:115c:a1e0::8"}},
		},
		{
			name: "invalid remote address keeps chain", remoteAddr: "invalid",
			header: http.Header{"X-Forwarded-For": {"192.0.2.1"}},
			want:   http.Header{"X-Forwarded-For": {"192.0.2.1"}},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			received := make(chan http.Header, 1)
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				received <- r.Header.Clone()
				w.WriteHeader(http.StatusNoContent)
			}))
			defer upstream.Close()
			target, err := url.Parse(upstream.URL)
			if err != nil {
				t.Fatal(err)
			}
			request := httptest.NewRequest(http.MethodGet, "https://evoflux.example.ts.net/", nil)
			request.RemoteAddr = tc.remoteAddr
			if tc.header != nil {
				request.Header = tc.header.Clone()
			}
			request = withProxyIdentity(request, "verified@example.com", "verified-phone")
			recorder := httptest.NewRecorder()
			newIdentityProxy(target, "test-proxy-key").ServeHTTP(recorder, request)
			if recorder.Code != http.StatusNoContent {
				t.Fatalf("proxy status = %d: %s", recorder.Code, recorder.Body.String())
			}
			got := <-received
			for _, header := range []string{"X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded"} {
				values, want := got.Values(header), tc.want.Values(header)
				if len(values) != len(want) || strings.Join(values, "\n") != strings.Join(want, "\n") {
					t.Errorf("upstream %s = %q, want %q", header, values, want)
				}
			}
		})
	}
}
