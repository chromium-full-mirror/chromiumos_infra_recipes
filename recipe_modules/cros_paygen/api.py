# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with Paygen and its config."""

import json
from copy import deepcopy
from recipe_engine import recipe_api


class BadPaygenConfig(Exception):
  """An exception we use if the received config looks invalid."""
  pass


class CrosPaygenApi(recipe_api.RecipeApi):
  """A module for CrOS-specific paygen steps."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosPaygenApi, self).__init__(*args, **kwargs)
    self._internal_config = None

  @property
  def _paygen_json_gs_path(self):
    """The path to the current release config for payload generation."""
    return 'gs://chromeos-build-release-console/paygen.json'

  @property
  def _config(self):
    """Lazily loaded copy of the entire configuration in paygen.json."""
    if not self._internal_config:
      raw_config = self._get_gs_config()
      self._internal_config = json.loads(raw_config)
      # Sanity check the configuration.
      if ('delta' not in self._internal_config or
          len(self._internal_config['delta']) == 0):
        raise BadPaygenConfig()
    # Returns immutable copy.
    return deepcopy(self._internal_config)

  def _get_gs_config(self):
    """Pull and load the current paygen configuration."""
    cat_res = self.m.gsutil.cat(self._paygen_json_gs_path, infra_step=True,
                                stdout=self.m.raw_io.output())
    return cat_res.stdout.strip()

  def _flatten_config(self, board_config):
    """Flatten a board_config so we can query it more easily."""
    new_b = deepcopy(board_config)
    del new_b['board']
    new_b['public_codename'] = board_config['board']['public_codename']
    new_b['is_active'] = board_config['board']['is_active']
    new_b['builder_name'] = board_config['board']['builder_name']
    return new_b

  def get_builder_config(self, builder_name, **kwargs):
    """Return the configs matching the queryor  [].

    Args:
      builder_name (String): The name of the builders to return configuration for.
      **kwargs: Match keyword to top level dictionary contents. For example passing
                delta_payload_tests=true will match only if matched.

    Returns:
     A list of dictionaries of the matching configurations. For example:

      [
       {
        "board": {
                "public_codename": "cyan",
                "is_active": true,
                "builder_name": "cyan"
        },
        "delta_type": "MILESTONE",
        "channel": "stable",
        "chrome_os_version": "13020.87.0",
        "chrome_version": "83.0.4103.119",
        "milestone": 83,
        "generate_delta": true,
        "delta_payload_tests": true,
        "full_payload_tests": false
        },
       {...},
       {...}
      ]
    """
    match_boards = []
    for b in self._config['delta']:
      b = self._flatten_config(b)
      if b['builder_name'] == builder_name:
        if all([k in b and b[k] == v for k, v in kwargs.items()]):
          match_boards.append(b)
    return match_boards
