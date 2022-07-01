# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Download the results from a Google Cloud Build."""

import argparse
import sys
import json

from google.cloud import storage
from google.cloud.devtools import cloudbuild_v1
import google.oauth2.credentials


def get_logs(storage_client, gs_path):
  """Return a Google Cloud Build log from Cloud Storage as a string."""
  blob = storage.blob.Blob.from_string(gs_path, client=storage_client)
  if not blob.exists():
    return f'{gs_path} not found.'
  return blob.download_as_text()


def get_result_logs(storage_client, build):
  """Return the log from a Google Cloud Build."""
  gs_path = f'{build.logs_bucket}/log-{build.id}.txt'
  return get_logs(storage_client, gs_path)


def get_step_logs(storage_client, build, step_id):
  """Return the log from a Google Cloud Build's step."""
  gs_path = f'{build.logs_bucket}/log-{build.id}-step-{step_id}.txt'
  return get_logs(storage_client, gs_path)


def get_build_info(credentials, project, build_id):
  """Return information about a Google Cloud Build."""
  client = cloudbuild_v1.services.cloud_build.CloudBuildClient(
      credentials=credentials)
  return client.get_build(project_id=project, id=build_id)


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('-input-json', type=argparse.FileType('r'), required=True)
  parser.add_argument('-output-json', type=argparse.FileType('w'),
                      required=True)
  args = parser.parse_args()

  input_json = json.load(args.input_json)

  credentials = google.oauth2.credentials.Credentials(input_json['token'])
  build = get_build_info(credentials, input_json['project'],
                         input_json['build_id'])
  storage_client = storage.Client(credentials=credentials)

  result = dict()
  result['result'] = {
      'status':
          build.Status(build.status).name,
      'log':
          f'CoP Log URL: {build.log_url}\n {get_result_logs(storage_client, build)}',
  }
  steps = list()
  for i, step in enumerate(build.steps):
    status = build.Status(step.status).name
    if status == 'SUCCESS':
      continue
    steps.append({
        'id': step.id,
        'status': status,
        'log': get_step_logs(storage_client, build, i)
    })
  result['steps'] = steps

  json.dump(result, args.output_json)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
