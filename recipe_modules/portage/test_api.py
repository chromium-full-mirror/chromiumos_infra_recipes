# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing the portage module.

This module provides helpers to make testing CrOS recipes simpler and more
consistent.
"""

from recipe_engine import recipe_test_api

from RECIPE_MODULES.chromeos.util.util import read_test_file


class PortageTestApi(recipe_test_api.RecipeTestApi):
  """Helper class for testing CrOS Paygen Recipes."""
  EXAMPLE_SUCCESS_INSTALL_PACKAGES = read_test_file(
      'example_success_install_packages.txt', __file__)
  EXAMPLE_SUCCESS_INSTALL_PACKAGES_EXPECTED = read_test_file(
      'example_success_install_packages_expected.json', __file__)

  EXAMPLE_FAILURE_INSTALL_PACKAGES = read_test_file(
      'example_failure_install_packages.txt', __file__)
  EXAMPLE_FAILURE_INSTALL_PACKAGES_EXPECTED = read_test_file(
      'example_failure_install_packages_expected.json', __file__)

  EXAMPLE_BROKEN_INSTALL_PACKAGES = read_test_file(
      'example_broken_install_packages.txt', __file__)

  EXAMPLE_DOUBLE_EMERGE_INIT_SDK = read_test_file(
      'example_double_emerge_init_sdk.txt', __file__)
  EXAMPLE_DOUBLE_EMERGE_INIT_SDK_EXPECTED = read_test_file(
      'example_double_emerge_init_sdk_expected.json', __file__)
  EXAMPLE_IGNORED_EMERGE_PACKAGES = read_test_file(
      'example_ignored_emerge_packages.txt', __file__)
  EXAMPLE_IGNORED_EMERGE_PACKAGES_EXPECTED = read_test_file(
      'example_ignored_emerge_packages_expected.json', __file__)
  EXAMPLE_INFO_RUN_PARSING = read_test_file('example_info_run_parsing.txt',
                                            __file__)
  EXAMPLE_INFO_RUN_PARSING_EXPECTED = read_test_file(
      'example_info_run_parsing_expected.json', __file__)
