package gerrit

import (
	"context"
	"fmt"
	"go.chromium.org/luci/common/api/gitiles"
	gitilespb "go.chromium.org/luci/common/proto/gitiles"
	"log"
	"net/http"
	"strings"
	"support/internal/shared"
	"time"
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
	ctx, _ = context.WithTimeout(ctx, 5*time.Minute)
	ch := make(chan *gitilespb.RefsResponse, 1)
	err = shared.DoWithRetry(ctx, shared.DefaultOpts, func() error {
		// This sets the deadline for the individual API call, while the outer context sets
		// an overall timeout for all attempts.
		innerCtx, _ := context.WithTimeout(ctx, 30*time.Second)
		resp, err := client.Refs(innerCtx, &gitilespb.RefsRequest{Project: branch.Project, RefsPath: ref})
		if err != nil {
			return err
		}
		ch <- resp
		return nil
	})
	if err != nil {
		log.Fatal(err)
	}
	resp := <- ch
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
