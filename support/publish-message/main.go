package main

import (
	"log"
	"support/internal/cli"
	"support/internal/pubsub"

	luciPubsub "github.com/luci/luci-go/common/gcloud/pubsub"
	"google.golang.org/api/option"
)

// Publish a message containing `data` to projects/`projectId`/topics/`topic-id`
type input struct {
	ProjectID string `json:"project_id"`
	TopicID   string `json:"topic_id"`
	Data      string `json:"data"`
}

type output struct {
	MessageID string `json:"message_id"`
}

func main() {
	cli.SetAuthScopes(luciPubsub.SubscriberScopes...)
	cli.Init()

	var input input
	cli.MustUnmarshalInput(&input)
	if len(input.Data) == 0 {
		log.Fatalf("data must not be empty")
	}

	tokenSource, err := cli.AuthenticatedTokenSource()

	if err != nil {
		log.Fatalf("Failed to create TokenSource: %v", err)
	}

	id, err := pubsub.PublishMessage(input.ProjectID, input.TopicID, input.Data, option.WithTokenSource(tokenSource))

	if err != nil {
		log.Fatalf("Failed to publish message: %v", err)
	}

	cli.MustMarshalOutput(output{MessageID: id})
}
