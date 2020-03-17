# BigQuery Insert

## Local testing

To test locally you'll need to authenticate with gerrit OAuth scopes:

```shell
luci-auth login -scopes 'https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/bigquery'
```

then use an input like the sample-input.json, sample-input2.json, or
goma-input.json in this directory.

```shell
go run bq-insert/main.go --input-json=/path/to/sample-input.json
```

The following input files are checked in:
* goma-input.json - For listing data from the goma logs dataset.
* goma-write-data.json - For writing data to goma. Shows proper format of
  request including sample row data. Should fail since only the
  chromeos-ci-prod@chromeos-bot.iam.gserviceaccount.com should be able to
  write.
* sample-addrows.json - For adding data to the chromeos test dataset.
* sample-addrows-fail.json - Shows that data with unrecognized fields
    will not be added to an existing dataset.
* sample-input.json - For listing data from public dataset
* sample-input2.json - For listing data from a chromeos test dataset.
* sample-write-data.json - Uses write-data (non-verbose) path, as a recipe
  would.
* sample-write-data-fail.json - Uses write-data (non-verbose) path, as a recipe
  would, but demonstrates failure output.

This allows developers to verify basic golang/BigQuery functionality,
BigQuery access permissions, etc.

NOTE: Using goma-input.json requires that the person executing the program
belong to a group such as chromeos-build-infra@google.com or
mdb/chromeos-ci-eng.
