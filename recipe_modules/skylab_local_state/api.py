# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.test_platform.skylab_local_state.load import LoadRequest, LoadResponse
from PB.test_platform.skylab_local_state.save import SaveRequest


class SkylabLocalStateCommand(recipe_api.RecipeApi):
  """Module for issuing skylab_local_state commands"""

  def initialize(self):
    self._cmd = None
    self._version = 'latest'

  def load(self, request):
    """Create a host info file via `load` command.

    Args:
      request: a LoadRequest.

    Returns: LoadResponse.
    """
    with self.m.step.nest('call `skylab_local_state`'):
      if not isinstance(request, LoadRequest):
        raise ValueError('request is not of type %s' % LoadRequest)
      self._ensure_skylab_local_state()
      cmd = [
          self._cmd,
          'load',
          '-input_json',
          '/dev/stdin',
          '-output_json',
          '/dev/stdout',
      ]
      return self.m.easy.stdout_jsonpb_step(
          'load',
          cmd,
          LoadResponse,
          stdin_data=json_format.MessageToJson(request),
          test_output=LoadResponse())

  def save(self, request):
    """Update the DUT state file via `save` command.

    Args:
      request: a SaveRequest.
    """
    with self.m.step.nest('call `skylab_local_state`'):
      if not isinstance(request, SaveRequest):
        raise ValueError('request is not of type %s' % SaveRequest)
      self._ensure_skylab_local_state()
      cmd = [
          self._cmd,
          'save',
          '-input_json',
          '/dev/stdin',
      ]
      return self.m.easy.step(
          'save',
          cmd,
          stdin_data=json_format.MessageToJson(request))

  def _ensure_skylab_local_state(self):
    """Ensure the skylab_local_state CLI is installed."""
    if self._cmd:
      return

    with self.m.step.nest('ensure skylab_local_state'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'skylab_local_state')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/skylab_local_state/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cmd = cipd_dir.join('skylab_local_state')
