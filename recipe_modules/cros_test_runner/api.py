# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.test_platform.skylab_test_runner.steps.test_execution import RunTestsRequest, RunTestsResponse


class CrosTestRunnerCommand(recipe_api.RecipeApi):
  """Module for issuing cros_test_runner commands"""

  def __init__(self, properties, **kwargs):
    super(CrosTestRunnerCommand, self).__init__(**kwargs)
    self._cipd_dir = None
    self._version = str(properties.version.cipd_label) or 'latest'

  def execute_luciexe(self, request):
    """Execute work via cros_test_runner luciexe binary.

    Args:
      request: a RunTestsRequest.

    Returns: RunTestsResponse.
    """
    self._ensure_cros_test_runner()
    with self.m.step.nest('call binary') as s:
      cmd = self._cipd_dir.join('cros_test_runner')
      # Simply use the same directory for the sub-build because I'm lazy and
      # because the intent is to unwrap the sub-build completely to replace this
      # parent build eventually.
      sub_cwd = self.m.path['start_dir']
      input_json = sub_cwd.join('input.json')
      output_json = sub_cwd.join('output.json')

      self.m.file.write_proto('write input', input_json, request, 'JSONPB')

      # crbug.com/1119441: Clear out some output fields from a clone of the
      # parent Build that may have been already populated so far, because
      # sub_build() doesn't do it for us yet.
      build = build_pb2.Build()
      build.CopyFrom(self.m.buildbucket.build)
      for ofield in ['output', 'status', 'summary_markdown', 'steps']:
        build.ClearField(ofield)

      # sub_build() raises StepFailure if the sub-build completes in FAILURE
      # and InfraFailure if sub-build completes in INFRA_FAILURE.
      #
      # crbug.com/1115207: We currently interpret all failures in the
      # sub-luciexe as InfraFailure because test failures are bubbled up later
      # in the summary step. As test summary updates are moved into the luciexe,
      # we will no longer need to return the responses from this sub_build()
      # invocation and will instead start surfacing test failures as
      # StepFailure.
      with self.m.context(cwd=sub_cwd, infra_steps=True):
        self.m.step.sub_build(
            'launch luciexe',
            [cmd, '--', '-input_json', input_json, '-output_json', output_json],
            build,
        )

      responses = self.m.file.read_proto(
          'read output',
          output_json,
          RunTestsResponse,
          'JSONPB',
      )
      s.logs['responses'] = [json_format.MessageToJson(responses)]
      return responses

  def _ensure_cros_test_runner(self):
    """Ensure the cros_test_runner CLI is installed."""
    if self._cipd_dir:
      return

    with self.m.step.nest('ensure cros_test_runner'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'cros_test_runner')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/cros_test_runner/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cipd_dir = cipd_dir

  def cipd_package_version(self):
    """Return the CTP CIPD package version (e.g. prod/staging/latest)."""
    return self._version
