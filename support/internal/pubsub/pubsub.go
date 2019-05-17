package pubsub

import (
	"context"

	"cloud.google.com/go/pubsub"
	"google.golang.org/api/option"
)

// PublishMessage `data` to projects/`projectID`/topics/`topic-id`. Passes `opts` to the pubsub
// client (e.g. WithTokenSource)
func PublishMessage(projectID string, topicID string, data string, opts ...option.ClientOption) (string, error) {
	ctx := context.Background()
	client, err := pubsub.NewClient(ctx, projectID, opts...)
	if err != nil {
		return "", err
	}

	topic := client.Topic(topicID)
	if err != nil {
		return "", err
	}

	result := topic.Publish(ctx, &pubsub.Message{Data: []byte(data)})

	return result.Get(ctx)
}
