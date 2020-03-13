# Git Test Submit

This is a support program that tests whether a provided list of Gerrit changes
can be cherry-picked on top of their underlying Gerrit projects/branches.

## Test runs

You can try this program locally using a sample-input file in this directory.

You'll need to be logged in first.

```bash
luci-auth login -scopes 'https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gerritcodereview'
```

e.g.

```bash
cd path/to/recipes/support
go run git-test-submit/git_test_submit.go --input-json=git-test-submit/sample-input.json
```
