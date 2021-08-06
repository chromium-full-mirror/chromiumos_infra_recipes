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


def clean_file_name(file_name, constants, project_name, build_target_name,
                    file_name_prepend):
  """Cleans a file name based on the provided mappings.

  TODO(b/187795079) The provided constants file gives a mapping of regex
  `prefix`s to match the given file name to. If one is found, the prefix
  portion is replaced with the corresponding `src_path`. This function
  encapsulates the conversion function that should eventually live in chromite.

  Args:
    file_name (str): The file name from the coverage llvm json file.
    constants (str): Content containing prefix/src_path pairs per project.
    project_name (str): The project to load constants data from.
    build_target_name(str): The name of the build target (i.e. sarien).
    file_name_prepend(str): What to prepend file names with after
      performing the replacements.


  Returns:
    A string formatted as: {file_name_prepend}{constants[src_path]}/{file_name}
    if a mapping is found otherwise None.
  """
  coverage_path = os.path.normpath(file_name)

  for mapping in constants[project_name]:
    pre = '(/build/{})?/?{}'.format(build_target_name, mapping['prefix'])
    if re.match(pre, coverage_path):
      coverage_path = re.sub(pre, mapping['src_path'], coverage_path)
      return file_name_prepend + coverage_path

  return None


def clean_file_names_in_llvm_coverage_json(llvm_coverage_json, constants,
                                           project_name, build_target_name,
                                           file_name_prepend):
  """Cleans an llvm coverage json file's file names.

  Takes a valid llvm coverage json file, and runs all the file names through
  the clean_file_name function. Only keeps file names that are successfully
  cleaned. The result is a new llvm json function that has all the file names
  cleaned.

  Args:
    llvm_coverage_json (str): The content from the llvm coverage json file.
    constants (str): Content containing prefix/src_path pairs per project.
    project_name (str): The project to load constants data from.
    build_target_name(str): The name of the build target (i.e. sarien).
    file_name_prepend(str): What to prepend file names with after
      performing the replacements.


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
      cleaned_file_name = clean_file_name(filename, constants, project_name,
                                          build_target_name, file_name_prepend)
      if cleaned_file_name is not None:
        file_data['filename'] = cleaned_file_name
        coverage_data.append(file_data)

  return {
      'data': [{
          'files': coverage_data
      }],
      'type': coverage_type,
      'version': coverage_version,
  }
