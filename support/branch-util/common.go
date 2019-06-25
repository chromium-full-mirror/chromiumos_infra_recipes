package main

import (
	"github.com/maruel/subcommands"
)

// Common flags
type CommonFlags struct {
	subcommands.CommandRunBase
	Push        bool
	Force       bool
	Root        string
	ManifestUrl string
}

func (c *CommonFlags) Init() {
	// Common flags
	c.Flags.BoolVar(&c.Push, "push", false,
		"Push branch modifications to remote repos. Before setting this flag, "+
			"ensure that you have the proper permissions and that you know what "+
			"you are doing. Ye be warned.")
	c.Flags.BoolVar(&c.Force, "force", false,
		"Required for any remote operation that would delete an existing "+
			"branch. Also required when trying to branch from a previously "+
			"branched manifest version.")
	// Sync options
	c.Flags.StringVar(&c.Root, "root", "",
		"Repo root of local checkout to branch. If the root does not "+
			"exist, this tool will create it. If the root is not initialized, "+
			"this tool will initialize it. If --root is not specificed, this "+
			"tool will branch a fresh checkout in a temporary directory.")
	c.Flags.StringVar(&c.ManifestUrl, "manifest_url",
		"https://chrome-internal.googlesource.com/chromeos/manifest-internal.git",
		"URL of the manifest to be checked out. Defaults to googlesource URL "+
			"for manifest-internal.")
}

func (c *CommonFlags) Parse() {

}
