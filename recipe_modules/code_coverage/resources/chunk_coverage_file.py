#!/usr/bin/env vpython3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to chunk big coverage files into smaller files."""
import argparse
import json
import logging
import os
import shutil
import sys

import code_coverage_util


def chunk(coverage_file, file_entries_per_chunk, chunk_dest_dir, coverage_type):
  """ Splits large |coverage_file| and smaller files.

  Method to split coverage |coverage_file| into smaller files,
  each containing |file_entries_per_chunk| coverage records.

  Args:
      coverage_file (str): Path of the llvm coverage file to be chunked.
      file_entries_per_chunk (int): Number of file records in each chunk.
      chunk_dest_dir (str): Destination directory for the split files.
      coverage_type (str): Type of the coverage.
  """

  # For non LLVM files, no need to chunk.
  if coverage_type != 'LLVM':
    shutil.copyfile(
        coverage_file,
        os.path.join(chunk_dest_dir, os.path.basename(coverage_file)))
    return

  with open(coverage_file, encoding='utf-8') as f:

    coverage_json = json.load(f)

    if (not coverage_json.get('data') or
        not coverage_json['data'][0].get('files')):
      return

    data = coverage_json['data'][0]['files']

    start = 0
    total_size = len(data)
    chunks = []
    while start < total_size:
      end = start + file_entries_per_chunk
      chunks.append(data[start:end])
      start = end

    count = 1

    for entry in chunks:
      coverage_json_temp = code_coverage_util.create_llvm_coverage_json(entry)
      chunk_file_path = os.path.join(chunk_dest_dir, str(count))
      with open(chunk_file_path, 'w', encoding='utf-8') as outfile:
        outfile.write(json.dumps(coverage_json_temp))

      count = count + 1

  logging.info('Split coverage file on path %s, into %d chunks.', coverage_file,
               count)
  return


def _parse_args(args):
  parser = argparse.ArgumentParser(
      description='Chunk a big llvm coverage json file into smaller '
      'chunks each having limited number of records.')

  parser.add_argument('--coverage-file', required=True, type=str,
                      help='absolute path to the coverage file')

  parser.add_argument('--file-entries-per-chunk', required=True, type=int,
                      help='number of coverage entries in each chunk.')

  parser.add_argument('--coverage-type', required=True, type=str,
                      help='type of coverage.')

  parser.add_argument(
      '--chunk-dest-dir', required=True, type=str,
      help='absolute dir path to where the chunked files need to be written.')

  return parser.parse_args(args=args)


def main():
  params = _parse_args(sys.argv[1:])

  if not os.path.exists(params.coverage_file):
    raise RuntimeError('Coverage file %s must exist' % params.coverage_file)

  if os.path.isdir(params.coverage_file):
    raise ValueError('The coverage_file cannot be a directory: %s' %
                     params.coverage_file)

  if not os.path.exists(params.chunk_dest_dir):
    raise RuntimeError('Chunk destination dir %s must exists' %
                       params.chunk_dest_dir)

  if params.file_entries_per_chunk < 1:
    raise RuntimeError('File entries per chunk needs to be greater than 0')

  chunk(params.coverage_file, params.file_entries_per_chunk,
        params.chunk_dest_dir, params.coverage_type)


if __name__ == '__main__':
  logging.basicConfig(format='[%(asctime)s %(levelname)s] %(message)s',
                      level=logging.INFO)
  sys.exit(main())
