# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Generate a secure and valid Google Cloud Build configuration from a user-provided COP build file."""

import argparse
import json
import sys
import yaml


def securize_user_config(user_config):
  """Validate that the user configuration is minimally safe to run."""

  #Check if user tries to access the token
  if '${_TOKEN}' in str(user_config):
    print('User yaml, must not use the token')
    sys.exit(-1)

  #Limit timeout
  user_config['timeout'] = '1200s'

  #Check docker container
  valid_containers = ('gcr.io/${PROJECT_ID}/', 'gcr.io/cloud-builders/git')
  for s in user_config['steps']:
    if not s['name'].startswith(valid_containers):
      print(f"Container names must start with {valid_containers}")
      sys.exit(-1)

  return user_config


def patch_yaml(base_yaml, user_yaml):
  """Merge a base build configuration with a user build configuration.

  Merge two configurations (base and user) following the following rues
  - 'steps' fields is the concatenation of base and user 'steps' fields,
    in that order.
  - 'availableSecrets' field comes directly from base configuration.
  - 'substititions' field is a merge of base and user configurations
  - For other fields present in user and base configurations, base takes
    preference.
  - Fields only present in user or base are copied as-is.

  Args:
    base_yaml:
      A parsed Google Cloud build configuration yaml file, as defined in
      https://cloud.google.com/build/docs/build-config-file-schema normally
      statically defined in the application code.
    user_yaml:
      A parsed Google Cloud build configuration yaml file, as defined in
      https://cloud.google.com/build/docs/build-config-file-schema normally
      provided by the user.

  Returns:
    A parse Google Cloud configuration yaml file, obtained by merging the
    base_yaml and user_yaml, following the aforementioned rules.
  """
  patched_yaml = dict()
  for key in base_yaml.keys():
    if key not in user_yaml.keys():
      patched_yaml[key] = base_yaml[key]
      continue
    if key == 'steps':
      patched_yaml['steps'] = base_yaml['steps'] + user_yaml['steps']
    if key == 'substitutions':
      patched_yaml['substitutions'] = {
          **base_yaml['substitutions'],
          **user_yaml['substitutions'],
      }
    if key == 'availableSecrets':
      patched_yaml['availableSecrets'] = base_yaml['availableSecrets']
  for key in user_yaml.keys():
    if key == 'availableSecrets':
      continue
    if key in base_yaml.keys():
      continue
    patched_yaml[key] = user_yaml[key]
  return patched_yaml


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('-input-json', type=argparse.FileType('r'), required=True)
  parser.add_argument('-output-json', type=argparse.FileType('w'),
                      required=True)
  args = parser.parse_args()

  input_json = json.load(args.input_json)
  file_base_config = open(input_json['base_yaml'])
  base_config = yaml.safe_load(file_base_config.read())
  user_config = yaml.safe_load(input_json['user_yaml'])
  substitutions = input_json['substitutions']

  user_config = securize_user_config(user_config)
  build_config = patch_yaml(base_config, user_config)
  for key in substitutions:
    build_config['substitutions'][key] = substitutions[key]

  json.dump(build_config, args.output_json)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
