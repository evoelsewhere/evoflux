// evoflux-tailnet embeds a userspace Tailscale node for EvoFlux Desktop.
//
// It deliberately exposes only one tailnet service: a reverse proxy to the
// loopback FastAPI sidecar. The control API is loopback-only and bearer-token
// protected; remote identity is resolved with Tailscale WhoIs and forwarded
// with a per-process secret that the FastAPI middleware verifies.
package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"

	"tailscale.com/client/local"
	"tailscale.com/ipn/ipnstate"
	"tailscale.com/tsnet"
)

const (
	handshakePrefix = "EVOFLUX_TAILNET_HANDSHAKE "
	controlTokenEnv = "EVOFLUX_TAILNET_CONTROL_TOKEN"
	proxyTokenEnv   = "EVOFLUX_TAILNET_PROXY_TOKEN"
	proxyMarker     = "tsnet"
)

var (
	version       = "dev"
	authURLRegexp = regexp.MustCompile(`https://login\.tailscale\.com/[A-Za-z0-9/_?&=.%:+-]+`)
)

type tailscaleState struct {
	Provider   string `json:"provider"`
	Installed  bool   `json:"installed"`
	LoggedIn   bool   `json:"logged_in"`
	HTTPSCerts *bool  `json:"https_certs"`
	AuthURL    string `json:"auth_url,omitempty"`
	Error      string `json:"error,omitempty"`
}

type serveState struct {
	Enabled bool   `json:"enabled"`
	URL     string `json:"url,omitempty"`
}

type statusPayload struct {
	Tailscale tailscaleState `json:"tailscale"`
	Serve     serveState     `json:"serve"`
}

type handshake struct {
	Port    int    `json:"port"`
	PID     int    `json:"pid"`
	Version string `json:"version"`
}

type tailnetApp struct {
	mu       sync.Mutex
	serveMu  sync.Mutex
	ts       *tsnet.Server
	lc       *local.Client
	target   *url.URL
	stateDir string
	proxyKey string

	desiredEnabled bool
	listener       net.Listener
	httpServer     *http.Server
	serveURL       string
	authURL        string
	startupError   string
	serveError     string
	shutdown       chan struct{}
	startDone      chan struct{}
	shutdownOnce   sync.Once
}

func newTailnetApp(stateDir, hostname, targetURL, proxyKey string) (*tailnetApp, error) {
	target, err := url.Parse(targetURL)
	if err != nil || target.Scheme != "http" || target.Hostname() != "127.0.0.1" {
		return nil, fmt.Errorf("target must be an http://127.0.0.1 URL")
	}
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return nil, fmt.Errorf("create state directory: %w", err)
	}
	app := &tailnetApp{
		target:         target,
		stateDir:       stateDir,
		proxyKey:       proxyKey,
		desiredEnabled: fileExists(filepath.Join(stateDir, "serve-enabled")),
		shutdown:       make(chan struct{}),
		startDone:      make(chan struct{}),
	}
	app.ts = &tsnet.Server{
		Dir:      stateDir,
		Hostname: hostname,
		UserLogf: app.captureUserLog,
		Logf: func(format string, args ...any) {
			if os.Getenv("EVOFLUX_TAILNET_DEBUG") == "1" {
				log.Printf("tailscale: "+format, args...)
			}
		},
	}
	return app, nil
}

func (a *tailnetApp) captureUserLog(format string, args ...any) {
	message := fmt.Sprintf(format, args...)
	if match := authURLRegexp.FindString(message); match != "" {
		a.mu.Lock()
		a.authURL = match
		a.mu.Unlock()
	}
	log.Printf("tailscale: %s", authURLRegexp.ReplaceAllString(message, "<login-url>"))
}

func (a *tailnetApp) start() {
	defer close(a.startDone)
	if err := a.ts.Start(); err != nil {
		a.setStartupError(fmt.Sprintf("start embedded tailscale: %v", err))
		return
	}
	lc, err := a.ts.LocalClient()
	if err != nil {
		a.setStartupError(fmt.Sprintf("open embedded tailscale client: %v", err))
		return
	}
	a.mu.Lock()
	a.lc = lc
	a.startupError = ""
	a.mu.Unlock()
	go a.reconcileLoop()
}

func (a *tailnetApp) setStartupError(message string) {
	a.mu.Lock()
	a.startupError = message
	a.mu.Unlock()
	log.Print(message)
}

func (a *tailnetApp) reconcileLoop() {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		status, err := a.localStatus(ctx)
		if err == nil && status.BackendState == "Running" {
			if a.isDesiredEnabled() {
				if err := a.ensureServe(status); err != nil {
					a.mu.Lock()
					a.serveError = err.Error()
					a.mu.Unlock()
				}
			}
		}
		cancel()

		select {
		case <-a.shutdown:
			return
		case <-ticker.C:
		}
	}
}

func (a *tailnetApp) localStatus(ctx context.Context) (*ipnstate.Status, error) {
	a.mu.Lock()
	lc := a.lc
	a.mu.Unlock()
	if lc == nil {
		return nil, errors.New("embedded tailscale is still starting")
	}
	return lc.StatusWithoutPeers(ctx)
}

func (a *tailnetApp) isDesiredEnabled() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.desiredEnabled
}

func (a *tailnetApp) snapshot(ctx context.Context) statusPayload {
	state := tailscaleState{Provider: "embedded", Installed: true}
	status, err := a.localStatus(ctx)
	if err != nil {
		a.mu.Lock()
		state.AuthURL = a.authURL
		if a.startupError != "" {
			state.Error = a.startupError
		} else {
			state.Error = err.Error()
		}
		serve := serveState{Enabled: a.listener != nil, URL: a.serveURL}
		a.mu.Unlock()
		return statusPayload{Tailscale: state, Serve: serve}
	}

	state.LoggedIn = status.BackendState == "Running"
	if status.AuthURL != "" {
		state.AuthURL = status.AuthURL
	} else {
		a.mu.Lock()
		state.AuthURL = a.authURL
		a.mu.Unlock()
	}
	if state.LoggedIn {
		hasCerts := len(status.CertDomains) > 0
		state.HTTPSCerts = &hasCerts
	}

	a.mu.Lock()
	serve := serveState{Enabled: a.listener != nil, URL: a.serveURL}
	state.Error = a.startupError
	if state.Error == "" && a.serveError != "" && a.desiredEnabled && a.listener == nil {
		state.Error = a.serveError
	}
	a.mu.Unlock()
	return statusPayload{Tailscale: state, Serve: serve}
}

func (a *tailnetApp) login(ctx context.Context) error {
	a.mu.Lock()
	lc := a.lc
	a.mu.Unlock()
	if lc == nil {
		return errors.New("embedded tailscale is still starting")
	}
	return lc.StartLoginInteractive(ctx)
}

func (a *tailnetApp) setEnabled(enabled bool) error {
	a.mu.Lock()
	a.desiredEnabled = enabled
	a.serveError = ""
	a.mu.Unlock()
	marker := filepath.Join(a.stateDir, "serve-enabled")
	if enabled {
		if err := os.WriteFile(marker, []byte("enabled\n"), 0o600); err != nil {
			return fmt.Errorf("persist phone access setting: %w", err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		status, err := a.localStatus(ctx)
		if err != nil {
			return err
		}
		if status.BackendState != "Running" {
			return errors.New("tailscale is not logged in")
		}
		return a.ensureServe(status)
	}
	if err := os.Remove(marker); err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("persist phone access setting: %w", err)
	}
	return a.stopServe()
}

func (a *tailnetApp) ensureServe(status *ipnstate.Status) error {
	a.serveMu.Lock()
	defer a.serveMu.Unlock()

	a.mu.Lock()
	if !a.desiredEnabled || a.listener != nil {
		a.mu.Unlock()
		return nil
	}
	a.mu.Unlock()

	var (
		listener net.Listener
		serveURL string
		err      error
	)
	if len(status.CertDomains) > 0 {
		listener, err = a.ts.ListenTLS("tcp", ":443")
		if err == nil {
			serveURL = "https://" + strings.TrimSuffix(status.CertDomains[0], ".")
		}
	}
	if listener == nil {
		listener, err = a.ts.Listen("tcp", ":80")
		if err != nil {
			return fmt.Errorf("start embedded tailnet listener: %w", err)
		}
		serveURL = "http://" + tailnetHost(status)
	}

	server := &http.Server{
		Handler:           a.proxyHandler(),
		ReadHeaderTimeout: 15 * time.Second,
		IdleTimeout:       90 * time.Second,
	}
	a.mu.Lock()
	if !a.desiredEnabled || a.listener != nil {
		a.mu.Unlock()
		_ = listener.Close()
		return nil
	}
	a.listener = listener
	a.httpServer = server
	a.serveURL = serveURL
	a.serveError = ""
	a.mu.Unlock()

	log.Printf("phone access listening at %s", serveURL)
	go func() {
		if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			a.mu.Lock()
			a.serveError = fmt.Sprintf("embedded tailnet server stopped: %v", err)
			a.listener = nil
			a.httpServer = nil
			a.serveURL = ""
			a.mu.Unlock()
		}
	}()
	return nil
}

func tailnetHost(status *ipnstate.Status) string {
	if status.Self != nil && status.Self.DNSName != "" {
		return strings.TrimSuffix(status.Self.DNSName, ".")
	}
	if len(status.TailscaleIPs) > 0 {
		ip := status.TailscaleIPs[0]
		if ip.Is6() {
			return "[" + ip.String() + "]"
		}
		return ip.String()
	}
	return "evoflux"
}

func (a *tailnetApp) proxyHandler() http.Handler {
	proxy := httputil.NewSingleHostReverseProxy(a.target)
	proxy.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, err error) {
		log.Printf("reverse proxy error: %v", err)
		http.Error(w, "EvoFlux backend is unavailable", http.StatusBadGateway)
	}
	return http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		a.mu.Lock()
		lc := a.lc
		a.mu.Unlock()
		if lc == nil {
			http.Error(w, "Tailnet identity is unavailable", http.StatusServiceUnavailable)
			return
		}
		identity, err := lc.WhoIs(request.Context(), request.RemoteAddr)
		if err != nil || identity == nil || identity.UserProfile == nil {
			log.Printf("WhoIs rejected %s: %v", request.RemoteAddr, err)
			http.Error(w, "Tailnet identity could not be verified", http.StatusForbidden)
			return
		}
		login := strings.TrimSpace(identity.UserProfile.LoginName)
		if login == "" {
			http.Error(w, "Tailnet login is unavailable", http.StatusForbidden)
			return
		}
		device := "tailnet-device"
		if identity.Node != nil {
			if identity.Node.ComputedName != "" {
				device = identity.Node.ComputedName
			} else if identity.Node.Name != "" {
				device = strings.TrimSuffix(identity.Node.Name, ".")
			}
		}
		request.Header.Del("Tailscale-User-Login")
		request.Header.Del("X-EvoFlux-Device-Label")
		request.Header.Del("X-EvoFlux-Remote-Proxy")
		request.Header.Del("X-EvoFlux-Remote-Token")
		request.Header.Set("Tailscale-User-Login", login)
		request.Header.Set("X-EvoFlux-Device-Label", device)
		request.Header.Set("X-EvoFlux-Remote-Proxy", proxyMarker)
		request.Header.Set("X-EvoFlux-Remote-Token", a.proxyKey)
		proxy.ServeHTTP(w, request)
	})
}

func (a *tailnetApp) stopServe() error {
	a.serveMu.Lock()
	defer a.serveMu.Unlock()
	a.mu.Lock()
	server := a.httpServer
	listener := a.listener
	a.httpServer = nil
	a.listener = nil
	a.serveURL = ""
	a.mu.Unlock()
	if server != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		return server.Shutdown(ctx)
	}
	if listener != nil {
		return listener.Close()
	}
	return nil
}

func (a *tailnetApp) close() {
	a.shutdownOnce.Do(func() { close(a.shutdown) })
	_ = a.stopServe()
	select {
	case <-a.startDone:
		_ = a.ts.Close()
	case <-time.After(5 * time.Second):
		log.Print("embedded tailscale did not finish starting before shutdown")
	}
}

func (a *tailnetApp) requestShutdown() {
	a.shutdownOnce.Do(func() { close(a.shutdown) })
}

func (a *tailnetApp) controlHandler(controlKey string) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/status", func(w http.ResponseWriter, request *http.Request) {
		writeJSON(w, http.StatusOK, a.snapshot(request.Context()))
	})
	mux.HandleFunc("POST /v1/login", func(w http.ResponseWriter, request *http.Request) {
		if err := a.login(request.Context()); err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": err.Error()})
			return
		}
		var payload statusPayload
		for attempt := 0; attempt < 12; attempt++ {
			payload = a.snapshot(request.Context())
			if payload.Tailscale.LoggedIn || payload.Tailscale.AuthURL != "" {
				break
			}
			time.Sleep(250 * time.Millisecond)
		}
		writeJSON(w, http.StatusOK, payload)
	})
	mux.HandleFunc("POST /v1/enable", func(w http.ResponseWriter, request *http.Request) {
		if err := a.setEnabled(true); err != nil {
			payload := a.snapshot(request.Context())
			payload.Tailscale.Error = err.Error()
			writeJSON(w, http.StatusConflict, payload)
			return
		}
		writeJSON(w, http.StatusOK, a.snapshot(request.Context()))
	})
	mux.HandleFunc("POST /v1/disable", func(w http.ResponseWriter, request *http.Request) {
		if err := a.setEnabled(false); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, a.snapshot(request.Context()))
	})
	mux.HandleFunc("POST /v1/logout", func(w http.ResponseWriter, request *http.Request) {
		_ = a.setEnabled(false)
		a.mu.Lock()
		lc := a.lc
		a.mu.Unlock()
		if lc == nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "embedded tailscale is still starting"})
			return
		}
		if err := lc.Logout(request.Context()); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, a.snapshot(request.Context()))
	})
	mux.HandleFunc("POST /v1/shutdown", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
		go a.requestShutdown()
	})

	return http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		provided := strings.TrimPrefix(request.Header.Get("Authorization"), "Bearer ")
		if len(provided) != len(controlKey) || subtle.ConstantTimeCompare([]byte(provided), []byte(controlKey)) != 1 {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		mux.ServeHTTP(w, request)
	})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func main() {
	var (
		stateDir = flag.String("state-dir", "", "persistent tsnet state directory")
		hostname = flag.String("hostname", "evoflux", "tailnet hostname")
		target   = flag.String("target", "", "loopback EvoFlux backend URL")
		parent   = flag.Int("parent-pid", 0, "exit when this parent process exits")
		showVer  = flag.Bool("version", false, "print version and exit")
	)
	flag.Parse()
	if *showVer {
		fmt.Println(version)
		return
	}
	controlKey := os.Getenv(controlTokenEnv)
	proxyKey := os.Getenv(proxyTokenEnv)
	if *stateDir == "" || *target == "" || controlKey == "" || proxyKey == "" {
		log.Fatalf("state-dir, target, %s and %s are required", controlTokenEnv, proxyTokenEnv)
	}

	app, err := newTailnetApp(*stateDir, *hostname, *target, proxyKey)
	if err != nil {
		log.Fatal(err)
	}
	controlListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		log.Fatalf("listen for control API: %v", err)
	}
	controlServer := &http.Server{
		Handler:           app.controlHandler(controlKey),
		ReadHeaderTimeout: 5 * time.Second,
	}
	port := controlListener.Addr().(*net.TCPAddr).Port
	payload, _ := json.Marshal(handshake{Port: port, PID: os.Getpid(), Version: version})
	fmt.Printf("%s%s\n", handshakePrefix, payload)

	go func() {
		if err := controlServer.Serve(controlListener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("control server stopped: %v", err)
			app.requestShutdown()
		}
	}()
	go app.start()

	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	if *parent > 0 {
		go func() {
			ticker := time.NewTicker(2 * time.Second)
			defer ticker.Stop()
			for range ticker.C {
				if !processAlive(*parent) {
					log.Printf("parent process %d exited", *parent)
					app.requestShutdown()
					return
				}
			}
		}()
	}

	select {
	case <-signals:
	case <-app.shutdown:
	}
	app.close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_ = controlServer.Shutdown(ctx)
	log.Printf("evoflux-tailnet %s stopped (%s/%s)", version, runtime.GOOS, runtime.GOARCH)
}
