# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to aggregate files coverage data to directories and components.

The code coverage data format is defined at:
https://chromium.googlesource.com/infra/infra/+/HEAD/appengine/findit/model/proto/code_coverage.proto
"""

from collections import defaultdict
import posixpath


def get_aggregated_coverage_data_from_files(files_coverage_data):
  """Aggregates files coverage data to directories and components.

  Note: this function assumes that all files are written in the same language,
  and have same metrics

  Args:
    files_coverage_data (list): A list of File coverage data.

  Returns:
    A dict mapping from directory to GroupCoverageSummary data.
  """
  per_directory_summaries = _caclulate_per_directory_summaries(
      files_coverage_data)
  per_directory_files = _calculate_per_directory_files(files_coverage_data)
  per_directory_subdirs = _calculate_per_directory_subdirs(
      per_directory_summaries)
  per_directory_coverage_data = {}
  for dir_path in per_directory_summaries:
    per_directory_coverage_data[dir_path] = {
        'path': dir_path,
        'dirs': per_directory_subdirs[dir_path],
        'files': per_directory_files[dir_path],
        'summaries': per_directory_summaries[dir_path],
    }

  return per_directory_coverage_data


def _caclulate_per_directory_summaries(files_coverage_data):
  """Calculates and returns per directory coverage metric summaries.

  Args:
    files_coverage_data (list): A list of File coverage data.

  Returns:
    A dict mapping from directory to coverage metric summaries.
  """
  per_directory_summaries = defaultdict(lambda: _new_summaries(
      files_coverage_data[0]['summaries']))
  for file_record in files_coverage_data:
    parent_dir = posixpath.dirname(file_record['path'])
    while parent_dir != '//':
      # In the coverage data format, dirs end with '/' except for root.
      parent_coverage_path = parent_dir + '/'
      _merge_summary(per_directory_summaries[parent_coverage_path],
                     file_record['summaries'])
      parent_dir = posixpath.dirname(parent_dir)

    _merge_summary(per_directory_summaries['//'], file_record['summaries'])

  return per_directory_summaries


def _calculate_per_directory_files(files_coverage_data):
  """Calculates and returns per directory files CoverageSummary.

  Args:
    files_coverage_data (list): A list of File coverage data.

  Returns:
    A dict mapping from directory to a list of CoverageSummary for file.
  """
  per_directory_files = defaultdict(list)
  for file_record in files_coverage_data:
    direct_parent_dir = posixpath.dirname(file_record['path'])
    if direct_parent_dir != '//':
      # In the coverage data format, dirs end with '/' except for root.
      direct_parent_dir += '/'

    per_directory_files[direct_parent_dir].append({
        'name': posixpath.basename(file_record['path']),
        'path': file_record['path'],
        'summaries': file_record['summaries'],
    })

  return per_directory_files


def _calculate_per_directory_subdirs(per_directory_summaries):
  """Calculates and returns per directory sub directories CoverageSummary.

  Args:
    per_directory_summaries (dict): A dict mapping from directory to coverage
                                    metric summaries.

  Returns:
    A dict mapping from directory to a list of CoverageSummary for directory.
  """
  per_directory_subdirs = defaultdict(list)
  for dir_path in sorted(per_directory_summaries.keys()):
    if dir_path == '//':
      continue

    assert dir_path.endswith('/'), (
        'Directory path: %s is expected to end with / in coverage data format' %
        dir_path)
    parent_dir_path, dirname = posixpath.split(dir_path[:-1])
    if parent_dir_path != '//':
      parent_dir_path += '/'

    per_directory_subdirs[parent_dir_path].append({
        'name': dirname + '/',
        'path': dir_path,
        'summaries': per_directory_summaries[dir_path],
    })

  return per_directory_subdirs


def _merge_summary(merge_dest, merge_src):
  """Merges to 'summaries' fields in metadata format.

  Two sumaries are required to have the exact same metrics, and this method
  adds the 'total' and 'covered' field of each metric in the second parameter
  to the corresponding field in the first parameter.

  Each parameter is expected to be in the following format:
  [{'name': 'line', 'total': 10, 'covered': 9},
   {'name': 'region', 'total': 10, 'covered': 9},
   {'name': 'function', 'total': 10, 'covered': 9}]
  """

  def get_metrics(summaries):
    return {s['name'] for s in summaries}

  assert get_metrics(merge_dest) == get_metrics(merge_src), (
      '%s and %s are expected to have the same metrics' %
      (merge_dest, merge_src))

  merge_src_dict = {i['name']: i for i in merge_src}
  for merge_dest_item in merge_dest:
    for field in ('total', 'covered'):
      merge_dest_item[field] += merge_src_dict[merge_dest_item['name']][field]


def _new_summaries(reference_summaries):
  """Returns new summaries with the same metrics as the reference one."""
  return [{
      'name': summary['name'],
      'covered': 0,
      'total': 0
  } for summary in reference_summaries]
