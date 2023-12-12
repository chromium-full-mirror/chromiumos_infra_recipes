# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is the labpack API.

It downloads the lapback CIPD executable to a shared area and manages access to it.
"""

from google.protobuf import json_format
from google.protobuf import struct_pb2
from recipe_engine import recipe_api
from recipe_engine.step_data import StepData
from RECIPE_MODULES.chromeos.labpack.utils import extract_executable_name_from_cipd_path
from RECIPE_MODULES.chromeos.labpack.result_map import new_result_map
from PB.lab.labpack import LabpackInput
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEFAULT_CIPD_LABEL = 'prod'
DEFAULT_CIPD_PACKAGE = 'chromiumos/infra/labpack/${platform}'


def _dict_to_struct(d):
  """convert a dictionary to the well-known type Struct."""
  return json_format.ParseDict(js_dict=d, message=struct_pb2.Struct())


def _struct_to_dict(struct):
  """convert an instance of the well-known type Struct to a dictionary."""
  return json_format.MessageToDict(struct)


class LabpackCommand(recipe_api.RecipeApi):
  """Labpack command is a singleton whose methods invoke the labpack CIPD executable

  Labpack has the following public attributes:
  - cipd_label
  - cipd_package

  - downloaded_executable_path: config_types.Path
  """

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self.run_count = 0
    self.cipd_label = properties.version.cipd_label or DEFAULT_CIPD_LABEL
    self.cipd_package = properties.version.cipd_package or DEFAULT_CIPD_PACKAGE
    self.downloaded_executable_path = None

  @staticmethod
  def get_ufs_host() -> str:  # pragma: nocover
    return 'ufs.api.cr.dev'

  @staticmethod
  def convert_step_data_to_status(step_data, dut_state):
    """Utility method to convert step data into a status like "ready". """
    assert step_data is None or isinstance(
        step_data, StepData), 'step_data unexpectedly has type {}'.format(
            type(step_data))  # pragma: nocover
    assert isinstance(dut_state,
                      str), 'dut_state unexpectedly has type {}'.format(
                          type(dut_state))
    if step_data is None:  # pragma: nocover
      return dut_state  # pragma: nocover

    if step_data.exc_result.retcode != 0:  # pragma: nocover
      return 'needs_repair'
    return 'ready'

  def has_downloaded_package(self):
    return self.downloaded_executable_path is not None  # pragma: nocover

  def get_cipd_executable_name(self):  # pragma: nocover
    """get_cipd_executable_name gets the executable name from the CIPD path"""
    return extract_executable_name_from_cipd_path(self.cipd_package)

  def get_cipd_path(self):  # pragma: nocover
    """Get the path of the cipd package."""
    return self.downloaded_executable_path

  def ensure_labpack(self):
    """Ensure labpack ensures that labpack exists.

    We create a cipd package area inside the cleanup directory,
    add labpack to the manifest file, and then ensure the resulting
    manifest.

    Args: No arguments

    Returns: Dictionary
    """
    out = new_result_map()

    if self.has_downloaded_package():
      return new_result_map()  # pragma: nocover

    # Add labpack to the current cipd package.
    with self.m.step.nest('ensure labpack'):
      self.downloaded_executable_path = self.m.cipd.ensure_tool(
          package=self.cipd_package,
          version=self.cipd_label,
      )

    return out

  def run_labpack(self, labpack_input: LabpackInput, only_run_once=False,
                  **kwargs) -> StepData:
    """Run labpack command.

    The kwargs are sent along without modification to `easy.step.__call__`.
    Note that the most important miscellaneous arg is "timeout".

    Args:
      labpack_input: a LabpackInput instance
      only_run_once: whether to only run once or not
      kwargs: a dictionary of the rest of the output to be handed to sub_build.

    Returns:
      see step.__call__ or None
    """
    attempted_run = False
    try:
      del labpack_input

      if only_run_once and self.run_count > 0:
        return None

      attempted_run = True
      assert 'cmd' not in kwargs, r'keyword argument "cmd" cannot be specified'
      assert 'stdin_data' not in kwargs, r'keyword argument "stdin_data" cannot be specified'

      if not self.has_downloaded_package():
        self.ensure_labpack()

      build = self.get_augmented_build()

      out = self.m.step.sub_build(
          name=kwargs.get('name', 'labpack invocation'),
          cmd=[self.downloaded_executable_path],
          build=build,
          raise_on_failure=False,
      )

      assert isinstance(out, StepData), 'out unexpectedly has type {}'.format(
          type(out))
      return out
    finally:
      if attempted_run:
        self.run_count += 1

  @staticmethod
  def get_use_ile_de_france(models, common_config):
    """Whether to use ile de france or not

    Args:
      * models: a list of models
      * common_config: the common config

    Returns:
      bool, whether to use ile de france or not"""

    if not models:
      return False

    model = models[0]

    if not common_config.enable_ile_de_france_config.enabled:
      return False  # pragma: nocover

    if model in common_config.enable_ile_de_france_config.allow_list.models:
      return True  # pragma: nocover

    if model in common_config.enable_ile_de_france_config.deny_list.models:
      return False  # pragma: nocover

    return False  # pragma: nocover

  def execute_ile_de_france(self, common_config, dut_state, models=None,
                            hostnames=None):
    """Whether to use Ile-de-France or not.

    Args:
      * common_config: the test runner properties
      * dut_state: the incoming dut state
      * models: the models in question
      * hostnames: the hostnames in question

    Returns:
      * the outgoing dut_state
    """
    assert not isinstance(models, (str, bytes))
    assert not isinstance(hostnames, (str, bytes))
    assert isinstance(dut_state, str)

    models = models or self.m.cros_tags.get_values(
        'label-model', self.m.buildbucket.build.infra.swarming.bot_dimensions)

    hostnames = hostnames or self.m.cros_tags.get_values(
        'dut_name', self.m.buildbucket.build.infra.swarming.bot_dimensions)

    use_ile_de_france = self.get_use_ile_de_france(models=models,
                                                   common_config=common_config)

    if not use_ile_de_france:
      return dut_state

    if dut_state != 'needs_repair':  # pragma: nocover
      return dut_state  # pragma: nocover

    assert self.ensure_labpack().get('ok')  # pragma: nocover

    step_data = self.run_labpack(
        labpack_input=LabpackInput(
            unit_name=hostnames[0],
            task_name='post_test',
            caller='test_runner.py',
        ))  # pragma: nocover

    return self.convert_step_data_to_status(step_data, dut_state)

  def get_build(self) -> build_pb2.Build:
    """get_build gets a copy of the input build"""
    b = build_pb2.Build()
    b.CopyFrom(self.m.buildbucket.build)
    return b

  def get_dut_name(self) -> str:
    """get the dut name from the swarming bot dimensions"""
    d = self.m.buildbucket.build.infra.swarming.bot_dimensions
    vals = self.m.cros_tags.get_values('dut_name', d)
    if vals:  # pragma: nocover
      return vals[0]
    return ''

  def get_augmented_build(self) -> build_pb2.Build:
    """return a build augmented with fields"""
    b = self.get_build()
    props_dict = _struct_to_dict(b.input.properties)
    props_dict['unit_name'] = self.get_dut_name()
    props_dict['task_name'] = 'post_test'
    props_dict['caller'] = 'test_runner.py'
    props_dict['inventory_service'] = self.get_ufs_host()
    props = _dict_to_struct(props_dict)
    b.input.properties.CopyFrom(props)
    return b
