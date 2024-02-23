#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to manipulate e2e coverage."""
import argparse
from datetime import date
import json
import logging
import os
import sys


def write_metadata(gs_bucket: str, gs_path: str, board: str, version: str,
                   snapshot_version: str, file_path: str) -> None:
  """Write metadata associated with e2e coverage.

  Args:
    gs_bucket: GCS bucket with the coverage artifacts.
    gs_path: Path to the artifact.
    board: Board used for generating artifacts.
    version: CROS version used to build artifacts.
    snapshot_version: Complete version that generated snapshot.
    file_path: Path of file to store the metadata.
  """
  content = {
      'artifacts_bucket': gs_bucket,
      'artifacts_path': gs_path,
      'board': board,
      'version': version,
      'snapshot_version': snapshot_version,
      'date': date.today().isoformat(),
  }

  with open(file_path, 'w', encoding='utf-8') as f:
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

  parser.add_argument('--snapshot-version', required=True, type=str,
                      help='Complete snapshot version including builderid.')

  parser.add_argument(
      '--path', required=True, type=str,
      help='absolute path to the file to store the metadata, must exist')

  return parser.parse_args(args=args)


def main():
  params = _parse_args(sys.argv[1:])

  if not os.path.exists(os.path.dirname(params.path)):
    raise RuntimeError(f'Parent directory for {params.path} must exist')

  write_metadata(params.artifacts_bucket, params.artifacts_path, params.board,
                 params.version, params.snapshot_version, params.path)


if __name__ == '__main__':
  logging.basicConfig(format='[%(asctime)s %(levelname)s] %(message)s',
                      level=logging.INFO)
  sys.exit(main())
