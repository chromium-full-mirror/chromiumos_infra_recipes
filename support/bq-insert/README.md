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

The following input files are checked in:
* sample-input.json - For listing data from public dataset
* sample-input2.json - For listing data from a chromeos test dataset.
* goma-input.json - For listing data from the goma logs dataset.
* sample-addrows.json - For adding data to the chromeos test dataset.
* sample-addrows-fail.json - Shows that data with unrecognized fields
    will not be added to an existing dataset.

This allows developers to verify basic golang/BigQuery functionality,
BigQuery access permissions, etc.

NOTE: goma-input.json is currently failing due to permissions issues.
