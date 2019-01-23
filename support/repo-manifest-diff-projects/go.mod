module chromium.googlesource.com/chromiumos/infra/recipes/support/repo-manifest-diff-projects

require (
	chromium.googlesource.com/chromiumos/infra/recipes/support/internal/cli v0.0.0
	chromium.googlesource.com/chromiumos/infra/recipes/support/internal/manifest v0.0.0
)

replace (
	chromium.googlesource.com/chromiumos/infra/recipes/support/internal/cli => ../internal/cli
	chromium.googlesource.com/chromiumos/infra/recipes/support/internal/manifest => ../internal/manifest
)
