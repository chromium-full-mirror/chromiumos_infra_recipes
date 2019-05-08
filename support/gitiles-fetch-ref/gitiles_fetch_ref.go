package main

import (
	"log"

	"go.chromium.org/luci/auth"
	"go.chromium.org/luci/common/api/gerrit"

	"support/internal/cli"
	sgerrit "support/internal/gerrit"
)

type Input struct {
	Branch sgerrit.Branch `json:"branch"`
}

type Output struct {
	Branch sgerrit.Branch `json:"branch"`
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
	branch := input.Branch

	branch = sgerrit.MustFetchBranch(cli.Context, httpClient, branch)
	cli.MustMarshalOutput(Output{Branch: branch})
}
