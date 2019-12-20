package git

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"go.chromium.org/luci/common/api/gerrit"
	"io/ioutil"
	"log"
	"os/exec"
	"strings"
	"time"
)

var (
	runnerImpl runner = realRunner{}
)

type runner interface {
	run(ctx context.Context, dir string, stdoutBuf, stderrBuf *bytes.Buffer, name string, args ...string) error
}

type realRunner struct{}

func (c realRunner) run(ctx context.Context, dir string, stdoutBuf, stderrBuf *bytes.Buffer, name string, args ...string) error {
	stdoutBuf.Reset()
	stderrBuf.Reset()
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Stdout = stdoutBuf
	cmd.Stderr = stderrBuf
	cmd.Dir = dir
	log.Printf("running %s %s", name, strings.Trim(fmt.Sprint(args), "[]"))
	err := cmd.Run()
	log.Printf("stdout\n%s", stdoutBuf.String())
	log.Printf("stderr\n%s", stderrBuf.String())
	return err
}

// Clone does a `git clone` on the provided repo URL into a subdirectory of the supplied dir, and
// returns the path to the folder of the checkout.
func Clone(ctx context.Context, url string, branch string, parentDir string) (string, error) {
	dir, err := ioutil.TempDir(parentDir, "gitclone")
	if err != nil {
		return dir, err
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()
	var stdoutBuf, stderrBuf bytes.Buffer
	cloneCmd := []string{"clone", "--depth=1", url, "-b", branch, "."}
	if err := runnerImpl.run(ctx, dir, &stdoutBuf, &stderrBuf, "git", cloneCmd...); err != nil {
		return dir, errors.New(stderrBuf.String())
	}
	return dir, nil
}

// FetchAndCherryPick attempts to cherry-pick a provided Gerrit revision into
// the provided local Git repo. It returns an error if this fails (e.g. if the
// cherry-pick won't merge successfully) or nil if the cherry-pick works
// alright.
//
// Invocations of this method alter the supplied Git repo, so the order of
// invocations is important.
func FetchAndCherryPick(ctx context.Context, revision *gerrit.RevisionInfo, url string, repoDir string) error {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()
	var stdoutBuf, stderrBuf bytes.Buffer
	if err := runnerImpl.run(
		ctx, repoDir, &stdoutBuf, &stderrBuf, "git", "fetch", "--depth=2", url, revision.Ref); err != nil {
		return errors.New(stderrBuf.String())
	}
	if err := runnerImpl.run(
		ctx, repoDir, &stdoutBuf, &stderrBuf, "git", "show", "-s", "--pretty=%p", "FETCH_HEAD"); err != nil {
		return errors.New(stderrBuf.String())
	}
	parentCommits := strings.Split(strings.Trim(stdoutBuf.String(), "\n"), " ")
	if len(parentCommits) > 1 {
		log.Printf("Found multiple parent commits, indicating a merge commit. "+
			"We are currently unable to validate this sort of situation. Aborting... %v", parentCommits)
		return nil
	}

	log.Printf("creating patch of %s in %s", revision.Ref, repoDir)
	// Use a big --unified value to make incorrect cherry-picks less likely.
	// This effectively means the patch will contain the entirety of each
	// changed file.
	formatPatchCmd := []string{"format-patch", "--unified=100000000", "FETCH_HEAD^1..FETCH_HEAD"}
	if err := runnerImpl.run(ctx, repoDir, &stdoutBuf, &stderrBuf, "git", formatPatchCmd...); err != nil {
		return errors.New(stderrBuf.String())
	}
	patchFile := strings.Trim(stdoutBuf.String(), "\n")
	log.Printf("patching branch")
	if err := runnerImpl.run(ctx, repoDir, &stdoutBuf, &stderrBuf, "git", "am", "--3way", "--ignore-whitespace", patchFile); err != nil {
		errStr := stderrBuf.String()
		if strings.Contains(errStr, "information is lacking or useless") {
			log.Printf("This looks like a case of https://crbug.com/1031306, in which something in the diff represents a non-existent file. Aborting...")
			return nil
		}
		// clean up the am state to reset the repo for the next patch.
		runnerImpl.run(ctx, repoDir, &stdoutBuf, &stderrBuf, "git", "am", "--abort")
		return errors.New(errStr)
	}
	return nil
}
