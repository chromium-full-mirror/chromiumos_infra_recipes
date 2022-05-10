# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to aid with code coverage related functions."""
import os
import re
import json


def is_valid_llvm_coverage_json_file(data):
  """Determines if the provided data is in the llvm coverage json format.

  Args:
    data (str): The data to check.

  Returns:
    True if the data is in the llvm coverage json format otherwise False.
  """
  try:
    json_data = json.loads(data)

    return 'type' in json_data \
           and 'version' in json_data \
           and 'data' in json_data \
           and json_data['type'] == 'llvm.coverage.json.export'
  except ValueError:
    return False


def clean_file_name(file_path, path_mappings):
  """Cleans a file name based on the provided mappings.

  Step 1. normalize the file_path with removing the lib version
  For example,
  ..bluez-5.54-r711/work/bluez-5.54/bluez/current/src/profile.c
  should be converted to
  ..bluez/work/bluez/bluez/current/src/profile.c

  Step 2. find path mappings from configuration
  For example,
  paths like ".*/bluez/current/src/(.*)" should be mapping to
  "third_party/bluez/current/src/[group(0)]"

  Step 3. extract the matching group to combine absolute path
  and relative path respectively, and return

  Args:
    file_name (str): The file name from the coverage llvm json file.
    path_mappings (str): Content containing path mappings.

  Returns:
    A tuple of (absolute_path, relative_path) if a mapping is found
    otherwise None.
  """
  absolute_path = os.path.normpath(file_path)
  absolute_path = re.sub(r'\-\d+(\.\d+)*(\-[\w\d]+)?/', '/', absolute_path)

  for mapping in path_mappings:
    m = re.match(mapping['path_pattern'], absolute_path)
    if m:
      absolute_path = os.path.join(mapping['absolute_path'], m.group(1))
      relative_path = os.path.join(mapping['relative_path'], m.group(1))
      return absolute_path, relative_path

  return None


def create_llvm_coverage_json(coverage_data,
                              coverage_type='llvm.coverage.json.export',
                              coverage_version='2.0.1'):
  """Given coverage_data, generate llvm format coverage json.

  Args:
    coverage_data (List): The coverage data containing array of file cov info.
    coverate_type (str): Type of coverage
    coverage_version (str): Coverage version

  Returns:
    coverage json llvm format.
  """
  coverage_json = {
      'data': [{
          'files': coverage_data,
      }],
      'type': coverage_type,
      'version': coverage_version,
  }
  return coverage_json


def clean_file_names_in_llvm_coverage_json(llvm_coverage_json, path_mappings,
                                           to_absolute_path=True):
  """Cleans an llvm coverage json file's file names.

  Takes a valid llvm coverage json file, and runs all the file names through
  the clean_file_name function. Only keeps file names that are successfully
  cleaned. The result is a new llvm json function that has all the file names
  cleaned.

  Args:
    llvm_coverage_json (str): The content from the llvm coverage json file.
    path_mappings (str): Path matching rules for relative and absolute path.
    to_absolute_path (bool): Clean file path to absolute path or relative path,
      the former is used for absolute coverage data, and the latter is used
      for incremental coverage data.

  Returns:
    A json object in the coverage llvm json format with file names that
    have been successfully cleaned.
  """
  coverage_type = llvm_coverage_json['type']
  coverage_version = llvm_coverage_json['version']
  coverage_data = []

  for datum in llvm_coverage_json['data']:
    for file_data in datum['files']:
      filename = file_data['filename']
      cleaned_file_name = clean_file_name(filename, path_mappings)
      if cleaned_file_name is not None:
        if to_absolute_path:
          file_data['filename'] = cleaned_file_name[0]
        else:
          file_data['filename'] = cleaned_file_name[1]
        coverage_data.append(file_data)

  return create_llvm_coverage_json(coverage_data, coverage_type,
                                   coverage_version)
