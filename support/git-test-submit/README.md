# Git Test Submit

This is a support program that tests whether a provided list of Gerrit changes
can be cherry-picked on top of their underlying Gerrit projects/branches.

## Test runs

You can try this program locally using a sample-input file in this directory.

e.g.

```bash
cd path/to/recipes/support
go run git-test-submit/git_test_submit.go --input-json=git-test-submit/sample-input-kernel.json
```