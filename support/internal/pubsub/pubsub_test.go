// Copyright 2021 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
package pubsub

import (
	"context"
	"testing"

	"cloud.google.com/go/pubsub"
	"cloud.google.com/go/pubsub/pstest"
	"google.golang.org/api/option"
	"google.golang.org/grpc"
	"gotest.tools/assert"
)

const testProject string = "test-project"
const testTopic string = "test-topic"
const testData string = "A test message"

// Create a new fake Pub/Sub server with a topic. Return the server and client connection to the
// server.
func setupTestServer() (*pstest.Server, *grpc.ClientConn, error) {
	ctx := context.Background()

	srv := pstest.NewServer()

	conn, err := grpc.Dial(srv.Addr, grpc.WithInsecure())
	if err != nil {
		return nil, nil, err
	}

	client, err := pubsub.NewClient(ctx, testProject, option.WithGRPCConn(conn))
	if err != nil {
		return nil, nil, err
	}

	_, err = client.CreateTopic(ctx, testTopic)
	if err != nil {
		return nil, nil, err
	}

	return srv, conn, nil
}

func TestPublishMessage(t *testing.T) {
	// Test the basic functionality of publishing a message.
	srv, conn, err := setupTestServer()
	assert.NilError(t, err)

	id, err := PublishMessage(testProject, testTopic, "", "", []byte(testData), option.WithGRPCConn(conn))
	assert.NilError(t, err)

	assert.Equal(t, len(srv.Messages()), 1)

	message := srv.Messages()[0]
	assert.Equal(t, message.ID, id)
	assert.Equal(t, string(message.Data), testData)
}
