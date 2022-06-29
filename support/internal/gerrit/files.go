// Copyright 2022 The ChromiumOS Authors.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package gerrit

import (
	"context"
	"log"
	"net/http"
	"strings"

	"go.chromium.org/luci/common/api/gitiles"
	gitilespb "go.chromium.org/luci/common/proto/gitiles"
)

type File struct {
	// Full (chromium.googlesource.com) or short (chromium) gitiles host.
	Host string `json:"host"`
	// Requested gerrit repo, e.g. "chromiumos/chromite".
	Project string `json:"project"`
	// Requested reference from the repo, e.g. "12fabada".
	Ref string `json:"ref"`
	// Requested file path.
	Path string `json:"path"`
	// Returned file content.
	Content string `json:"content"`
}

// Fetch file from the given hosts or die.
func MustFetchFile(ctx context.Context, httpClient *http.Client, file File) File {
	var output File

	host := file.Host
	if !strings.ContainsRune(host, '.') {
		host = host + shortGitilesHostSuffix
	}

	gc, err := gitiles.NewRESTClient(httpClient, host, true)
	if err != nil {
		log.Fatalf("error creating Gitiles client: %v", err)
	}

	req := &gitilespb.DownloadFileRequest{
		Project:    file.Project,
		Path:       file.Path,
		Committish: file.Ref,
		Format:     gitilespb.DownloadFileRequest_TEXT,
	}

	content, err := gc.DownloadFile(ctx, req)
	if err != nil {
		log.Fatalf("error downloading file: %v", err)
	}

	output.Content = content.Contents

	return output
}
