# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Start a Google Cloud Build."""

import argparse
import sys
import json

from google.cloud.devtools import cloudbuild_v1
from google.protobuf import json_format
import google.oauth2.credentials


def run_build(token, project, build_config):
  """Authenticate into Google Cloud Build and start a build."""
  cred = google.oauth2.credentials.Credentials(token)
  client = cloudbuild_v1.services.cloud_build.CloudBuildClient(credentials=cred)
  build_class = cloudbuild_v1.types.cloudbuild.Build.pb(
      cloudbuild_v1.types.cloudbuild.Build())
  build = json_format.Parse(json.dumps(build_config), build_class)
  return client.create_build(project_id=project, build=build)


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('-input-json', type=argparse.FileType('r'), required=True)
  parser.add_argument('-output-json', type=argparse.FileType('w'),
                      required=True)
  args = parser.parse_args()

  input_json = json.load(args.input_json)

  build = run_build(input_json['token'], input_json['project'],
                    input_json['build_config'])

  out = {'id': build.metadata.build.id}
  json.dump(out, args.output_json)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
