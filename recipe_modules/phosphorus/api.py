# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.test_platform.phosphorus.prejob import PrejobRequest
from PB.test_platform.phosphorus.runtest import RunTestRequest
from PB.test_platform.phosphorus.upload_to_tko import UploadToTkoRequest
from PB.test_platform.phosphorus.upload_to_gs import UploadToGSRequest
from PB.test_platform.phosphorus.upload_to_gs import UploadToGSResponse

class PhosphorusCommand(recipe_api.RecipeApi):
  """Module for issuing Phosphorus commands"""

  def __init__(self, properties, **kwargs):
    super(PhosphorusCommand, self).__init__(**kwargs)
    self._cmd = None
    self._version = str(properties.version.cipd_label)
    if not self._version: # pragma: no cover
      raise ValueError('No version label provided for '
          'phosphorus CIPD package.')

  def _run(self,
           subcommand,
           request, request_type,
           response_type=None, send_response=False):
    """Generic subcommand runner for phosphorus.

    Args:
      subcommand: (str) subcommand to run
      request: proto input request to subcommand
      request_type: request must be of this type.
      response_type: response will be interpreted as this type.
      send_response: whether to relay a response from the command to the caller
    Returns:
      JSON proto of response_type if send_response is set, None otherwise
    """
    with self.m.step.nest('call `phosphorus`') as s:
      if not isinstance(request, request_type):
        raise ValueError('request is not of type %s' % request_type)
      s.presentation.logs['request'] = [json_format.MessageToJson(request)]
      self._ensure_phosphorus()
      cmd = [
        self._cmd,
        subcommand,
        '-input_json',
        '/dev/stdin',
      ]
      stdin=self.m.raw_io.input_text(json_format.MessageToJson(request))
      if not send_response:
        self.m.easy.step(subcommand, cmd, stdin=stdin)
        return
      cmd += [
          '-output_json',
          '/dev/stdout',
      ]
      response = self.m.easy.stdout_jsonpb_step(
          subcommand,
          cmd,
          response_type,
          stdin=stdin,
          test_output=response_type(),
          ok_ret=(0,))
      s.presentation.logs['response'] = [json_format.MessageToJson(response)]
      return response

  def prejob(self, request):
    """Run a prejob or a provision via `prejob` subcommand.

    Args:
      request: a PrejobRequest.
    """
    self._run('prejob', request, PrejobRequest)

  def run_test(self, request):
    """Run a test via `run-test` subcommand.

    Args:
      request: a RunTestRequest.
    """
    self._run('run-test', request, RunTestRequest)

  def upload_to_gs(self, request):
    """Upload selected test results to GS via `upload-to-gs` subcommand.

    Args:
      request: an UploadToGSRequest.
    """
    return self._run('upload-to-gs', request, UploadToGSRequest,
              UploadToGSResponse, send_response=True)

  def upload_to_tko(self, request):
    """Upload test results to TKO via `upload-to-tko` subcommand.

    Args:
      request: an UploadToTkoRequest.
    """
    self._run('upload-to-tko', request, UploadToTkoRequest)

  def _ensure_phosphorus(self):
    """Ensure the phosphorus CLI is installed."""
    if self._cmd:
      return

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure phosphorus'):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'phosphorus')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/phosphorus/${platform}',
                          self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cmd = cipd_dir.join('phosphorus')
