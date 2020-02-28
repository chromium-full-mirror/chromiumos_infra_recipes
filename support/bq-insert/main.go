// Copyright 2020 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package main

import (
	"context"
	"fmt"
	"log"

	"cloud.google.com/go/bigquery"
	"go.chromium.org/luci/auth"
	"google.golang.org/api/iterator"

	"support/internal/cli"
)

type Input struct {
	ProjectId    string `json:"project_id"`
	TableName    string `json:"table_name"`
	TestOnly     bool   `json:"test_only"`
	CompileEvent string `json:"compile_event"`
}

type Output struct {
}

func main() {
	cli.SetAuthScopes(auth.OAuthScopeEmail)
	cli.Init()

	var input Input
	cli.MustUnmarshalInput(&input)

	ctx := context.Background()
	client, err := bigquery.NewClient(ctx, input.ProjectId)
	if err != nil {
		log.Fatal("Error creating client: ", err)
	}

	if input.TestOnly {
		tableData := queryTable(ctx, client, input.TableName)
		log.Print("Contents of ", input.TableName)
		for _, element := range tableData {
			log.Print("ELEMENT: " + element)
		}
	}
	// TODO(mmortensen): Handle table updates by defining a type that
	// implements the ValueSaver interface, which has a single method named
	// Save. Then create an Uploader, and call its Put method with a slice of
	// values.

}

// Query a table, reading all columns of a few rows. This allows developers to
// verify basic golang/BigQuery integration, including BigQuery access
// permissions, BigQuery project id, BigQuery table name path, and so on.
// These are all prerequisites to what is needed to update a table.
func queryTable(ctx context.Context, client *bigquery.Client, tableName string) []string {
	tableData := make([]string, 0)
	q := client.Query("select * from `" + tableName + "` LIMIT 5")
	it, err := q.Read(ctx)
	if err != nil {
		log.Fatal("Error performing q.Read: ", err)
	}
	for {
		var row []bigquery.Value
		err := it.Next(&row)
		if err == iterator.Done {
			break
		}
		if err != nil {
			log.Fatal("Error reading from "+tableName+":", err)
		}
		rowString := fmt.Sprintln(row)
		tableData = append(tableData, rowString)
	}
	return tableData
}
