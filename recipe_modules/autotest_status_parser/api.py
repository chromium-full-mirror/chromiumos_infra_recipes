# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.test_platform.skylab_test_runner.result import Result


class AutotestStatusParserCommand(recipe_api.RecipeApi):
  """Module for issuing autotest_status_parser commands."""

  def initialize(self):
    self._version = 'latest'

  def parse(self, results_dir):
    """Extract test results from an results directory.

    Args:
      results_dir: a string pointing to a directory containing test results.

    Returns: Result.
    """
    with self.m.step.nest('call `autotest_status_parser`') as s:
      if not results_dir:
        raise ValueError('No results directory provided')
      binary = self._get_autotest_status_parser()
      cmd = [
          binary,
          'parse',
          results_dir,
      ]
      result = self.m.easy.stdout_jsonpb_step(
          'parse',
          cmd,
          Result,
          test_output=Result())
      s.presentation.logs['response'] = [json_format.MessageToJson(result)]
      return result

  def _get_autotest_status_parser(self):
    """Ensure the autotest_status_parser CLI is installed.

    Returns: string, the path to the binary.
    """
    with self.m.step.nest('ensure autotest_status_parser'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd',
                                                 'autotest_status_parser')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/autotest_status_parser/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        return cipd_dir.join('autotest_status_parser')
