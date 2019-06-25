package main

import (
	"fmt"

	"github.com/maruel/subcommands"
)

var cmdCreateBranch = &subcommands.Command{
	UsageLine: "create <options>",
	ShortDesc: "Create a branch.",
	LongDesc:  "Create a branch.",
	CommandRun: func() subcommands.CommandRun {
		c := &createBranchRun{}
		c.Init()
		c.Flags.BoolVar(&c.yes, "yes", false,
			"If set, disables the boolean prompt confirming the branch name.")
		// Arguments for determining branch name.
		c.Flags.StringVar(&c.descriptor, "descriptor", "",
			"Optional descriptor for this branch. Typically, this is a build "+
				"target or a device, depending on the nature of the branch. Used "+
				"to generate the branch name. Cannot be used with --custom.")
		// Which manifest should be branched?
		c.Flags.StringVar(&c.version, "version", "",
			"Manifest version to branch off, e.g. '10509.0.0'. You may not branch "+
				"off of the same version twice unless you run "+
				"with --force.")
		// What kind of branch is this?
		// TODO(@jackneus): Figure out how to group these flags in the
		// help dialog. Right now all flags are displayed in alphabetic
		// order, which is less helpful.
		c.Flags.BoolVar(&c.release, "release", false,
			"The new branch is a release branch. "+
				"Named as 'release-<descriptor>-R<Milestone>-<Major Version>.B'.")
		c.Flags.BoolVar(&c.factory, "factory", false,
			"The new branch is a factory branch. "+
				"Named as 'factory-<Descriptor>-<Major Version>.B'.")
		c.Flags.BoolVar(&c.firmware, "firmware", false,
			"The new branch is a firmware branch. "+
				"Named as 'firmware-<Descriptor>-<Major Version>.B'.")
		c.Flags.BoolVar(&c.stabilize, "stabilize", false,
			"The new branch is a minibranch. "+
				"Named as 'stabilize-<Descriptor>-<Major Version>.B'.")
		c.Flags.StringVar(&c.custom, "custom", "",
			"Use a custom branch type with an explicit name. "+
				"WARNING: custom names are dangerous. This tool greps branch "+
				"names to determine which versions have already been branched. "+
				"Version validation is not possible when the naming convention "+
				"is broken. Use this at your own risk.")
		return c
	},
}

type createBranchRun struct {
	CommonFlags
	yes        bool
	descriptor string
	version    string
	file       string
	release    bool
	factory    bool
	firmware   bool
	stabilize  bool
	custom     string
}

func (c *createBranchRun) getBranchType() (string, bool) {
	var branch_type string
	branch_types_selected := 0
	if c.release {
		branch_types_selected++
		branch_type = "release"
	}
	if c.factory {
		branch_types_selected++
		branch_type = "factory"
	}
	if c.firmware {
		branch_types_selected++
		branch_type = "firmware"
	}
	if c.stabilize {
		branch_types_selected++
		branch_type = "stabilize"
	}
	if c.custom != "" {
		branch_types_selected++
		branch_type = "custom"
	}
	if branch_types_selected != 1 {
		return "", false
	}

	return branch_type, true
}

func (c *createBranchRun) validate() (bool, string) {
	if c.version == "" && c.file == "" {
		return false, "Must set --version or --file."
	}
	_, ok := c.getBranchType()
	if !ok {
		return false, "Must select exactly one branch type " +
			"(--release, --factory, --firmware, --stabilize, --custom)."
	}
	return true, ""
}

func (c *createBranchRun) Run(a subcommands.Application, args []string,
	env subcommands.Env) int {
	ok, err := c.validate()
	if !ok {
		fmt.Fprintf(a.GetErr(), "%s: %s\n", a.GetName(), err)
		return 1
	}

	return 0
}
