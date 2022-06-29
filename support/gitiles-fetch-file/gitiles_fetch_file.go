// Copyright 2022 The ChromiumOS Authors.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package main

import (
	"log"

	"go.chromium.org/luci/auth"
	"go.chromium.org/luci/common/api/gerrit"

	"support/internal/cli"
	sgerrit "support/internal/gerrit"
)

type Input struct {
	File sgerrit.File `json:"file"`
}

type Output struct {
	File sgerrit.File `json:"file"`
}

func main() {
	cli.SetAuthScopes(auth.OAuthScopeEmail, gerrit.OAuthScope)
	cli.Init()

	httpClient, err := cli.AuthenticatedHTTPClient()
	if err != nil {
		log.Fatal(err)
	}

	var input Input
	cli.MustUnmarshalInput(&input)
	file := input.File

	file = sgerrit.MustFetchFile(cli.Context, httpClient, file)

	cli.MustMarshalOutput(Output{File: file})
}
