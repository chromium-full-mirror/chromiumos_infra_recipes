package main

import (
	"log"

	"chromium.googlesource.com/chromiumos/infra/recipes/support/cli"
	"chromium.googlesource.com/chromiumos/infra/recipes/support/vcs/lib"
)

type Input struct {
	FromPath string `json:"from_path"`
	ToPath   string `json:"to_path"`
}

type Output struct {
	lib.ManifestDiff
}

func main() {
	cli.Init()

	var input Input
	cli.MustUnmarshalInput(&input)

	// Load from and to manifests
	var fromManifest, toManifest lib.Manifest

	if err := fromManifest.LoadFromXmlFile(input.FromPath); err != nil {
		log.Fatal(err)
	}

	if err := toManifest.LoadFromXmlFile(input.ToPath); err != nil {
		log.Fatal(err)
	}

	cli.MustMarshalOutput(fromManifest.Diff(toManifest))
}
