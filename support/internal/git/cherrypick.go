package git

import (
	"context"
	"fmt"
	"go.chromium.org/luci/buildbucket/proto"
	"log"
	"net/http"
	"strings"
	sgerrit "support/internal/gerrit"
)

// CheckCherryPick checks if the provided GerritChanges can be merged into
// their target project-branches without needing a rebase. It returns a list
// of errors of any failures to cherry pick, or an empty slice if all cherry
// picks are successful.
//
// The provided changes may span various Gerrit instances, projects, and
// branches. Their ordering matters, as they will be cherry picked in order
// from first to last.
func CheckCherryPick(
	ctx context.Context,
	httpClient *http.Client,
	tmpRoot string,
	changes []buildbucketpb.GerritChange) []error {
	errs := make([]error, 0)
	sChanges := mustFetchChanges(changes, ctx, httpClient)

	// e.g.
	// https://chromium-review.googlesource.com/chromiumos/third_party/kernel -> master -> change
	projectUrlBranchChanges := make(map[string]map[string][]*sgerrit.Change)
	for _, c := range sChanges {
		url := fmt.Sprintf("%s/%s", fullHost(c.Host), c.Info.Project)
		if _, found := projectUrlBranchChanges[url]; !found {
			projectUrlBranchChanges[url] = make(map[string][]*sgerrit.Change)
		}
		projectUrlBranchChanges[url][c.Info.Branch] = append(projectUrlBranchChanges[url][c.Info.Branch], c)
	}
	for url, branchChanges := range projectUrlBranchChanges {
	branchLoop:
		for branch, changes := range branchChanges {
			// Future optimization possibility: the cloning could be done concurrently
			// over several repos at once. That would clutter up logging/debuggability
			// somewhat, so it's been left out for now.
			repoDir, err := Clone(ctx, url, branch, tmpRoot)
			if err != nil {
				log.Printf("error cloning %s at branch %s", url, branch)
				errs = append(errs, err)
				continue branchLoop
			}
			log.Printf("clone repoDir %s", repoDir)
			for _, c := range changes {
				fmt.Printf("*\n* Checking change %s:%d\n*\n", c.Host, c.Number)
				err := FetchAndCherryPick(ctx, c.RevisionInfo, url, repoDir)
				if err != nil {
					log.Printf("error cherry-picking %s", c.RevisionInfo.Ref)
					errs = append(errs, err)
				}
				log.Printf("Successfully cherry-picked %d", c.Number)
			}
		}
	}
	return errs
}

func mustFetchChanges(changes []buildbucketpb.GerritChange, ctx context.Context, httpClient *http.Client) sgerrit.Changes {
	var sChanges sgerrit.Changes
	for _, gc := range changes {
		sChanges = append(sChanges, &sgerrit.Change{
			Host:     gc.Host,
			Number:   int(gc.Change),
			PatchSet: int(gc.Patchset),
		})
	}
	sgerrit.MustFetchChanges(ctx, httpClient, sChanges, sgerrit.Options{})
	return sChanges
}

// fullHost converts a Gerrit host into a canonical https form, e.g.
// https://chromium-review.googlesource.com
func fullHost(host string) string {
	if !strings.ContainsRune(host, '.') {
		host = host + "-review.googlesource.com"
	}
	if !strings.HasPrefix(host, "https://") {
		host = "https://" + host
	}
	return host
}
