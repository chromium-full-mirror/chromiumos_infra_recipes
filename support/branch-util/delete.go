package main

import (
	"fmt"

	"github.com/maruel/subcommands"
)

var cmdDeleteBranch = &subcommands.Command{
	UsageLine: "delete <options> branch_name",
	ShortDesc: "Delete a branch.",
	LongDesc:  "Delete a branch.",
	CommandRun: func() subcommands.CommandRun {
		c := &deleteBranchRun{}
		c.Init()
		return c
	},
}

type deleteBranchRun struct {
	CommonFlags
	// Name of the branch to delete.
	branch_name string
}

func (c *deleteBranchRun) validate(args []string) (bool, string) {
	if len(args) < 1 {
		return false, "Missing required argument(s)."
	} else {
		c.branch_name = args[0]
	}
	return true, ""
}

func (c *deleteBranchRun) Run(a subcommands.Application, args []string,
	env subcommands.Env) int {
	ok, err := c.validate(args)
	if !ok {
		fmt.Fprintf(a.GetErr(), "%s: %s\n", a.GetName(), err)
		return 1
	}

	return 0
}
