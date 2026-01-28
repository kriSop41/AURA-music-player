// auth_manager.js

class AuthManager {
    constructor(clientId) {
        this.clientId = clientId;
        this.user = null;
        this.onDataLoaded = null; // Callback to update app with cloud data
        this.onUserInfo = null;   // Callback to update UI with user info
    }

    get baseUrl() {
        return (window.location.port === '5500' || window.location.port === '5501' || window.location.protocol === 'file:')
            ? 'http://localhost:10000'
            : '';
    }

    initialize(dataLoadedCallback, userInfoCallback) {
        this.onDataLoaded = dataLoadedCallback;
        this.onUserInfo = userInfoCallback;
        
        // Load Google Identity Services script dynamically
        if (!document.getElementById('google-client-script')) {
            const script = document.createElement('script');
            script.src = "https://accounts.google.com/gsi/client";
            script.id = "google-client-script";
            script.async = true;
            script.defer = true;
            document.body.appendChild(script);
        }
        
        // Check for existing session
        this.checkSession();
    }

    renderLoginButton(elementId) {
        if (this.user) return; // Don't render if already logged in

        let attempts = 0;
        const maxAttempts = 30; // Poll for 3 seconds max

        const tryRender = () => {
            attempts++;
            if (attempts > maxAttempts) {
                console.error("Could not render Google login button: container not visible or GSI not loaded in time.");
                return;
            }

            // 1. Check if GSI script is fully ready
            if (!window.google || !window.google.accounts || !window.google.accounts.id) {
                setTimeout(tryRender, 100); // GSI not ready, wait and try again.
                return;
            }

            const element = document.getElementById(elementId);
            if (!element) {
                console.error("Could not render Google login button: element not found.");
                return;
            }

            // 2. Check if the element is visible in the DOM. `offsetParent` is null for hidden elements.
            if (element.offsetParent === null) {
                setTimeout(tryRender, 100); // Element not visible, wait and try again.
                return;
            }

            // If we reach here, GSI is loaded and the element is visible.
            window.google.accounts.id.initialize({ client_id: this.clientId, callback: this.handleCredentialResponse.bind(this) });
            element.innerHTML = ''; // Clear any previous content

            // Create a custom styled button wrapper
            const wrapper = document.createElement('div');
            Object.assign(wrapper.style, {
                position: 'relative', width: '250px', height: '46px', margin: '0 auto', cursor: 'pointer'
            });

            // The visible "Alive" button
            const customBtn = document.createElement('div');
            customBtn.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 24 24" style="margin-right:12px; min-width:20px">
                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                </svg>
                <span style="font-family: 'Outfit', sans-serif; font-weight: 500; font-size: 15px; color: white;">Sign in with Google</span>
            `;
            Object.assign(customBtn.style, {
                position: 'absolute', top: '0', left: '0', width: '100%', height: '100%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'rgba(255, 255, 255, 0.05)', border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '23px', transition: 'all 0.3s ease', backdropFilter: 'blur(10px)'
            });

            // Hover effects
            wrapper.onmouseenter = () => {
                customBtn.style.background = 'rgba(255, 255, 255, 0.1)';
                customBtn.style.borderColor = '#8b5cf6';
                customBtn.style.boxShadow = '0 0 20px rgba(139, 92, 246, 0.3)';
                customBtn.style.transform = 'translateY(-1px)';
            };
            wrapper.onmouseleave = () => {
                customBtn.style.background = 'rgba(255, 255, 255, 0.05)';
                customBtn.style.borderColor = 'rgba(255, 255, 255, 0.1)';
                customBtn.style.boxShadow = 'none';
                customBtn.style.transform = 'translateY(0)';
            };

            // Invisible Google Button Overlay
            const googleTarget = document.createElement('div');
            Object.assign(googleTarget.style, {
                position: 'absolute', top: '0', left: '0', width: '100%', height: '100%',
                opacity: '0.0001', zIndex: '10', overflow: 'hidden', transform: 'scale(1.1)'
            });

            wrapper.appendChild(customBtn);
            wrapper.appendChild(googleTarget);
            element.appendChild(wrapper);

            window.google.accounts.id.renderButton(googleTarget, { theme: "outline", size: "large", width: 250 });
        };

        // Start the process with a small delay to allow UI to start updating
        setTimeout(tryRender, 100);
    }

    async handleCredentialResponse(response, isAutoLogin = false) {
        try {
            const res = await fetch(`${this.baseUrl}/api/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    credential: response.credential,
                    clientId: this.clientId
                })
            });
            
            const result = await res.json();
            if (result.status === 'success') {
                this.user = { 
                    credential: response.credential,
                    info: result.user_info 
                };
                localStorage.setItem('google_credential', response.credential);
                
                // Update UI with user info
                if (this.onUserInfo && result.user_info) {
                    this.onUserInfo(result.user_info);
                }

                // If cloud has data, load it into the app
                if (this.onDataLoaded && result.data && Object.keys(result.data).length > 0) {
                    this.onDataLoaded(result.data);
                    alert('Data synced from cloud!');
                } else if (!isAutoLogin) {
                    alert('Logged in successfully!');
                }
            } else {
                console.error('Auth failed:', result.error);
                if (isAutoLogin) {
                    localStorage.removeItem('google_credential'); // Clear bad token
                } else {
                    alert('Login Failed: ' + (result.error || 'Unknown server error'));
                }
            }
        } catch (e) {
            console.error('Login failed', e);
            if (!isAutoLogin) alert('Login Failed: Could not connect to server.');
        }
    }

    async syncData(appData) {
        if (!this.user || !this.user.credential) return;
        
        try {
            await fetch(`${this.baseUrl}/api/auth/sync`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    credential: this.user.credential,
                    clientId: this.clientId,
                    data: appData
                })
            });
            console.log('Data synced to cloud');
        } catch (e) {
            console.error('Sync failed', e);
        }
    }
    
    checkSession() {
        const cred = localStorage.getItem('google_credential');
        if (cred) {
            // Attempt to re-login with stored token
            this.handleCredentialResponse({ credential: cred }, true);
        }
    }

    logout() {
        localStorage.removeItem('google_credential');
        this.user = null;
        location.reload();
    }
}

// Replace with your actual Google Client ID
window.authManager = new AuthManager('469577212141-5pqcscb2r8jrthnp15sv9o216sdcrrjg.apps.googleusercontent.com');