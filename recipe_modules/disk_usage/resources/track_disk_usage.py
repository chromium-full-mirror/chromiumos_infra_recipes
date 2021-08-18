#-*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=superfluous-parens

import argparse
import logging
import os
from os.path import isdir, join
import sys



def _track_free():
  os.system('df -h .')


def _track_usage(d, depth=0):
  for f in os.listdir(d):
    os.system('du -sh ' + join(d, f))

  print('~' * 60)
  # Recurse if needed
  if depth > 0:
    for f in os.listdir(d):
      if isdir(join(d, f)) and not f.startswith('.'):
        _track_usage(join(d, f), depth - 1)


def main():
  parser = argparse.ArgumentParser(description='Track the disk usage.',
                                   prog='./runit.py track_disk_usage.py')
  parser.add_argument('--dir', help='the dir to track if not cwd')
  parser.add_argument('--depth', type=int, help='the depth to iterate till')
  args = parser.parse_args()

  try:
    _track_free()
    d = args.dir or os.getcwd()
    _track_usage(d, args.depth)
  except Exception as e:  # pylint: disable=broad-except
    logging.error(str(e))


if __name__ == '__main__':
  logging.basicConfig()
  logging.getLogger().setLevel(logging.INFO)
  sys.exit(main())
