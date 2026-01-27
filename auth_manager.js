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

        // Safety check: If ID is still the placeholder, don't try to render
        if (!this.clientId || this.clientId.includes('PASTE_YOUR_CLIENT_ID')) {
            return;
        }

        const checkGoogle = setInterval(() => {
            if (window.google) {
                clearInterval(checkGoogle);
                window.google.accounts.id.initialize({
                    client_id: this.clientId,
                    callback: this.handleCredentialResponse.bind(this)
                });
                
                const element = document.getElementById(elementId);
                if (element) {
                    window.google.accounts.id.renderButton(
                        element,
                        { theme: "outline", size: "large" }
                    );
                }
            }
        }, 100);
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