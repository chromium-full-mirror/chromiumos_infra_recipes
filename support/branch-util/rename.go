package main

import (
	"fmt"

	"github.com/maruel/subcommands"
)

var cmdRenameBranch = &subcommands.Command{
	UsageLine: "rename <options> old new",
	ShortDesc: "Rename a branch.",
	LongDesc:  "Rename a branch.",
	CommandRun: func() subcommands.CommandRun {
		c := &renameBranchRun{}
		c.Init()
		return c
	},
}

type renameBranchRun struct {
	CommonFlags
	// Branch to rename.
	old string
	// New name for the branch.
	new string
}

func (c *renameBranchRun) validate(args []string) (bool, string) {
	if len(args) < 2 {
		return false, "Missing required argument(s)."
	} else {
		c.old = args[0]
		c.new = args[1]
	}
	return true, ""
}

func (c *renameBranchRun) Run(a subcommands.Application, args []string,
	env subcommands.Env) int {
	ok, err := c.validate(args)
	if !ok {
		fmt.Fprintf(a.GetErr(), "%s: %s\n", a.GetName(), err)
		return 1
	}

	return 0
}
