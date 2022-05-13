#!/usr/bin/env vpython3
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


def clean_file_paths(coverage_file, path_mapping_file, output_file,
                     to_absolute_path):
  """Cleans the file paths in a given coverage file and writes out the results.

    Args:
      coverage_file: the coverage file to process.
      path_mapping_file: the file of the path mappings configs.
      output_file: where to write the cleaned file.
      to_absolute_path: True clean file path as absolute path, otherwise
        as relative path(the part showing up on gerrit frontend, which is
        decided by repo settings).
  """
  with open(coverage_file, 'r') as coverage_file, open(path_mapping_file,
                                                       'r') as config_file:
    coverage_file_data = coverage_file.read()

    # Write the data as is if it can't be cleaned.
    if not code_coverage_util.is_valid_llvm_coverage_json_file(
        coverage_file_data):
      shutil.copyfile(coverage_file, output_file)
      return

    data = json.loads(coverage_file_data)
    path_mappings = json.load(config_file)
    results = code_coverage_util.clean_file_names_in_llvm_coverage_json(
        data, path_mappings, to_absolute_path)

    with open(output_file, 'w') as out_file:
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

  parser.add_argument('--to_absolute_path', required=True, type=bool,
                      help='clean file paths as absolute or relative path')

  return parser.parse_args(args=args)


def main():
  params = _parse_args(sys.argv[1:])

  if not os.path.exists(params.coverage_file):
    raise RuntimeError('Coverage file %s must exist' % params.coverage_file)

  if not os.path.exists(params.constants_file):
    raise RuntimeError('Path mappings config %s must exist' %
                       params.constants_file)

  if os.path.exists(params.output_file):
    raise RuntimeError('Output file %s already exists' % params.output_file)

  clean_file_paths(params.coverage_file, params.constants_file,
                   params.output_file, params.to_absolute_path)


if __name__ == '__main__':
  logging.basicConfig(format='[%(asctime)s %(levelname)s] %(message)s',
                      level=logging.INFO)
  sys.exit(main())
