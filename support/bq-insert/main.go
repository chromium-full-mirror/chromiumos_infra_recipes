// Copyright 2020 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"

	"cloud.google.com/go/bigquery"
	"go.chromium.org/luci/auth"
	"google.golang.org/api/iterator"
	"google.golang.org/api/option"

	"support/internal/cli"
)

type Input struct {
	ProjectId    string          `json:"project_id"`
	DatasetId    string          `json:"dataset_id"`
	TableName    string          `json:"table_name"`
	ReadTest     bool            `json:"read_test"`
	WriteTest    bool            `json:"write_test"`
	WriteData    bool            `json:"write_data"`
	CompileEvent json.RawMessage `json:"compile_event"`
}

type Output struct {
	BqError string `json:"bq_error"`
}

func main() {
	cli.SetAuthScopes(auth.OAuthScopeEmail, bigquery.Scope)
	cli.Init()

	httpClient, err := cli.AuthenticatedHTTPClient()
	if err != nil {
		log.Fatal(err)
	}

	var input Input
	cli.MustUnmarshalInput(&input)

	ctx := context.Background()
	client, err := bigquery.NewClient(ctx, input.ProjectId, option.WithHTTPClient(httpClient))
	if err != nil {
		log.Fatal("Error creating client: ", err)
	}

	debugInfo := debugJsonRawMessage(input.CompileEvent)
	log.Print(debugInfo)

	if input.ReadTest {
		var fullTableName string
		if strings.Contains(input.TableName, ".") {
			// Then we have a fully qualified table name already.
			fullTableName = input.TableName
		} else {
			// Build up qualified table name.
			fullTableName = strings.Join([]string{
				input.ProjectId, input.DatasetId, input.TableName}, ".")
		}
		log.Print(" fullTableName ", fullTableName)
		tableData := queryTable(ctx, client, fullTableName)
		log.Print("Contents of ", input.TableName)
		for _, element := range tableData {
			log.Print("ELEMENT: " + element)
		}

		enumerateClientContents(ctx, client, input.DatasetId)
		cli.MustMarshalOutput(Output{BqError: ""})
		return
	} else if input.WriteData {
		error_string := insertTableData(ctx, client, input.DatasetId, input.TableName, input.CompileEvent, false)
		cli.MustMarshalOutput(Output{BqError: error_string})
		return
	} else if input.WriteTest {
		log.Printf("Raw message to write: %v", string(input.CompileEvent))
		// Get and log the table schema so that it can be visually compared to the
		// message contents.
		metadata := getTableMetadata(ctx, client, input.DatasetId, input.TableName)
		if metadata != nil {
			logTableSchema(metadata)
		}
		error_string := insertTableData(ctx, client, input.DatasetId, input.TableName, input.CompileEvent, true)
		cli.MustMarshalOutput(Output{BqError: error_string})
		return
	}
	cli.MustMarshalOutput(Output{BqError: ""})
}

// Each item to insert as a row is a json.RawMessage. The insertTableData
// function will put Item values into an array of ValueSaver interface type,
// triggering the Save function to be called for each Item.
type Item struct {
	message json.RawMessage
}

// Because 'Item' elements are put into an array of bigquery.Value saver
// inside insertTableTable, the Save() function will be called for each
// element from within the inserter's Put method. The Save function returns
// a key/value map where the key is the column name and the value is a
// bigquery.Value type.
func (i Item) Save() (map[string]bigquery.Value, string, error) {
	mymap := make(map[string]bigquery.Value)
	var values map[string]interface{}
	json.Unmarshal(i.message, &values)
	for key, value := range values {
		mymap[key] = value
	}
	return mymap, "", nil
}

// Insert the raw Json Message into the table specified by client/datasetId/tableName.
// If the table cannot be found then log a fatal error.
// If the insertion fails then log a fatal error.
func insertTableData(ctx context.Context, client *bigquery.Client, datasetId string, tableName string, message json.RawMessage, logDebugInfo bool) string {
	dataset := client.Dataset(datasetId)
	if dataset == nil {
		log.Fatal("Error getting dataset ", datasetId)
	}
	table := dataset.Table(tableName)
	if table == nil {
		log.Fatal("Error getting table")
	}
	var values map[string]interface{}
	json.Unmarshal(message, &values)
	if logDebugInfo {
		for key, value := range values {
			log.Println("JSON Key: ", key, " Value: ", value)
		}
	}
	var saverArray = make([]bigquery.ValueSaver, 0)
	saverArray = append(saverArray, Item{message})

	inserter := table.Inserter()
	insertion_error := inserter.Put(ctx, saverArray)
	if insertion_error != nil {
		log.Println("Error inserting values into table ", tableName, " : ", insertion_error)
		// This cast is based on the docs which indicate the the error interface
		// returned by the Inserter function is a PutMultiError:
		// https://godoc.org/cloud.google.com/go/bigquery#example-Inserter-Put
		multiError := insertion_error.(bigquery.PutMultiError)
		rowInsertionError := multiError[0]
		log.Println("InsertID ", rowInsertionError.InsertID, " RowIndex ", rowInsertionError.RowIndex)
		for index, err := range rowInsertionError.Errors {
			log.Printf("error %d = %v", index, err)
		}
		return insertion_error.Error()
	}
	return ""
}

// Given a BigQuery client (i.e. a Pantheon project like "chromeos-bot"), enumerate the datasets
// and for a given dataset enumerate the tables.
func enumerateClientContents(ctx context.Context, client *bigquery.Client, datasetId string) {
	dataset_iter := client.Datasets(ctx)
	for {
		dataset, dataset_error := dataset_iter.Next()
		if dataset_error == iterator.Done {
			break
		}
		if dataset_error != nil {
			log.Println("Error getting dataset", dataset_error)
		} else {
			log.Println("Client contains dataset ProjectID:", dataset.ProjectID, " DatasetID:", dataset.DatasetID)
		}
	}

	if datasetId == "" {
		log.Println("Empty (non-specified datasetId)")
		return
	}
	dataset := client.Dataset(datasetId)
	if dataset == nil {
		log.Fatal("Error getting dataset")
	}
	log.Println("Enumerating tables of dataset ProjectId: ", dataset.ProjectID, " DatasetId: ", dataset.DatasetID)
	it := dataset.Tables(ctx)
	for {
		table, err := it.Next()
		if err == iterator.Done {
			break
		}
		if err != nil {
			log.Println("Error getting table ", err)
			break
		} else {
			log.Println("TABLE ProjectID ", table.ProjectID, " DatasetID ", table.DatasetID,
				" TableID ", table.TableID)
		}
	}
}

// Retrieve a dataset's table metadata, logging a fatal error if it cannot be obtained.
func getTableMetadata(ctx context.Context, client *bigquery.Client, datasetId string, tableName string) *bigquery.TableMetadata {
	dataset := client.Dataset(datasetId)
	if dataset == nil {
		log.Fatal("Error getting dataset")
	}
	table := dataset.Table(tableName)
	if table == nil {
		log.Fatal("Error getting table")
	}
	metadata, err := table.Metadata(ctx)
	if err != nil {
		log.Fatal("Error getting table metadata: ", err)
	}
	return metadata
}

// Given the table metadata, log the schema name/type.
func logTableSchema(metadata *bigquery.TableMetadata) {
	for _, fs := range metadata.Schema {
		log.Println(" SCHEMA name/type --- ", fs.Name, fs.Type)
	}
}

// Given a json RawMessage, return debug string information such as the raw
// message and key/value pairs.
func debugJsonRawMessage(message json.RawMessage) string {
	var debugString string = ""
	debugString = fmt.Sprintf("Raw message: %v", string(message))
	debugString += "Unmarshalled json: " + debugPrintJsonRawMessage(1, message)
	return debugString
}

// Given a jsonRawMessage, print the string keys and the generic json values.
// For the values, if they can be unmarshalled, then recursively expand those
// json values as well.
func debugPrintJsonRawMessage(level int, message json.RawMessage) string {
	messageString := strings.Repeat(" ", level)
	genericJsonData := &map[string]json.RawMessage{}
	err := json.Unmarshal(message, genericJsonData)
	if err == nil {
		for key, value := range *genericJsonData {
			messageString += fmt.Sprintf(" JSON_KEY{%d} [%s] JSON_VALUE[%s]", level, key, value)
			genericJsonSubMsg := &map[string]json.RawMessage{}
			subErr := json.Unmarshal(value, genericJsonSubMsg)
			if subErr == nil {
				for subkey, subvalue := range *genericJsonSubMsg {
					messageString += " SUBKEY[" + subkey + "] " + debugPrintJsonRawMessage(level+1, subvalue)
				}
			}
		}
	}
	messageString += "\n"
	return messageString
}

// Query a table, reading all columns of a few rows. This allows developers to
// verify basic golang/BigQuery integration, including BigQuery access
// permissions, BigQuery project id, BigQuery table name path, and so on.
// These are all prerequisites to what is needed to update a table.
func queryTable(ctx context.Context, client *bigquery.Client, tableName string) []string {
	tableData := make([]string, 0)
	q := client.Query("select * from `" + tableName + "` LIMIT 20")
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
