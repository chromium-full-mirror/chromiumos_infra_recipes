// Copyright 2021 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package pubsub

import (
	"context"
	"fmt"

	"cloud.google.com/go/pubsub"
	"google.golang.org/api/option"
)

// PublishMessage `data` to projects/`projectID`/topics/`topic-id`. Passes `opts` to the pubsub
// client (e.g. WithTokenSource)
func PublishMessage(
	projectID string,
	topicID string,
	orderingKey string,
	endpoint string,
	data []byte, opts ...option.ClientOption,
) (string, error) {
	ctx := context.Background()

	if orderingKey != "" && endpoint == "" {
		return "", fmt.Errorf("endpoint must be specified with ordering_key")
	}

	if endpoint != "" {
		opts = append(opts, option.WithEndpoint(endpoint))
	}

	client, err := pubsub.NewClient(ctx, projectID, opts...)
	if err != nil {
		return "", err
	}

	topic := client.Topic(topicID)
	if err != nil {
		return "", err
	}

	topic.EnableMessageOrdering = orderingKey != ""
	result := topic.Publish(ctx, &pubsub.Message{
		Data:        data,
		OrderingKey: orderingKey,
	})

	return result.Get(ctx)
}
