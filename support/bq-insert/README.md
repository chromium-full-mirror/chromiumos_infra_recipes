# BigQuery Insert

## Local testing

To test locally you'll need to authenticate with gerrit OAuth scopes:

```shell
luci-auth login -scopes 'https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gerritcodereview'
```

then use an input like the sample-input.json, sample-input2.json, or
goma-input.json in this directory.

```shell
go run bq-insert/main.go --input-json=/path/to/sample-input.json
```

Note that these input files are for reading data only:
  sample-input.json
  sample-input2.json
  goma-input.json
This allows developers to verify basic golang/BigQuery functionality,
BigQuery access permissions, etc.

NOTE: goma-input.json is currently failing due to permissions issues.
