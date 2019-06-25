package main

import (
	"context"
	"io/ioutil"
	"log"
	"os"

	"github.com/maruel/subcommands"
)

var (
	Context = context.Background()

	push         bool
	force        bool
	root         string
	repo_url     string
	repo_branch  string
	manifest_url string
)

var application = &subcommands.DefaultApplication{
	Name:  "cros branch",
	Title: "cros branch tool",
	Commands: []*subcommands.Command{
		subcommands.CmdHelp,
		cmdCreateBranch,
		cmdRenameBranch,
		cmdDeleteBranch,
	},
}

type branchApplication struct {
	*subcommands.DefaultApplication
	log *log.Logger
}

func main() {
	subcommands.KillStdLog()
	s := &branchApplication{application, log.New(ioutil.Discard, "", log.LstdFlags|log.Lmicroseconds)}
	os.Exit(subcommands.Run(s, nil))
}
