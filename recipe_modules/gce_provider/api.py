# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.bot_scaling import ScalingAction
from PB.go.chromium.org.luci.gce.api.config.v1.config import Config, Configs
#from PB.go.chromium.org.luci.gce.api.config.v1 import service as service_pb2

from recipe_engine import recipe_api
from google.protobuf import json_format

import json

GCE_PROVIDER_URL = 'gce-provider.appspot.com'


class GceProvider(recipe_api.RecipeApi):
  """A module that interacts with the GCE Provider config service.

  Depends on 'prpc' binary available in $PATH:
  https://godoc.org/go.chromium.org/luci/grpc/cmd/prpc

  """

  def get_current_config(self, ids):
    """Function to retrieve the current config from GCE Provider.

    Args:
      ids (list): A list of all the config prefixes to retrieve.

    Returns:
      Configs, list of GCE Provide Config objects.
    """
    config_mapping = []
    for prefix in ids:
      req = {'id': prefix}
      step = self._run(
          'Get', req,
          test_stdout=lambda: self.test_api.get_current_config_step_test_data())
      config_mapping.append(
          json_format.ParseDict(step, Config(), ignore_unknown_fields=True))
    return Configs(vms=config_mapping)

  def _run(self, method, stdin_json, step_name=None, test_stdout=None):
    """Return a swarming command step.

    Args:
      method (str): config.Configuration method to call.
      stdin_json (json): json input data to Step command.
      step_name (str): Presentation name for step.
      test_stdout (dict): dictionary based test data.
    """
    step_name = step_name or ('gce-provider.config.' + method)
    cmd = [
        'prpc', 'call', '-format=json', GCE_PROVIDER_URL,
        'config.Configuration.' + method
    ]
    return self.m.easy.stdout_json_step(step_name, cmd, test_stdout=test_stdout,
                                        stdin_json=stdin_json, infra_step=True)
