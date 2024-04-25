# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the conductor tool."""

import json
from typing import List, Optional, Union

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
    self._report = {}

  @property
  def enabled(self) -> bool:
    return self._properties.enable_conductor

  @property
  def dryrun(self) -> bool:
    return self._properties.conductor_dryrun

  def collect_config(self,
                     collect_name: Union[str, None]) -> Optional[CollectConfig]:
    if not self._properties.collect_configs or not collect_name:
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
    self.m.gobin.call('conductor', cmd, step_name=step_name or
                      'conductor: %s' % cmd[0], timeout=timeout, **kwargs)

  def collect(self, collect_name: str, bbids: List[Union[str, int]],
              initial_retry: bool = False, **kwargs) -> List[int]:
    """Calls `conductor collect` with the given args.

    Args:
      collect_name: Name of this collection (used to find collect config).
      bbids: List of BBIDs to collect.
      initial_retry: Whether to pass --initial_retry to conductor for an
        unconditional retry at the start of the run.

    Returns:
      Final set of BBIDs.
    """
    if not self.enabled:
      raise StepFailure('conductor is not enabled')

    collect_config = self.collect_config(collect_name)
    if not collect_config:
      raise StepFailure("could not find collect config for collection '%s'" %
                        collect_name)

    if not bbids:
      raise StepFailure('no bbids specified')
    bbids = [str(bbid) for bbid in bbids]

    messages_path = self.m.path.mkdtemp(prefix='conductor-')
    input_json_file = messages_path / 'input.json'
    output_json_file = messages_path / 'output.json'
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
    if self.dryrun:
      cmd += ['--dryrun']
    if initial_retry:
      cmd += ['--initial_retry']

    # Try except so that the step turns red but does not doom the build.
    try:
      self(cmd, **kwargs)
    except:  #pylint: disable=bare-except
      pass

    with self.m.step.nest('read conductor output') as presentation:
      try:
        data = self.m.file.read_text('read output json', output_json_file,
                                     test_data='{"bbids":["123"]}')
        output = json.loads(data)

        report = output.get('report', None)
        if report:
          self._report[collect_name] = report
          self.m.easy.set_properties_step(conductor_report=self._report,
                                          step_name='update conductor report')

        conductor_bbids = [int(bbid) for bbid in output.get('bbids', [])]
        if not conductor_bbids:
          presentation.status = self.m.step.FAILURE
          presentation.step_text = 'conductor reported no bbids, falling back to original bbids'
          conductor_bbids = bbids
        return [int(bbid) for bbid in conductor_bbids]
      except:  #pylint: disable=bare-except
        presentation.step_text = "couldn't parse output, falling back to original bbids"
        return [int(bbid) for bbid in bbids]
