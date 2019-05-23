package cli

import (
	"golang.org/x/oauth2"
	"net/http"

	"go.chromium.org/luci/auth"
	"go.chromium.org/luci/auth/client/authcli"
	"go.chromium.org/luci/hardcoded/chromeinfra"
)

var (
	authOptions = chromeinfra.DefaultAuthOptions()
	authFlags   authcli.Flags
)

// Set the auth scopes. Must be called before Init.
func SetAuthScopes(scopes ...string) {
	assertInited(false)
	authOptions.Scopes = scopes
}

// Return an authenticated HTTP client. Must be called after Init.
func AuthenticatedHTTPClient() (*http.Client, error) {
	assertInited(true)
	authOptions, err := authFlags.Options()
	if err != nil {
		return nil, err
	}
	authenticator := auth.NewAuthenticator(Context, auth.SilentLogin, authOptions)
	return authenticator.Client()
}

// Return an authenticated TokenSource. Must be called after Init.
func AuthenticatedTokenSource() (oauth2.TokenSource, error) {
	assertInited(true)
	authOptions, err := authFlags.Options()
	if err != nil {
		return nil, err
	}
	authenticator := auth.NewAuthenticator(Context, auth.SilentLogin, authOptions)
	return authenticator.TokenSource()
}
