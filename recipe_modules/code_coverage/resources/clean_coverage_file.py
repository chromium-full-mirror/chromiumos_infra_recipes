#!/usr/bin/env vpython
# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import json
import logging
import os
import sys
import shutil
import code_coverage_util


def clean_file_paths(path_to_coverage_file, path_to_constants_file,
                     path_to_output_file, build_target_name):
  """Cleans the file paths in a given coverage file and writes out the results.

    Args:
      path_to_coverage_file: the coverage file to process.
      path_to_constants_file: the constants file containing the mappings.
      path_to_output_file: where to write the cleaned file.
      build_target_name: name of the build target.
  """
  with open(path_to_coverage_file,
            'r') as coverage_file, open(path_to_constants_file,
                                        'r') as constants_file:
    coverage_file_data = coverage_file.read()

    # Write the data as is if it can't be cleaned.
    if not code_coverage_util.is_valid_llvm_coverage_json_file(
        coverage_file_data):
      shutil.copyfile(path_to_coverage_file, path_to_output_file)
      return

    data = json.loads(coverage_file_data)
    constants = json.load(constants_file)
    results = code_coverage_util.clean_file_names_in_llvm_coverage_json(
        data, constants, build_target_name)

    with open(path_to_output_file, 'w') as out_file:
      json.dump(results, out_file)


def _parse_args(args):
  parser = argparse.ArgumentParser(
      description='Clean file names in a coverage file if possible and write '
      'the cleaned file to the provided output location.')

  parser.add_argument('--coverage-file', required=True, type=str,
                      help='absolute path to the coverage file')

  parser.add_argument(
      '--constants-file', required=True, type=str,
      help='absolute path to the file containing constants for package mapping.'
  )

  parser.add_argument(
      '--output-file', required=True, type=str,
      help='absolute path to where the cleaned file should be placed.')

  parser.add_argument('--build-target', required=True, type=str,
                      help='the target code coverage was built for')

  return parser.parse_args(args=args)


def main():
  params = _parse_args(sys.argv[1:])

  if not os.path.exists(params.coverage_file):
    raise RuntimeError('Coverage file %s must exist' % params.coverage_file)

  if not os.path.exists(params.constants_file):
    raise RuntimeError('Constants file %s must exist' % params.constants_file)

  if os.path.exists(params.output_file):
    raise RuntimeError('Output file %s already exists' % params.output_file)

  clean_file_paths(params.coverage_file, params.constants_file,
                   params.output_file, params.build_target)


if __name__ == '__main__':
  logging.basicConfig(format='[%(asctime)s %(levelname)s] %(message)s',
                      level=logging.INFO)
  sys.exit(main())
