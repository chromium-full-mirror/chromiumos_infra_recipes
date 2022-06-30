// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package main

import (
	"log"
	"time"

	"go.chromium.org/luci/auth"
	"go.chromium.org/luci/common/api/gerrit"
	"golang.org/x/oauth2"

	"support/internal/cli"
)

type Token struct {
	// Oauth2 access token.
	Access_Token string `json:"access_token"`
	// When does the token expires.
	Expires time.Time `json:"expires"`
}

type Output struct {
	Token Token `json:"token"`
}

func main() {
	/*
	 * Init a new Client with the right scopes.
	 * Right now there is only one user of this, the cop recipe, so we hardcode
	 * the scopes, if this is used on more recipes it should be passed as a parameter.
	 */
	cli.SetAuthScopes(auth.OAuthScopeEmail, gerrit.OAuthScope, "https://www.googleapis.com/auth/cloud-platform")
	cli.Init()

	// Forge a new Token using the Client TokenSource.
	tokenSource, err := cli.AuthenticatedTokenSource()
	if err != nil {
		log.Fatal(err)

	}
	oauth2.NewClient(cli.Context, tokenSource)
	savedToken, err := tokenSource.Token()
	if err != nil {
		log.Fatal(err)
	}

	// Output the Token and its expiration date.
	var output Token
	output.Access_Token = savedToken.AccessToken
	output.Expires = savedToken.Expiry
	cli.MustMarshalOutput(Output{Token: output})
}
