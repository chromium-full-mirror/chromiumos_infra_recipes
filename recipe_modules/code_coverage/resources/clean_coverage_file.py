#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import json
import logging
import os
import sys
import shutil

import code_coverage_util


def clean_file_paths(coverage_filepath, path_mapping_filepath, output_filepath,
                     to_absolute_path):
  """Cleans the file paths in a given coverage file and writes out the results.

    Args:
      coverage_filepath: Path to the coverage file to process.
      path_mapping_filepath: Path to the file of the path mappings configs.
      output_filepath: Where to write the cleaned file.
      to_absolute_path: If True, clean file path as absolute path. Otherwise,
        as relative path (the part showing up on gerrit frontend, which is
        decided by repo settings).
  """
  with open(coverage_filepath, 'r', encoding='utf-8') as coverage_file:
    coverage_file_data = coverage_file.read()
  if not code_coverage_util.is_valid_lcov_coverage_file(coverage_file_data):
    logging.info('Copying unknown file %s', coverage_filepath)
    # Write the data as is if it can't be cleaned.
    shutil.copyfile(coverage_filepath, output_filepath)
    return
  logging.info('Cleaning lcov file %s to_absolute_path=%s', coverage_filepath,
               to_absolute_path)
  with open(path_mapping_filepath, 'r', encoding='utf-8') as config_file:
    path_mappings = json.load(config_file)
  results = code_coverage_util.clean_file_names_in_lcov_coverage(
      coverage_file_data, path_mappings, to_absolute_path=to_absolute_path)
  with open(output_filepath, 'w', encoding='utf-8') as output_file:
    output_file.write(results)


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

  parser.add_argument('--to_absolute_path', required=True,
                      type=lambda x: x.lower() == 'true',
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
                      level=logging.DEBUG)
  sys.exit(main())
