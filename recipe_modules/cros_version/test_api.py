# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import textwrap
from .version import Version

from recipe_engine import recipe_test_api


class CrosVersionTestApi(recipe_test_api.RecipeTestApi):

  Version = Version

  @property
  def test_snapshot(self):
    return self.m.git_footers.test_position_num

  test_version_str = 'R99-1234.56.0'

  # Example chromeos_version.sh with historically-accurate contents.
  @staticmethod
  def chromeos_version_contents(version_str=None):
    """Set the workspace version for a test.

    Args:
      Version (str): The version to use.

    Returns:
      (str): Example contents for chromeos_version.sh
    """
    version = Version.from_string(version_str or
                                  CrosVersionTestApi.test_version_str)
    return textwrap.dedent(r'''\
        if something; then
          # Comment
          export CHROMEOS_BUILD={}
          # Other Comment
          CHROMEOS_BRANCH={}
          CHROMEOS_PATCH={}  # inline comment
        fi

        export CHROME_BRANCH={}
        '''.format(version.build, version.branch, version.patch,
                   version.chrome_branch))

  @recipe_test_api.mod_test_data
  @staticmethod
  def workspace_version(version_str=None):
    """Set the workspace version for a test.

    Args:
      Version (str): The version to use.

    Returns:
      (mod_test_data) to pass to api.test.
    """
    return version_str or CrosVersionTestApi.test_version_str