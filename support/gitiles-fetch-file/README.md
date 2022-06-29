# Gitiles Fetch file

## Local testing

To test locally you'll need to authenticate with gerrit OAuth scopes:

```shell
luci-auth login -scopes 'https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gerritcodereview'
```

then use an input like the sample-input.json in this directory.

```shell
go run gitiles-fetch-files/gitiles_fetch_files.go --input-json=/path/to/sample-input.json
```
