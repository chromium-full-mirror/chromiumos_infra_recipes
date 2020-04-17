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
* goma-exp-read.json - Reads data from the goma experimental dataset,
  which has the same schema as the goma logs dataset but can be modified
  for tests (see below).
* goma-exp-write-small.json - Writes a small subset of data to the goma
  experimental dataset.
* goma-exp-write-small-verbose.json - Write a small subset of data to the
  goma experimental dataset with the verbose flag set.
* goma-exp-full-missing3fields.json - Write a large json goma dataset to goma
  experimental dataset, which has all fields except 3 that were added to the
  BQ schema in April 2020.
* goma-exp-full-allfields.json - This large json goma dataset has full raw output
  from goma including 3 proto fields that were added to the BQ schema in April 2020.
* goma-input.json - For listing data from the goma logs dataset.
* goma-write-data.json - For writing data to goma. Shows proper format of
  request including sample row data. Should fail since only the
  chromeos-ci-prod@chromeos-bot.iam.gserviceaccount.com should be able to
  write.
* sample-addrows.json - For adding data to the chromeos test dataset.
* sample-addrows-fail.json - Shows that data with unrecognized fields
  will not be added to an existing dataset.
* sample-addrows-newlines.json - Showing data with unrecognized fields
  but with nested json values and newlines to test/display debug print.
* sample-input.json - For listing data from public dataset
* sample-input-verbsoe.json - For listing data from public dataset with
  the verbose flag set, which will enumerate projects in the dataset.
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

## Writeable goma BigQuery table for tests

The Goma team created a dataset for which mmortensen@ and others can be granted
write access.  To create the table from a single entry of the goma data set (so
that it uses the goma table schema and contains a valid entry), use this command
in the BigQuery GCP editor:
```sql
  CREATE TABLE `goma-logs.experimental_client_events.compile_events`
  AS  SELECT * FROM `goma-logs.client_events.compile_events` LIMIT 1;
```
