package main

import (
	"log"

	"go.chromium.org/luci/auth"
	"go.chromium.org/luci/common/api/gerrit"

	"support/internal/cli"
	sgerrit "support/internal/gerrit"
)

type Input struct {
	Changes sgerrit.Changes `json:"changes"`
	sgerrit.Options
}

type Output struct {
	Changes sgerrit.Changes `json:"changes"`
}

func main() {
	cli.SetAuthScopes(auth.OAuthScopeEmail, gerrit.OAuthScope)
	cli.Init()

	httpClient, err := cli.AuthenticatedHTTPClient()
	if err != nil {
		log.Fatal(err)
	}

	// Read change requests.
	var input Input
	cli.MustUnmarshalInput(&input)
	changes := input.Changes
	if len(changes) == 0 {
		log.Fatal("no changes requested")
	}
	options := input.Options

	// Fetch changes from each host or die.
	changes = sgerrit.MustFetchChanges(cli.Context, httpClient, changes, options)

	cli.MustMarshalOutput(Output{Changes: changes})
}
