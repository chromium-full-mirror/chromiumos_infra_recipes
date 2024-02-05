#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to manipulate e2e coverage."""
import argparse
import json
import logging
import os
import sys

_METADATA_FILENAME = 'e2e_metadata.json'


def write_metadata(gs_bucket: str, gs_path: str, board: str, version: str,
                   out_dir: str) -> None:
  """Write metadata associated with e2e coverage.

  Args:
    gs_bucket: GCS bucket with the coverage artifacts.
    gs_path: Path to the artifact.
    board: Board used for generating artifacts.
    version: CROS version used to build artifacts.
    out_dir: Directory to store the metadata.
  """
  content = {
      'artifacts_bucket': gs_bucket,
      'artifacts_path': gs_path,
      'board': board,
      'version': version,
  }

  with open(os.path.join(out_dir, _METADATA_FILENAME), 'w',
            encoding='utf-8') as f:
    f.write(json.dumps(content))


def _parse_args(args):
  parser = argparse.ArgumentParser(description='Manipulate e2e coverage files.')

  parser.add_argument('--artifacts-bucket', required=True, type=str,
                      help='The artifacts where we have the tarball.')

  parser.add_argument('--artifacts-path', required=True, type=str,
                      help='Path to the tarball.')

  parser.add_argument('--board', required=True, type=str,
                      help='Board used to generate artifacts.')

  parser.add_argument('--version', required=True, type=str,
                      help='CROS version used to generate artifacts.')

  parser.add_argument(
      '--output-dir', required=True, type=str,
      help='absolute path to the directory to store the metadata, must exist')

  return parser.parse_args(args=args)


def main():
  params = _parse_args(sys.argv[1:])

  if not os.path.exists(params.output_dir):
    raise RuntimeError(f'Output directory {params.output_dir} must exist')

  write_metadata(params.artifacts_bucket, params.artifacts_path, params.board,
                 params.version, params.output_dir)


if __name__ == '__main__':
  logging.basicConfig(format='[%(asctime)s %(levelname)s] %(message)s',
                      level=logging.INFO)
  sys.exit(main())
