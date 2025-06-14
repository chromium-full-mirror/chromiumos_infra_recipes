# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Download the results from a Google Cloud Build."""

import argparse
import sys
import json

from google.cloud import storage
from google.cloud.devtools import cloudbuild_v1


def download_file(storage_client, gs_path):
  """Return a Google Cloud blob as a string, or None if the blob does not exist"""
  blob = storage.blob.Blob.from_string(gs_path, client=storage_client)
  if not blob.exists():
    return None
  return blob.download_as_text()


def get_result_logs(storage_client, build):
  """Return the log from a Google Cloud Build."""
  gs_path = f'{build.logs_bucket}/log-{build.id}.txt'
  log = download_file(storage_client, gs_path)
  if not log:
    return f'{gs_path} not found.'
  return log


def filter_result(step_id, result):
  """Filter the lines from a specific step from a combined result log"""
  prefix = f'Step #{step_id}'
  lines = filter(lambda x: x.startswith(prefix), result.splitlines())
  return '\n'.join(lines)


def get_step_logs(storage_client, build, step_id, result):
  """Return the log from a Google Cloud Build's step."""
  gs_path = f'{build.logs_bucket}/log-{build.id}-step-{step_id}.txt'
  log = download_file(storage_client, gs_path)
  if log:
    return log
  log = filter_result(step_id, result)
  if log == '':
    return f'Log for Step {step_id} not found.'
  return log


def get_build_info(project, build_id):
  """Return information about a Google Cloud Build."""
  client = cloudbuild_v1.services.cloud_build.CloudBuildClient()
  return client.get_build(project_id=project, id=build_id)


def should_log_step(step):
  """Given a step return whether this step should be logged"""
  if step.id.startswith('verbose_'):
    return True
  if step.status in (
      cloudbuild_v1.Build.Status.SUCCESS,
      # If a step fails then other parallel steps are terminated early.
      # They have status CANCELLED if the terminated step is already running,
      # and QUEUED if the terminated step hasn't started yet.
      cloudbuild_v1.Build.Status.QUEUED,
      cloudbuild_v1.Build.Status.CANCELLED,
  ):
    return False
  return True


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('-input-json', type=argparse.FileType('r'), required=True)
  parser.add_argument('-output-json', type=argparse.FileType('w'),
                      required=True)
  args = parser.parse_args()

  input_json = json.load(args.input_json)

  build = get_build_info(input_json['project'], input_json['build_id'])
  storage_client = storage.Client()

  result_logs = get_result_logs(storage_client, build).rstrip()

  result = {}
  result['result'] = {
      'status': build.Status(build.status).name,
      'log': result_logs,
      'log_url': build.log_url,
  }
  steps = []
  for i, step in enumerate(build.steps):
    if not should_log_step(step):
      continue
    status = build.Status(step.status).name
    log = get_step_logs(storage_client, build, i, result_logs).rstrip()
    steps.append({
        'id': i,
        'name': step.id,
        'status': status,
        'log': log,
    })
  result['steps'] = steps

  json.dump(result, args.output_json)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
