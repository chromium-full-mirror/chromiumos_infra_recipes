#!/usr/bin/env vpython3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helper script to execute a Standard SQL query via google-cloud-bigquery."""

from __future__ import annotations

import argparse
import json
import subprocess

# pylint: disable=import-error
from google.cloud import bigquery
from google.oauth2 import credentials

BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"


def _get_credentials() -> credentials.Credentials:
  token = subprocess.check_output(
      ["luci-auth", "token", "-scopes", BIGQUERY_SCOPE, "-lifetime", "5m"],
      text=True,
  ).strip()
  return credentials.Credentials(token=token)


def main() -> None:
  parser = argparse.ArgumentParser(
      description="Run a Standard SQL query using google-cloud-bigquery.")
  parser.add_argument("--project", required=True, help="GCP project ID.")
  parser.add_argument("--sql", required=True, help="Standard SQL query string.")
  parser.add_argument(
      "--param",
      action="append",
      default=[],
      help="Named STRING query parameter in NAME=VALUE format.",
  )
  args = parser.parse_args()

  query_params = []
  for param in args.param:
    name, val = param.split("=", 1)
    query_params.append(bigquery.ScalarQueryParameter(name, "STRING", val))
  job_config = bigquery.QueryJobConfig(query_parameters=query_params)
  client = bigquery.Client(project=args.project, credentials=_get_credentials())
  rows = [
      dict(row.items())
      for row in client.query(args.sql, job_config=job_config).result(
          timeout=120)
  ]
  print(json.dumps(rows))


if __name__ == "__main__":
  main()
