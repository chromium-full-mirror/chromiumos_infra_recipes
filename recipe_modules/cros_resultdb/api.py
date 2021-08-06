# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import base64
import os
import re

from recipe_engine import recipe_api


class ResultDBCommand(recipe_api.RecipeApi):
  """Module for chromium tests on skylab to upload result to Result DB."""

  def __init__(self, **kwargs):
    super(ResultDBCommand, self).__init__(**kwargs)
    self._result_adapter = None
    self._version = 'latest'

  def extract_resultdb_settings(self, test_args):
    """Extract resultdb settings from test_args.

    Args:
        test_args - A string of extra autotest arguments. See upload().

    Returns:
        json string
    """
    arg_re = re.compile(r'(\w+)[:=](.*)$')
    args_dict = {}
    for arg in test_args.split():
      match = arg_re.match(arg)
      if match:
        args_dict[match.group(1).lower()] = match.group(2)
    return base64.b64decode(args_dict.get('resultdb_settings', ''))

  def upload(self, builder_name, test_args, base_dir):
    """Call the resultDB module to upload test result

    Args:
      * builder_name - Luci builder name.
      * test_args - A string of extra autotest arguments,
          e.g. "key1=val1 key2=val2". Chromium tests use test_arg to pass
          runtime parameters to our autotest wrapper. We reuse it to pipe
          resultDB arguments, because it is easy to access in test runner
          recipe.
          test_args must contain resultdb_settings, which is base64 compressed
          json string, wrapping all resultdb parameters.
          For supported parameters, refer recipe_engine/resultdb module.
      * base_dir - The path of the base test results on the drone server.
          Chromium test result can be found at
          base_dir/autoserv_test/chromium/results.
    """
    rdb_settings = self.extract_resultdb_settings(test_args)
    assert rdb_settings, ('test_args should contain resultdb_settings to '
                          'upload result to resultdb. Got %s' % test_args)

    configs = self.m.json.loads(rdb_settings)
    assert configs.get('result_format') in [
        'gtest', 'json', 'single'
    ], 'result_format must be gtest, json or single, got %s' % configs.get(
        'result_format')
    assert configs.get('result_file') is not None, ('result_file '
                                                    'should not be empty.')
    # Test results on Drone server are not stored in swarming [start_dir],
    # e.g. "/usr/local/autotest/results/swarming-12345678/1".
    # So use general os.path to join.
    base = os.path.join(base_dir, 'autoserv_test', 'chromium', 'results')
    with self.m.step.nest('upload chromium test result to rdb') as rdb_step:
      result_file = os.path.join(base, configs.get('result_file'))
      # ResultDB in CrOS recipes only supports uploading result file,
      # so the cmd must accompany the result_adapter.
      self._ensure_result_adapter_executables()
      result_adapter = [
          self._result_adapter,
          configs.get('result_format'),
          '-result-file',
          result_file,
      ]
      if configs.get('artifact_directory'):
        result_adapter += [
            '-artifact-directory',
            os.path.join(base, configs.get('artifact_directory')),
        ]

      # Skylab tests can not wrap directly by rdb now. We only care the
      # result file from the test runs.
      rdb_cmd = result_adapter + ['--'] + ['echo']

      # add var 'builder' by default
      var = {'builder': builder_name}
      var.update(configs.get('base_variant', {}))

      base_tags = map(lambda x: tuple(x.split(':', 1)),
                      configs.get('base_tags', []))

      # wrap it with rdb-stream
      cmd = self.m.resultdb.wrap(
          rdb_cmd,
          base_tags=base_tags,
          base_variant=var,
          coerce_negative_duration=configs.get('coerce_negative_duration',
                                               True),
          test_id_prefix=configs.get('test_id_prefix', ''),
          test_location_base=configs.get('test_location_base'),
          location_tags_file=configs.get('location_tags_file'),
          require_build_inv=True,
          exonerate_unexpected_pass=configs.get('exonerate_unexpected_pass',
                                                True),
          include=True,
      )
      return self.m.step('run rdb', cmd)

  def _ensure_result_adapter_executables(self):
    """Ensure the result_adapter CLI is installed."""
    if self._result_adapter:
      return

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure result_adapter'):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'result_adapter')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('infra/tools/result_adapter/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._result_adapter = cipd_dir.join('result_adapter')
