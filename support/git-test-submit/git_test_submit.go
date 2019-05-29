package main

import (
	"context"
	"go.chromium.org/luci/auth"
	"go.chromium.org/luci/common/api/gerrit"
	"log"
	"os"
	"support/internal/cli"
	sgerrit "support/internal/gerrit"
	"support/internal/git"
)

type Input struct {
	TempDir       string          `json:"temp_dir"`
	GerritChanges sgerrit.Changes `json:"gerrit_changes"`
}

type Output struct {
	Errors []string `json:"errors"`
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

	ctx := context.Background()

	output := &Output{}
	if input.TempDir == "" {
		input.TempDir = os.TempDir()
	}
	errs := git.CheckCherryPick(ctx, httpClient, input.TempDir, input.GerritChanges)
	for i, err := range errs {
		log.Printf("Error %d/%d\n%s", i+1, len(errs), err.Error())
		output.Errors = append(output.Errors, err.Error())
	}
	cli.MustMarshalOutput(output)
}
