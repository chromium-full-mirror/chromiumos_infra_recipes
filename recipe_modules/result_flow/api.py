# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.test_platform.result_flow.ctp import CTPRequest, CTPResponse


class ResultFlowCommand(recipe_api.RecipeApi):
  """Module for issuing result flow commands"""

  def __init__(self, properties, **kwargs):
    super(ResultFlowCommand, self).__init__(**kwargs)
    self._cmd = None
    self._version = str(properties.version.cipd_label) or 'latest'
    if not self._version:  # pragma: no cover
      raise ValueError('No version label provided for '
                       'result_flow CIPD package.')

  def _run(self, subcommand, request, request_type, response_type):
    """Generic subcommand runner for result flow.

    Args:
      subcommand: (str) subcommand to run
      request: proto input request to subcommand
      request_type: request must be of this type
      response_type: response will be interpreted as this type
    Returns:
      JSON proto of response_type
    """
    with self.m.step.nest('call `result_flow`') as presentation:
      if not isinstance(request, request_type):
        raise ValueError('request is not of type %s' % request_type)
      presentation.logs['request'] = [json_format.MessageToJson(request)]
      self._ensure_result_flow()
      cmd = [
          self._cmd,
          subcommand,
          '-input_json',
          '/dev/stdin',
      ]
      stdin = self.m.raw_io.input_text(json_format.MessageToJson(request))
      cmd += [
          '-output_json',
          '/dev/stdout',
      ]
      response = self.m.easy.stdout_jsonpb_step(subcommand, cmd, response_type,
                                                stdin=stdin,
                                                test_output=response_type(),
                                                ok_ret=(0,))
      presentation.logs['response'] = [json_format.MessageToJson(response)]
      return response

  def ctp(self, request):
    """Run the result_flow to pipe CTP data to TestPlanRun table in BQ.

    Args:
      request: a test_platform.result_flow.CTPRequest.
    """
    return self._run('ctp', request, CTPRequest, CTPResponse)

  def _ensure_result_flow(self):
    """Ensure the result_flow CLI is installed."""
    if self._cmd:
      return

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure result_flow'):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'result_flow')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/result_flow/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cmd = cipd_dir.join('result_flow')
