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

class PhosphorusCommand(recipe_api.RecipeApi):
  """Module for issuing Phosphorus commands"""

  def initialize(self):
    self._cmd = None
    self._version = 'latest'

  def _run(self, subcommand, request, request_type):
    """Generic subcommand runner for phosphorus.

    Args:
      subcommand: (str) subcommand to run.
      request: proto input request to subcommand.
      request_type: request must be of this type.
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
      self.m.easy.step(
          subcommand,
          cmd,
          stdin=self.m.raw_io.input_text(json_format.MessageToJson(request)))

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
    self._run('upload-to-gs', request, UploadToGSRequest)

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

    with self.m.step.nest('ensure phosphorus'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'phosphorus')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/phosphorus/${platform}',
                          self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cmd = cipd_dir.join('phosphorus')