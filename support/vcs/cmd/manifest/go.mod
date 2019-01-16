module chromium.googlesource.com/chromiumos/infra/recipes/support/vcs/cmd/manifest

require (
	chromium.googlesource.com/chromiumos/infra/recipes/support/cli v0.0.0
	chromium.googlesource.com/chromiumos/infra/recipes/support/vcs/lib v0.0.0
)

replace (
	chromium.googlesource.com/chromiumos/infra/recipes/support/cli => ../../../cli
	chromium.googlesource.com/chromiumos/infra/recipes/support/vcs/lib => ../../lib
)
