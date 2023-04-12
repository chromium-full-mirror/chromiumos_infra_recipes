# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wait until Google Cloud Build is completed and return is status."""

import argparse
import sys
import json
import time
import luci_auth

from google.cloud.devtools import cloudbuild_v1
import google.oauth2.credentials


def monitor_status(client, project, build_id):
  """Poll Google Cloud Build for an id until a Build is completed."""

  while True:
    build = client.get_build(project_id=project, id=build_id)
    status = build.Status(build.status).name

    if status not in ('WORKING', 'QUEUED'):
      return status
    time.sleep(10)


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('-input-json', type=argparse.FileType('r'), required=True)
  parser.add_argument('-output-json', type=argparse.FileType('w'),
                      required=True)
  args = parser.parse_args()

  input_json = json.load(args.input_json)

  credential = google.oauth2.credentials.Credentials(
      luci_auth.get_token(minutes=30))
  client = cloudbuild_v1.services.cloud_build.CloudBuildClient(
      credentials=credential)

  status = monitor_status(client, input_json['project'], input_json['build_id'])

  out = {'status': status}
  json.dump(out, args.output_json)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
