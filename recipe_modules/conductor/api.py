# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the conductor tool."""

import json
from typing import List, Union

from google.protobuf import json_format

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.conductor import CollectConfig
from PB.recipe_modules.chromeos.conductor.conductor import ConductorProperties


class ConductorApi(recipe_api.RecipeApi):
  """A module for calling conductor."""

  def __init__(self, properties: ConductorProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties

  def initialize(self):
    """Initializes the module."""
    self._conductor_path = None

    self._conductor_cipd_package = (
        self._properties.conductor_cipd_package or
        'chromiumos/infra/conductor/${platform}')

    default_ref = 'staging' if self.m.cros_infra_config.is_staging else 'prod'
    self._conductor_cipd_ref = (
        self._properties.conductor_cipd_ref or default_ref)

  @property
  def enabled(self) -> bool:
    return self._properties.enable_conductor

  def collect_config(self, collect_name: str) -> CollectConfig:
    if not self._properties.collect_configs:
      return None
    return self._properties.collect_configs.get(collect_name, None)

  def __call__(self, cmd: List[str], step_name: str = None, timeout: int = 3600,
               **kwargs):
    """Call conductor with the given args.

    Args:
      cmd: Command to be run with conductor
      step_name: Message to use for step. Optional.
      timeout: Timeout, in seconds. Defaults to one hour.
      kwargs: Keyword arguments for recipe_engine/step.
    """
    self._ensure_conductor()
    self.m.step(step_name or 'conductor: %s' % cmd[0],
                [self._conductor_path] + cmd, timeout=timeout, **kwargs)

  def collect(self, collect_name: str, bbids: List[Union[str, int]],
              dryrun: bool = False, **kwargs) -> List[int]:
    """Calls `conductor collect` with the given args.

    Args:
      collect_name: Name of this collection (used to find collect config).
      bbids: List of BBIDs to collect.
      dryrun: Whether or not to dryrun retries.

    Returns:
      Final set of BBIDs.
    """
    if not self.enabled:
      raise StepFailure('conductor is not enabled')

    collect_config = self.collect_config(collect_name)
    if not collect_config:
      raise StepFailure('could not find collect config for collection \'%s\'' %
                        collect_name)

    if not bbids:
      raise StepFailure('no bbids specified')
    bbids = [str(bbid) for bbid in bbids]

    messages_path = self.m.path.mkdtemp(prefix='conductor-')
    input_json_file = messages_path.join('input.json')
    output_json_file = messages_path.join('output.json')
    self.m.file.write_text('write input json', input_json_file,
                           json_format.MessageToJson(collect_config))

    cmd = [
        'collect', '--input_json', input_json_file, '--output_json',
        output_json_file, '--bbids', ','.join(bbids)
    ]
    if self._properties.polling_interval_seconds:
      cmd += [
          '--polling_interval',
          str(self._properties.polling_interval_seconds)
      ]
    if dryrun:
      cmd += ['--dryrun']
    self(cmd, **kwargs)

    data = self.m.file.read_text('read output json', output_json_file,
                                 test_data='["123"]')
    bbids = json.loads(data)
    return [int(bbid) for bbid in bbids] if bbids else None

  def _ensure_conductor(self):
    """Ensure the conductor cli is installed."""
    if self._conductor_path:
      return  # pragma: nocover

    with self.m.step.nest('ensure conductor'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._conductor_cipd_package, self._conductor_cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._conductor_path = cipd_dir.join('conductor')
