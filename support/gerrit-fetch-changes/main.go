package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"go.chromium.org/luci/auth"
	"go.chromium.org/luci/common/api/gerrit"

	"chromium.googlesource.com/chromiumos/infra/recipes/support/internal/cli"
)

const (
	shortHostSuffix = "-review.googlesource.com"
)

type Change struct {
	// Full (chromium-review.googlesource.com) or short (chromium) gerrit host.
	Host string `json:"host"`
	// Change number requested.
	Number int `json:"change_number"`
	// Patch set number as requested. If -1, fetch "current" patch set.
	PatchSet int `json:"patch_set"`

	// Change info if found.
	Info *gerrit.Change `json:"info"`
	// Patch set info if found.
	PatchSetRevision string               `json:"patch_set_revision"`
	RevisionInfo     *gerrit.RevisionInfo `json:"revision_info"`
}

type Changes []*Change

type Options struct {
	IncludeFiles bool `json:"include_files"`
}

type Input struct {
	Changes Changes `json:"changes"`
	Options
}

type Output struct {
	Changes Changes `json:"changes"`
}

func changesToQueryParams(changes Changes, options Options) gerrit.ChangeQueryParams {
	var (
		queryOrs        []string
		currentRevision = false
		allRevisions    = false
	)
	for _, change := range changes {
		queryOrs = append(queryOrs, fmt.Sprintf("change:{%d}", change.Number))
		if change.PatchSet == -1 {
			currentRevision = true
		} else if change.PatchSet != 0 {
			allRevisions = true
		}
	}
	queryOpts := []string{}
	if allRevisions {
		queryOpts = append(queryOpts, "ALL_REVISIONS")
	} else if currentRevision {
		queryOpts = append(queryOpts, "CURRENT_REVISION")
	}
	if options.IncludeFiles {
		queryOpts = append(queryOpts, "ALL_FILES")
	}
	return gerrit.ChangeQueryParams{
		Query:   strings.Join(queryOrs, " OR "),
		N:       len(changes),
		Options: queryOpts,
	}
}

func updateChangeFromResults(change *Change, results []*gerrit.Change) {
	for _, candidate := range results {
		if candidate.ChangeNumber == change.Number {
			change.Info = candidate
			break
		}
	}
	if change.Info == nil {
		return
	}

	var foundRev string
	if change.PatchSet == -1 {
		foundRev = change.Info.CurrentRevision
	} else if change.PatchSet != 0 {
		for rev, revInfo := range change.Info.Revisions {
			if revInfo.PatchSetNumber == change.PatchSet {
				foundRev = rev
				break
			}
		}
	}
	if revInfo, ok := change.Info.Revisions[foundRev]; ok {
		change.PatchSetRevision = foundRev
		change.RevisionInfo = &revInfo
	}
	change.Info.Revisions = nil
}

func fetchHostChanges(
	ctx context.Context, httpClient *http.Client,
	host string, changes Changes, options Options,
) error {
	client, err := gerrit.NewClient(httpClient, fmt.Sprintf("https://%s", host))
	if err != nil {
		return err
	}
	queryParams := changesToQueryParams(changes, options)
	results, more, err := client.ChangeQuery(ctx, queryParams)
	if err != nil {
		return err
	}
	if more {
		// Shouldn't happen, but log just in case.
		log.Print("WARNING: more results than expected!")
	}
	for _, c := range changes {
		updateChangeFromResults(c, results)
	}
	return nil
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

	// Group changes by host.
	hostChanges := make(map[string]Changes)
	for _, c := range changes {
		host := c.Host
		if !strings.ContainsRune(host, '.') {
			host = host + shortHostSuffix
		}
		hostChanges[host] = append(hostChanges[host], c)
	}

	// Error management for parallel requests.
	var hostErrors sync.Map
	var wg sync.WaitGroup
	ctx, cancel := context.WithTimeout(cli.Context, 1*time.Minute)
	defer cancel()

	// Parallel request per host.
	for host, changes := range hostChanges {
		// Copy loop variables into scope.
		host, changes := host, changes
		wg.Add(1)
		go func() {
			defer wg.Done()
			err := fetchHostChanges(ctx, httpClient, host, changes, options)
			if err != nil {
				hostErrors.Store(host, err)
				cancel()
			}
		}()
	}
	wg.Wait()

	failed := false
	hostErrors.Range(func(host, err interface{}) bool {
		log.Printf("request to %s failed: %v", host, err)
		failed = true
		return true
	})
	if failed {
		os.Exit(1)
	}

	cli.MustMarshalOutput(Output{Changes: changes})
}
