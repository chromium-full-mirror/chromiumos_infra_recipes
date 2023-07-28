#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import sys
import unittest

import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(THIS_DIR, os.pardir)))

import convert_coverage_metadata_from_llvm as converter  # pylint: disable=wrong-import-position

CONSTANTS_FILE = 'constants.json'


def mocked_open(filename, _):
  if filename == CONSTANTS_FILE:
    content = '[{"prefix": "base-[^/]*/base","repo": "", "src_path":"base"}]'
  else:
    content = """{
            "data":
                [
                {
                    "files":
                    [
                        {
                        "segments":
                            [
                            [1, 12, 1, true, true],
                            [2, 7, 1, true, true],
                            [2, 14, 1, true, false],
                            [2, 18, 0, true, true],
                            [2, 25, 1, true, false],
                            [2, 27, 1, true, true],
                            [4, 4, 0, true, false],
                            [6, 3, 0, true, true],
                            [7, 2, 0, false, false]
                            ],
                        "summary":
                            {
                            "lines":
                                {
                                "count": 7,
                                "covered": 4,
                                "percent": 57
                                }
                            },
                        "filename": "/build/betty/base-0.0.1/base/base1.cc"
                        },
                        {
                        "segments":
                            [
                            [1, 12, 1, true, true],
                            [1, 25, 0, false, false]
                            ],
                        "summary":
                            {
                            "lines":
                                {
                                "count": 1,
                                "covered": 1,
                                "percent": 100
                                }
                        },
                        "filename": "/build/betty/base-0.0.1/base/base2.cc"
                    }
                    ]
                }
                ]
            }"""
  file_object = mock.mock_open(read_data=content).return_value
  file_object.__iter__.return_value = content.splitlines(True)
  return file_object


class GenerateCoverageMetadataTest(unittest.TestCase):

  def test_parse_exported_coverage_json(self):
    segments = [
        [1, 12, 1, True, True],
        [2, 7, 1, True, True],
        [2, 14, 1, True, False],
        [2, 18, 0, True, True],
        [2, 25, 1, True, False],
        [2, 27, 1, True, True],
        [4, 4, 0, True, False],
        [6, 3, 0, True, True],
        [7, 2, 0, False, False],
    ]

    expected_line_data = {1: 1, 2: 1, 3: 1, 4: 1, 5: 0, 6: 0, 7: 0}
    expected_block_data = {2: [[18, 24]], 4: [[4, -1]]}
    line_data, block_data = converter.extract_coverage_info(segments)
    self.assertDictEqual(expected_line_data, line_data)
    self.assertDictEqual(expected_block_data, block_data)

  def test_parse_exported_coverage_json_one_line(self):
    segments = [[1, 12, 1, True, True], [1, 25, 0, False, False]]

    expected_line_data = {1: 1}
    expected_block_data = {}
    line_data, block_data = converter.extract_coverage_info(segments)
    self.assertDictEqual(expected_line_data, line_data)
    self.assertDictEqual(expected_block_data, block_data)

  def test_parse_exported_coverage_json_uncovered_macros(self):
    segments = [[3, 49, 0, True, True], [5, 3, 0, False, True],
                [8, 1, 0, True, False], [8, 5, 0, True, True],
                [8, 14, 0, True, False], [10, 2, 0, False, False]]

    expected_line_data = {3: 0, 4: 0, 8: 0, 9: 0, 10: 0}
    expected_block_data = {}
    line_data, block_data = converter.extract_coverage_info(segments)
    self.assertDictEqual(expected_line_data, line_data)
    self.assertDictEqual(expected_block_data, block_data)

  @mock.patch('__builtin__.open', new=mocked_open)
  def test_to_compressed_file_record(self):
    file_coverage_data = {
        'segments': [
            [1, 12, 1, True, True],
            [2, 7, 1, True, True],
            [2, 14, 1, True, False],
            [2, 18, 0, True, True],
            [2, 25, 1, True, False],
            [2, 27, 1, True, True],
            [4, 4, 0, True, False],
            [6, 3, 0, True, True],
            [7, 2, 0, False, False],
        ],
        'summary': {
            'lines': {
                'covered': 4,
                'count': 7,
            }
        },
        'filename': '/build/betty/base-0.0.1/base/base.cc',
    }
    expected_record = {
        'path':
            '//base/base.cc',
        'summaries': [{
            'covered': 4,
            'name': 'line',
            'total': 7,
        }],
        'lines': [
            {
                'first': 1,
                'last': 4,
                'count': 1,
            },
            {
                'first': 5,
                'last': 7,
                'count': 0,
            },
        ],
        'uncovered_blocks': [{
            'line': 2,
            'ranges': [{
                'first': 18,
                'last': 24,
            }]
        }, {
            'line': 4,
            'ranges': [{
                'first': 4,
                'last': -1,
            }]
        }],
    }
    self.maxDiff = None
    record = converter.to_compressed_file_record(file_coverage_data,
                                                 CONSTANTS_FILE)
    self.assertDictEqual(expected_record, record)

  # This test uses made-up segments, and the intention is to test that for
  # *uncontinous* regions, even if their lines are executed the same number of
  # times, when converted to compressed format, lines in different regions
  # shouldn't be merged together.
  @mock.patch('__builtin__.open', new=mocked_open)
  def test_to_compressed_file_record_for_uncontinous_lines(self):
    file_coverage_data = {
        'segments': [
            [102, 35, 4, True, True],
            [104, 4, 0, False, False],
            [107, 35, 4, True, True],
            [109, 4, 0, False, False],
        ],
        'summary': {
            'lines': {
                'covered': 6,
                'count': 6,
            }
        },
        'filename': '/build/betty/base-0.0.1/base/base.cc',
    }
    expected_record = {
        'path':
            '//base/base.cc',
        'summaries': [{
            'covered': 6,
            'name': 'line',
            'total': 6,
        }],
        'lines': [
            {
                'first': 102,
                'last': 104,
                'count': 4,
            },
            {
                'first': 107,
                'last': 109,
                'count': 4,
            },
        ]
    }
    self.maxDiff = None
    record = converter.to_compressed_file_record(file_coverage_data,
                                                 CONSTANTS_FILE)
    self.assertDictEqual(expected_record, record)

  def test_rebase_line_and_block_data(self):
    line_data = [(1, 1), (2, 1), (3, 1), (4, 1), (5, 0), (6, 0), (7, 0)]
    block_data = {2: [[18, 24]]}
    file_name = 'base/base.cc'
    diff_mapping = {'base/base.cc': {'2': [16, 'A line added by the patch.']}}

    rebased_line_data, rebased_block_data = (
        converter.rebase_line_and_block_data(line_data, block_data,
                                             diff_mapping[file_name]))

    expected_line_data = [(16, 1)]
    expected_block_data = {16: [[18, 24]]}
    self.maxDiff = None
    self.assertListEqual(expected_line_data, rebased_line_data)
    self.assertDictEqual(expected_block_data, rebased_block_data)

  @mock.patch('__builtin__.open', new=mocked_open)
  def test_to_compressed_file_record_with_diff_mapping(self):
    file_coverage_data = {
        'segments': [
            [1, 12, 1, True, True],
            [2, 7, 1, True, True],
            [2, 14, 1, True, False],
            [2, 18, 0, True, True],
            [2, 25, 1, True, False],
            [2, 27, 1, True, True],
            [4, 4, 0, True, False],
            [6, 3, 0, True, True],
            [7, 2, 0, False, False],
        ],
        'summary': {
            'lines': {
                'covered': 2,
                'count': 7,
            }
        },
        'filename': '/build/betty/base-0.0.1/base/base.cc',
    }
    diff_mapping = {
        'base/base.cc': {
            '2': [10, 'A line added by the patch.'],
            '3': [11, 'Another added line.'],
            '5': [16, 'One more line.']
        }
    }

    record = converter.to_compressed_file_record(file_coverage_data,
                                                 CONSTANTS_FILE, diff_mapping)

    expected_record = {
        'path':
            '//base/base.cc',
        'summaries': [{
            'covered': 2,
            'name': 'line',
            'total': 7,
        }],
        'lines': [
            {
                'first': 10,
                'last': 11,
                'count': 1,
            },
            {
                'first': 16,
                'last': 16,
                'count': 0,
            },
        ],
        'uncovered_blocks': [{
            'line': 10,
            'ranges': [{
                'first': 18,
                'last': 24,
            }]
        }],
    }

    self.maxDiff = None
    self.assertDictEqual(expected_record, record)

  @mock.patch('__builtin__.open', new=mocked_open)
  def test_load_files_coverage_data(self):
    expected_files_coverage_data = [
        {
            'path': '//base/base2.cc',
            'lines': [{
                'count': 1,
                'last': 1,
                'first': 1,
            }],
            'summaries': [{
                'covered': 1,
                'name': 'line',
                'total': 1,
            }],
        },
        {
            'path':
                '//base/base1.cc',
            'lines': [{
                'count': 1,
                'last': 4,
                'first': 1,
            }, {
                'count': 0,
                'last': 7,
                'first': 5,
            }],
            'summaries': [{
                'covered': 4,
                'name': 'line',
                'total': 7,
            }],
            'uncovered_blocks': [{
                'ranges': [{
                    'last': 24,
                    'first': 18,
                }],
                'line': 2,
            }, {
                'ranges': [{
                    'last': -1,
                    'first': 4,
                }],
                'line': 4,
            }],
        },
    ]
    coverage_files = ['coverage.json']
    files_coverage_data = converter.load_files_coverage_data(
        coverage_files, CONSTANTS_FILE, None)
    self.maxDiff = None
    self.assertListEqual(expected_files_coverage_data, files_coverage_data)

  @mock.patch.object(converter, 'load_files_coverage_data')
  @mock.patch.object(converter.repository_util, 'get_file_revisions')
  def test_generate_metadata_for_full_repo_coverage(
      self, mock_GetFileRevisions, mock_load_files_coverage_data):
    mock_GetFileRevisions.return_value = {
        '//dir1/file1.cc': ('hash1', 1234),
        '//dir2/file2.cc': ('hash2', 5678),
    }
    mock_load_files_coverage_data.return_value = [
        {
            'path':
                '//dir1/file1.cc',
            'lines': [{
                'count': 1,
                'last': 4,
                'first': 1,
            }, {
                'count': 0,
                'last': 7,
                'first': 5,
            }],
            'summaries': [{
                'covered': 4,
                'name': 'line',
                'total': 7,
            }],
            'uncovered_blocks': [{
                'ranges': [{
                    'last': 24,
                    'first': 18,
                }],
                'line': 2,
            }, {
                'ranges': [{
                    'last': -1,
                    'first': 4,
                }],
                'line': 4,
            }],
        },
        {
            'path': '//dir2/file2.cc',
            'lines': [{
                'count': 1,
                'last': 1,
                'first': 1,
            }],
            'summaries': [{
                'covered': 1,
                'name': 'line',
                'total': 1,
            }],
        },
    ]

    compressed_data = converter.convert_metadata(
        coverage_files=['/path/to/coverage_files'],
        checkout_dir='/path/to/checkout_dir',
        project_dir='project_dir',
        output_dir='/path/to/output_dir',
        constants_file='constants.json',
        diff_mapping=None,
    )

    self.maxDiff = None
    expected_compressed_summaries = [{'covered': 5, 'total': 8, 'name': 'line'}]

    self.assertListEqual(expected_compressed_summaries,
                         compressed_data['summaries'])

    expected_compressed_dirs = [
        {
            'dirs': [
                {
                    'path': '//dir1/',
                    'name': 'dir1/',
                    'summaries': [{
                        'covered': 4,
                        'total': 7,
                        'name': 'line',
                    }]
                },
                {
                    'path': '//dir2/',
                    'name': 'dir2/',
                    'summaries': [{
                        'covered': 1,
                        'total': 1,
                        'name': 'line',
                    }]
                },
            ],
            'files': [],
            'summaries': [{
                'covered': 5,
                'total': 8,
                'name': 'line'
            }],
            'path': '//'
        },
        {
            'dirs': [],
            'files': [{
                'name': 'file1.cc',
                'path': '//dir1/file1.cc',
                'summaries': [{
                    'covered': 4,
                    'total': 7,
                    'name': 'line',
                }]
            }],
            'summaries': [{
                'covered': 4,
                'total': 7,
                'name': 'line',
            }],
            'path': '//dir1/'
        },
        {
            'dirs': [],
            'files': [{
                'name': 'file2.cc',
                'path': '//dir2/file2.cc',
                'summaries': [{
                    'covered': 1,
                    'total': 1,
                    'name': 'line',
                }]
            }],
            'summaries': [{
                'covered': 1,
                'total': 1,
                'name': 'line',
            }],
            'path': '//dir2/'
        },
    ]

    self.assertListEqual(expected_compressed_dirs, compressed_data['dirs'])

    expected_compressed_files = [
        {
            'path': '//dir1/file1.cc',
            'lines': [{
                'count': 1,
                'last': 4,
                'first': 1,
            }, {
                'count': 0,
                'last': 7,
                'first': 5,
            }],
            'summaries': [{
                'covered': 4,
                'name': 'line',
                'total': 7,
            }],
            'uncovered_blocks': [{
                'ranges': [{
                    'last': 24,
                    'first': 18,
                }],
                'line': 2,
            }, {
                'ranges': [{
                    'last': -1,
                    'first': 4,
                }],
                'line': 4,
            }],
            'revision': 'hash1',
            'timestamp': 1234,
        },
        {
            'path': '//dir2/file2.cc',
            'lines': [{
                'count': 1,
                'last': 1,
                'first': 1,
            }],
            'summaries': [{
                'covered': 1,
                'name': 'line',
                'total': 1,
            }],
            'revision': 'hash2',
            'timestamp': 5678,
        },
    ]

    self.assertListEqual(expected_compressed_files, compressed_data['files'])


if __name__ == '__main__':
  unittest.main()
