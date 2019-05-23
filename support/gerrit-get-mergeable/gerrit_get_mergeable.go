package main

import (
	"log"

	"go.chromium.org/luci/auth"
	"go.chromium.org/luci/common/api/gerrit"

	"support/internal/cli"
	sgerrit "support/internal/gerrit"
)

type Input struct {
	MergeableInput sgerrit.MergeableInput `json:"mergeable_input"`
}

type Output struct {
	MergeableOutput sgerrit.MergeableOutput `json:"mergeable_output"`
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

	output := sgerrit.MustGetMergeable(cli.Context, httpClient, input.MergeableInput)
	cli.MustMarshalOutput(Output{MergeableOutput: *output})
}
