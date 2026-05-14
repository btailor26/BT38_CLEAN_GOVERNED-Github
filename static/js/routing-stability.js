/**
 * SECTION X: URL Freeze / Routing Stability Fix
 * Prevents page freezes, ensures graceful error handling, and provides auto-recovery
 */

(function() {
    'use strict';

    const RoutingStability = {
        config: {
            apiTimeout: 4000,
            pageLoadTimeout: 4000,
            healthCheckUrl: '/api/system/health',
            dashboardUrl: '/',
            retryDelay: 1000,
            maxRetries: 2
        },

        state: {
            pageLoadStart: Date.now(),
            loadingOverlayActive: false,
            currentRoute: window.location.pathname,
            failedRoutes: [],
            consecutiveHealthFailures: 0,
            navigationTimeoutId: null,
            overlayDelayId: null
        },

        init: function() {
            this.injectStyles();
            this.createLoadingOverlay();
            this.wrapFetch();
            this.setupPageLoadTimeout();
            this.setupNavigationMonitor();
            this.setupHealthCheck();
            this.logRouteAccess();
            this.setupAutoRecovery(15000);
            console.log('[RoutingStability] Initialized');
        },

        injectStyles: function() {
            const style = document.createElement('style');
            style.textContent = `
                #rs-loading-overlay {
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background: rgba(0, 0, 0, 0.7);
                    display: none;
                    align-items: center;
                    justify-content: center;
                    z-index: 9999;
                    flex-direction: column;
                }
                #rs-loading-overlay.active {
                    display: flex;
                }
                #rs-loading-content {
                    text-align: center;
                    color: white;
                    padding: 30px;
                    background: #1a1a2e;
                    border-radius: 10px;
                    max-width: 400px;
                }
                #rs-loading-spinner {
                    width: 50px;
                    height: 50px;
                    border: 4px solid rgba(255,255,255,0.3);
                    border-top-color: #4dabf7;
                    border-radius: 50%;
                    animation: rs-spin 1s linear infinite;
                    margin: 0 auto 20px;
                }
                @keyframes rs-spin {
                    to { transform: rotate(360deg); }
                }
                #rs-loading-message {
                    font-size: 16px;
                    margin-bottom: 15px;
                }
                #rs-loading-timer {
                    font-size: 12px;
                    color: #adb5bd;
                    margin-bottom: 15px;
                }
                .rs-btn {
                    padding: 10px 20px;
                    border: none;
                    border-radius: 5px;
                    cursor: pointer;
                    margin: 5px;
                    font-size: 14px;
                }
                .rs-btn-primary {
                    background: #4dabf7;
                    color: white;
                }
                .rs-btn-secondary {
                    background: #6c757d;
                    color: white;
                }
                .rs-btn:hover {
                    opacity: 0.9;
                }
                #rs-error-banner {
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    background: #dc3545;
                    color: white;
                    padding: 10px 20px;
                    text-align: center;
                    z-index: 9998;
                    display: none;
                }
                #rs-error-banner.active {
                    display: block;
                }
            `;
            document.head.appendChild(style);
        },

        createLoadingOverlay: function() {
            const overlay = document.createElement('div');
            overlay.id = 'rs-loading-overlay';
            overlay.innerHTML = `
                <div id="rs-loading-content">
                    <div id="rs-loading-spinner"></div>
                    <div id="rs-loading-message">Loading...</div>
                    <div id="rs-loading-timer"></div>
                    <div id="rs-loading-actions" style="display:none;">
                        <button class="rs-btn rs-btn-primary" onclick="RoutingStability.retryLoad()">Retry</button>
                        <button class="rs-btn rs-btn-secondary" onclick="RoutingStability.goToDashboard()">Go to Dashboard</button>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);

            const banner = document.createElement('div');
            banner.id = 'rs-error-banner';
            banner.innerHTML = '<span id="rs-error-text">Server temporarily unreachable</span> <button class="rs-btn rs-btn-primary" style="padding:5px 10px;margin-left:10px;" onclick="RoutingStability.dismissBanner()">Dismiss</button>';
            document.body.appendChild(banner);
        },

        showLoading: function(message) {
            this.state.loadingOverlayActive = true;
            const overlay = document.getElementById('rs-loading-overlay');
            const msgEl = document.getElementById('rs-loading-message');
            const actionsEl = document.getElementById('rs-loading-actions');
            
            if (overlay) {
                overlay.classList.add('active');
                if (msgEl) msgEl.textContent = message || 'Loading...';
                if (actionsEl) actionsEl.style.display = 'none';
            }
        },

        hideLoading: function() {
            this.state.loadingOverlayActive = false;
            const overlay = document.getElementById('rs-loading-overlay');
            if (overlay) {
                overlay.classList.remove('active');
            }
        },

        showLoadingError: function(message) {
            const msgEl = document.getElementById('rs-loading-message');
            const actionsEl = document.getElementById('rs-loading-actions');
            const spinnerEl = document.getElementById('rs-loading-spinner');
            
            if (msgEl) msgEl.textContent = message || 'Page load failed';
            if (actionsEl) actionsEl.style.display = 'block';
            if (spinnerEl) spinnerEl.style.display = 'none';
            
            this.logRouteFailure(this.state.currentRoute, message);
        },

        showBanner: function(message) {
            const banner = document.getElementById('rs-error-banner');
            const textEl = document.getElementById('rs-error-text');
            if (banner) {
                banner.classList.add('active');
                if (textEl) textEl.textContent = message;
            }
        },

        dismissBanner: function() {
            const banner = document.getElementById('rs-error-banner');
            if (banner) banner.classList.remove('active');
        },

        retryLoad: function() {
            window.location.reload();
        },

        goToDashboard: function() {
            window.location.href = this.config.dashboardUrl;
        },

        wrapFetch: function() {
            const originalFetch = window.fetch;
            const self = this;

            window.fetch = function(url, options = {}) {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => {
                    controller.abort();
                    console.warn(`[RoutingStability] Request timeout: ${url}`);
                }, self.config.apiTimeout);

                const fetchOptions = {
                    ...options,
                    signal: controller.signal
                };

                return originalFetch(url, fetchOptions)
                    .then(response => {
                        clearTimeout(timeoutId);
                        return response;
                    })
                    .catch(error => {
                        clearTimeout(timeoutId);
                        if (error.name === 'AbortError') {
                            self.logRouteFailure(url, 'Request timed out after ' + self.config.apiTimeout + 'ms');
                            throw new Error('Request timed out – try again or view jobs tab.');
                        }
                        throw error;
                    });
            };
        },

        setupPageLoadTimeout: function() {
            const self = this;
            
            window.addEventListener('load', function() {
                self.hideLoading();
                console.log('[RoutingStability] Page loaded successfully');
            });

            setTimeout(function() {
                if (document.readyState !== 'complete') {
                    self.showLoading('Page taking longer than expected...');
                    
                    setTimeout(function() {
                        if (document.readyState !== 'complete') {
                            self.showLoadingError('Page load failed – retry or return to dashboard.');
                            self.checkHealth();
                        }
                    }, self.config.pageLoadTimeout);
                }
            }, self.config.pageLoadTimeout);
        },

        setupNavigationMonitor: function() {
            const self = this;

            document.addEventListener('click', function(e) {
                const link = e.target.closest('a[href]');
                if (link && link.href && !link.href.startsWith('javascript:') && !link.target) {
                    const isInternal = link.hostname === window.location.hostname;
                    if (isInternal && !link.href.includes('#')) {
                        self.state.currentRoute = new URL(link.href).pathname;
                    }
                }
            });

            window.addEventListener('beforeunload', function() {
                // Clear any pending timeouts to prevent stale handlers
                if (self.state.navigationTimeoutId) {
                    clearTimeout(self.state.navigationTimeoutId);
                }
                if (self.state.overlayDelayId) {
                    clearTimeout(self.state.overlayDelayId);
                }
                
                // DELAY showing overlay - only show if navigation is genuinely slow
                // This prevents the overlay from appearing during fast page transitions
                self.state.overlayDelayId = setTimeout(function() {
                    self.showLoading('Navigating...');
                    self.state.navigationTimeoutId = setTimeout(function() {
                        if (self.state.loadingOverlayActive) {
                            console.log('[RoutingStability] Navigation timeout - showing recovery options');
                            self.showLoadingError('Navigation taking too long. Retry or return to dashboard.');
                        }
                    }, 8000);
                }, 200); // Only show overlay if navigation takes longer than 200ms
            });
            
            // Clean up on page hide (covers bfcache and normal navigation)
            window.addEventListener('pagehide', function() {
                if (self.state.navigationTimeoutId) {
                    clearTimeout(self.state.navigationTimeoutId);
                }
                if (self.state.overlayDelayId) {
                    clearTimeout(self.state.overlayDelayId);
                }
                self.hideLoading();
            });
        },

        setupHealthCheck: function() {
            const self = this;
            
            setInterval(function() {
                if (self.state.loadingOverlayActive) {
                    self.checkHealth();
                }
            }, 5000);
        },

        checkHealth: async function() {
            const self = this;
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 3000);
                
                const response = await fetch(this.config.healthCheckUrl, {
                    signal: controller.signal,
                    credentials: 'same-origin'
                });
                clearTimeout(timeoutId);
                
                if (response.ok) {
                    const data = await response.json();
                    if (data.status === 'ok') {
                        console.log('[RoutingStability] Health check passed - issue is frontend');
                        this.state.consecutiveHealthFailures = 0;
                        this.dismissBanner();
                        return true;
                    }
                }
                this.state.consecutiveHealthFailures++;
                console.warn('[RoutingStability] Health check failed, count:', this.state.consecutiveHealthFailures);
                if (this.state.consecutiveHealthFailures >= 2) {
                    this.showBanner('Server temporarily unreachable.');
                }
                return false;
            } catch (error) {
                this.state.consecutiveHealthFailures++;
                console.error('[RoutingStability] Health check error, count:', this.state.consecutiveHealthFailures, error);
                if (this.state.consecutiveHealthFailures >= 2) {
                    this.showBanner('Server temporarily unreachable.');
                }
                return false;
            }
        },

        logRouteAccess: function() {
            const entry = {
                route: window.location.pathname,
                timestamp: new Date().toISOString(),
                userAgent: navigator.userAgent.substring(0, 100)
            };
            
            try {
                /* disabled dead route logger */ void(0);/*
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(entry),
                    credentials: 'same-origin'
                }).catch(() => {});
            } catch (e) {}
        },

        logRouteFailure: function(route, reason) {
            const entry = {
                route: route,
                reason: reason,
                timestamp: new Date().toISOString()
            };
            
            this.state.failedRoutes.push(entry);
            console.error('[RoutingStability] Route failure:', entry);
            
            try {
                /* disabled dead route failure logger */ void(0);/*
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(entry),
                    credentials: 'same-origin'
                }).catch(() => {});
            } catch (e) {}
        },

        setupAutoRecovery: function(timeoutMs) {
            const self = this;
            setTimeout(function() {
                if (self.state.loadingOverlayActive) {
                    console.log('[RoutingStability] Auto-recovering to dashboard');
                    self.logRouteFailure(self.state.currentRoute, 'Auto-recovery triggered after timeout');
                    window.location.href = self.config.dashboardUrl;
                }
            }, timeoutMs || 10000);
        }
    };

    window.RoutingStability = RoutingStability;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            RoutingStability.init();
        });
    } else {
        RoutingStability.init();
    }

})();

window.safeApiCall = async function(url, options = {}, fallbackValue = null) {
    try {
        const response = await fetch(url, {
            credentials: 'same-origin',
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        }
        return await response.text();
    } catch (error) {
        console.error(`[safeApiCall] Error calling ${url}:`, error);
        return fallbackValue;
    }
};

window.submitBackgroundJob = async function(url, data, successMessage) {
    try {
        RoutingStability.showLoading('Starting background job...');
        
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
            credentials: 'same-origin'
        });
        
        RoutingStability.hideLoading();
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }
        
        const result = await response.json();
        
        if (result.job_id || result.queued || result.success) {
            if (successMessage) {
                alert(successMessage);
            }
            return result;
        }
        
        return result;
    } catch (error) {
        RoutingStability.hideLoading();
        console.error('[submitBackgroundJob] Error:', error);
        alert('Operation failed: ' + error.message);
        throw error;
    }
};
