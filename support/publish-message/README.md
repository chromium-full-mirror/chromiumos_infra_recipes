# Publish Message

Client to publish a message to Cloud Pub/Sub

## Local testing

To test locally you'll need to authenticate with gerrit OAuth scopes:

```shell
luci-auth login -scopes 'https://www.googleapis.com/auth/pubsub'
```

then use an input like the sample-input.json in this directory.

```shell
go run publish-message/main.go --input-json=/path/to/sample-input.json
```