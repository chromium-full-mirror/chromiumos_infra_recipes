# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module that interacts with GCE Provider."""

import collections

from PB.go.chromium.org.luci.gce.api.config.v1.config import Config, Configs
from recipe_engine import recipe_api
from google.protobuf import json_format

GCE_PROVIDER_URL = 'gce-provider.appspot.com'


class NoneConfigFailure(recipe_api.StepFailure):
  """Error class for when GCE Provider returns None for a Configuration.Get"""

  def __init__(self, config_prefix):
    super().__init__(f'No config found for prefix {config_prefix}')


ConfigResponse = collections.namedtuple('ConfigResponse',
                                        ['configs', 'missing_configs'])


class GceProvider(recipe_api.RecipeApi):
  """A module that interacts with the GCE Provider config service.

  Depends on 'prpc' binary available in $PATH:
  https://godoc.org/go.chromium.org/luci/grpc/cmd/prpc
  """

  def update_gce_config(self, bid, config):
    """Function to update the config in GCE Provider.

    Args:
      bid (str):  bot group prefix to update.
      config(Config): GCE Provider config object

    Returns:
      Config, GCE Provider Config definition with updated values.
    """
    req = {
        'id': bid,
        'config': json_format.MessageToDict(config),
        'updateMask': {
            'paths': ['config.current_amount'],
        },
    }
    step = self._run(
        'Update', req,
        test_stdout=lambda: self.test_api.get_update_config_data(config),
        step_suffix=f' bot group {bid}')
    return json_format.ParseDict(step, Config(), ignore_unknown_fields=True)

  def _make_gce_config_call(self, prefix):
    """Function to make the GCE Provider call for Config

    Args:
      prefix (str): The bot prefix to make to GCE Provider configs.

    Returns:
      Step, the result of the call to GCE Provider
    """
    req = {'id': prefix}
    step = self._run(
        'Get', req,
        test_stdout=lambda: self.test_api.get_current_config_step_test_data(
            prefix), step_suffix=' (prefix: {})'.format(prefix))
    return step

  def get_current_config(self, ids):
    """Function to retrieve the current config from GCE Provider.

    Args:
      ids (list): A list of all the config prefixes to retrieve.

    Returns:
      ConfigResponse containing:
        configs: Configs, list of GCE Provide Config objects.
        missing_configs: list[str] of ids for which there is no config.
    """
    configs = []
    missing_configs = []
    futures = {}
    for prefix in ids:
      fut = self.m.futures.spawn(self._make_gce_config_call, prefix=prefix)
      futures[fut] = prefix
    for fut in self.m.futures.iwait(futures.keys()):
      stdout = fut.result()
      if stdout is None:
        pref = futures[fut]
        missing_configs.append(pref)
        self.m.deferrals.defer_exception(NoneConfigFailure(pref))
        continue
      configs.append(
          json_format.ParseDict(stdout, Config(), ignore_unknown_fields=True))
    return ConfigResponse(Configs(vms=configs), missing_configs)

  def _run(self, method, stdin_json, step_name=None, test_stdout=None,
           step_suffix=''):
    """Return a swarming command step.

    Args:
      method (str): config.Configuration method to call.
      stdin_json (json): json input data to Step command.
      step_name (str): Presentation name for step.
      test_stdout (dict): dictionary based test data.
    """
    step_name = step_name or ('gce-provider.config.{}{}'.format(
        method, step_suffix))
    cmd = [
        'prpc', 'call', '-format=json', GCE_PROVIDER_URL,
        'config.Configuration.' + method
    ]
    return self.m.easy.stdout_json_step(step_name, cmd, test_stdout=test_stdout,
                                        ignore_exceptions=True,
                                        stdin_json=stdin_json, infra_step=True)
