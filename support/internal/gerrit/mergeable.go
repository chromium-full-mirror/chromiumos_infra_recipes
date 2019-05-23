package gerrit

import (
	"context"
	"go.chromium.org/luci/common/api/gerrit"
	gerritpb "go.chromium.org/luci/common/proto/gerrit"
	"log"
	"net/http"
	"strings"
	"support/internal/shared"
	"time"
)

type MergeableInput struct {
	// Full (chromium-review.googlesource.com) or short (chromium) gerrit host.
	Host string `json:"host"`
	// Change number requested.
	Number int64 `json:"change_number"`
	// The project of this change. For example, "chromium/src".
	Project string `json:"project"`
	// Unique ID for the revision to query. See
	// https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#revision-id
	RevisionId string `json:"revision_id"`
	// The source to merge from, e.g. a complete or abbreviated commit SHA-1, a
	// complete reference name, a short reference name under refs/heads,
	// refs/tags, or refs/remotes namespace, etc.
	Source string `json:"source"`
	// The strategy of the merge. See gerritpb.MergeableStrategy for permissible values.
	Strategy string `json:"mergeable_strategy"`
}

type MergeableOutput struct {
	// Submit type used for this change. See gerritpb.MergeableInfo_SubmitType for permissible values.
	SubmitType string `json:"submit_type"`
	// The strategy of the merge. See gerritpb.MergeableStrategy for permissible values.
	Strategy string `json:"mergeable_strategy"`
	// true if this change is cleanly mergeable, false otherwise.
	Mergeable bool `json:"mergeable"`
	// true if this change is already merged, false otherwise.
	CommitMerged bool `json:"commit_merged"`
	// true if the content of this change is already merged, false otherwise.
	ContentMerged bool `json:"content_merged"`
	// A list of paths with conflicts.
	Conflicts []string `json:"conflicts"`
	// A list of other branch names where this change could merge cleanly.
	MergeableInto []string `json:"mergeable_into"`
}

// MustFetchBranch retrieves branch metadata from Gitiles.
func MustGetMergeable(ctx context.Context, httpClient *http.Client, input MergeableInput) *MergeableOutput {
	if !strings.ContainsRune(input.Host, '.') {
		input.Host = input.Host + shortHostSuffix
	}
	client, err := gerrit.NewRESTClient(httpClient, input.Host, true)
	if err != nil {
		log.Fatalf("error creating Gerrit client: %v", err)
	}
	ctx, _ = context.WithTimeout(ctx, 5*time.Minute)
	ch := make(chan *gerritpb.MergeableInfo, 1)
	err = shared.DoWithRetry(ctx, shared.DefaultOpts, func() error {
		// This sets the deadline for the individual API call, while the outer context sets
		// an overall timeout for all attempts.
		innerCtx, _ := context.WithTimeout(ctx, 30*time.Second)
		resp, err := client.GetMergeable(innerCtx, &gerritpb.GetMergeableRequest{
			Project: input.Project,
			Number: input.Number,
			RevisionId: input.RevisionId,
			Strategy: gerritpb.MergeableStrategy(gerritpb.MergeableStrategy_value[input.Strategy]),
			Source: input.Source})
		if err != nil {
			return err
		}
		ch <- resp
		return nil
	})
	if err != nil {
		log.Fatal(err)
	}
	resp := <-ch
	return &MergeableOutput{
		SubmitType:    resp.SubmitType.String(),
		Strategy:      resp.Strategy.String(),
		Mergeable:     resp.Mergeable,
		CommitMerged:  resp.CommitMerged,
		ContentMerged: resp.ContentMerged,
		Conflicts:     resp.Conflicts,
		MergeableInto: resp.MergeableInto,
	}
}
