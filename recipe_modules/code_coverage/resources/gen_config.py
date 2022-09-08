#!/usr/bin/env vpython3
# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This script generates build artifact path mapping configs.

When there is source code folder name or structure change, run this
script to regenerate the configuration. No arguments are required, the
input and output are derived from the code base structure.

$ ./gen_config.py
"""

import logging
import json
import os
from pathlib import Path
from xml.etree import ElementTree


def gen_mapping_config(cros_home, manifest_file):
  """Generates artifacts path mapping from the manifest .xml file

    manifest file defines all repos referenced from code search and
    corresponding location, we can generate the source mapping with
    the path and a little heuristics

    Return: a list of tuple, 1st element is the full path, 2nd element
    is the specific words used to genrate the matching pattern.
    """

  path_configs = []
  doc = ElementTree.parse(manifest_file)
  for project in doc.findall('./project'):

    # The components between path prefix and the file name, which is used to
    # generate file path matching patterns.
    match_folder = ""
    absolute_path = project.attrib['path']
    relative_path = ""
    config_components = []

    # Because repo 'src/platform2' does not include specific sub folder for
    # matching, we need to explore another level of sub folders explicitly.
    if absolute_path == 'src/platform2':
      for entry in os.scandir(os.path.join(cros_home, 'src/platform2')):
        if entry.is_dir() and not entry.name.startswith('.'):
          match_folder = entry.name
          relative_path = match_folder
          config_components.append(
              (os.path.join(absolute_path,
                            entry.name), relative_path, match_folder))
    elif absolute_path.startswith('src/platform/'):
      match_folder = absolute_path.removeprefix('src/platform/')
      relative_path = ""
      config_components.append((absolute_path, relative_path, match_folder))
    elif absolute_path.startswith('src/aosp/external'):
      match_folder = absolute_path.removeprefix('src/aosp/external/')
      relative_path = ""
      config_components.append((absolute_path, relative_path, match_folder))
    elif absolute_path.startswith('src/third_party'):
      match_folder = absolute_path.removeprefix('src/third_party/')
      relative_path = ""
      config_components.append((absolute_path, relative_path, match_folder))
    else:
      continue

    for absolute_path, relative_path, match_folder in config_components:
      path_configs.append({
          'path_pattern':
              r'.*/%s/(.*[a-zA-Z0-9-_]+\.[a-zA-Z0-9-_]+)' % match_folder,
          'absolute_path':
              absolute_path,
          'relative_path':
              relative_path
      })

  return path_configs


def gen_all_mapping_configs(cros_home):
  config1 = gen_mapping_config(cros_home,
                               os.path.join(cros_home, 'manifest/full.xml'))
  config2 = gen_mapping_config(
      cros_home, os.path.join(cros_home, 'manifest-internal/internal_full.xml'))
  return config1 + config2


if __name__ == '__main__':
  home_dir = os.path.normpath(os.path.join(__file__, '../../../../../..'))
  configs = gen_all_mapping_configs(home_dir)
  path_mapping_file = Path(__file__).parent.joinpath('path_mapping.json')
  with path_mapping_file.open('w') as f:
    json.dump(configs, f, indent=2)
  logging.info('generated config to %s', path_mapping_file)
