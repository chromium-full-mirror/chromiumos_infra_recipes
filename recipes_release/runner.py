# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for unittest framework."""

import argparse
import logging
import os
import sys
import unittest


def main(input_args):
  """The main function to run unittest/integration tests.

  Args:
    input_args: the input args.

  Returns:
    a unittest.TextTestRunner object.
  """

  # Discover and run tests.
  if input_args.test_file:
    suites = unittest.loader.TestLoader().discover(input_args.test_path,
                                                   input_args.test_file)
  else:
    suites = unittest.loader.TestLoader().discover(input_args.test_path,
                                                   '*_unittest.py')

  return unittest.TextTestRunner(verbosity=2, buffer=True).run(suites)


def _make_parser():
  """Return unittest parser."""
  parser = argparse.ArgumentParser(
      description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument(
      '--test_path',
      help='The path to look for tests, defaults to the current directory.',
      default=os.getcwd())
  parser.add_argument(
      'test_file', nargs='?',
      help=('A single test module to test, default to empty string, which '
            'means the runner will find test modules by test-pattern.'),
      default='')
  parser.add_argument('--debug', action='store_true',
                      help='Display the logging in unittest.')
  return parser


if __name__ == '__main__':
  unittest_parser = _make_parser()
  args = unittest_parser.parse_args()
  if args.debug:
    logging.getLogger().setLevel(logging.DEBUG)
  else:
    logging.getLogger().setLevel(logging.CRITICAL)

  result = main(args)

  if not result.wasSuccessful():
    sys.exit(1)
