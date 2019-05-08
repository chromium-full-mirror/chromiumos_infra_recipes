package gerrit

import (
	"context"
	"fmt"
	"go.chromium.org/luci/common/api/gitiles"
	gitilespb "go.chromium.org/luci/common/proto/gitiles"
	"log"
	"net/http"
	"strings"
)

const(
	shortGitilesHostSuffix = ".googlesource.com"
)

type Branch struct {
	// Requested full (chromium-review.googlesource.com) or short (chromium) gerrit host.
	Host string `json:"host"`
	// Requested gerrit repo, e.g. "chromiumos/chromite".
	Project string `json:"project"`
	// Requested branch from the repo, e.g. "master".
	Branch string `json:"branch"`
	// Returned HEAD revision from that branch.
	Revision string `json:"revision"`
}

// MustFetchBranch retrieves branch metadata from Gitiles.
func MustFetchBranch(ctx context.Context, httpClient *http.Client, branch Branch) Branch {
	host := branch.Host
	if !strings.ContainsRune(host, '.') {
		host = host + shortGitilesHostSuffix
	}
	client, err := gitiles.NewRESTClient(httpClient, host, true)
	if err != nil {
		log.Fatalf("error creating Gitiles client: %v", err)
	}
	ref := "refs/heads/" + branch.Branch
	resp, err := client.Refs(ctx, &gitilespb.RefsRequest{Project: branch.Project, RefsPath: ref})
	if err != nil {
		log.Fatalf("error fetching ref: %v", err)
	}
	// For some weird reason, a request of "refs/heads/master" comes back in the response as
	// "refs/heads/master/refs/heads/master". Maybe it's a bug somewhere? In the meantime, let's
	// handle this case and the eventually-fixed case.
	if rev, found := resp.Revisions[fmt.Sprintf("%s/%s", ref, ref)]; found {
		branch.Revision = rev
	}
	if rev, found := resp.Revisions[ref]; found {
		branch.Revision = rev
	}
	if branch.Revision == "" {
		log.Fatalf("found no revision in response: %v", resp)
	}
	return branch
}
