# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from recipe_engine.step_data import StepData
from RECIPE_MODULES.chromeos.labpack.utils import extract_executable_name_from_cipd_path, jsonify_labpack_input
from RECIPE_MODULES.chromeos.labpack.result_map import new_result_map
from PB.lab.labpack import LabpackInput

DEFAULT_CIPD_LABEL = 'prod'
DEFAULT_CIPD_PACKAGE = 'chromiumos/infra/labpack/${platform}'


class LabpackCommand(recipe_api.RecipeApi):
  """Labpack command is a singleton whose methods invoke the labpack CIPD executable

  Labpack has the following public attributes:
  - cipd_label
  - cipd_package

  - has_downloaded_package: bool

  """

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self.cipd_label = properties.version.cipd_label or DEFAULT_CIPD_LABEL
    self.cipd_package = properties.version.cipd_package or DEFAULT_CIPD_PACKAGE
    self.downloaded_executable_path = None

  @staticmethod
  def convert_step_data_to_status(step_data, dut_state):
    """Utility method to convert step data into a status like "ready". """
    assert step_data is None or isinstance(
        step_data, StepData), "step_data unexpectedly has type {}".format(
            type(step_data))  # pragma: nocover
    assert isinstance(dut_state,
                      str), "dut_state unexpectedly has type {}".format(
                          type(dut_state))
    if step_data is None:  # pragma: nocover
      return dut_state  # pragma: nocover

    if step_data.exc_result.retcode != 0:  # pragma: nocover
      return "needs_repair"
    return "ready"

  def has_downloaded_package(self):
    return self.downloaded_executable_path is not None  # pragma: nocover

  def get_cipd_executable_name(self):
    """get_cipd_executable_name gets the executable name from the CIPD path"""
    return extract_executable_name_from_cipd_path(
        self.cipd_package)  # pragma: nocover

  def get_cipd_path(self):
    """Get the path of the cipd package.

    Get the location of a path inside cleanup, which is guaranteed to be
    cleaned between runs.

    See documentation below for details:

    https://chromium.googlesource.com/infra/luci/recipes-py/+/HEAD/README.recipes.md#recipe_modules-path
    """
    return self.m.path['cleanup'].join('cipd', 'labpack')

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

  def run_labpack(self, labpack_input: LabpackInput, **kwargs) -> StepData:
    """Run labpack command.

    The kwargs are sent along without modification to `easy.step.__call__`.
    Note that the most important miscellaneous arg is "timeout".

    Args:
      labpack_input: a LabpackInput instance
      kwargs: a dictionary of the rest of the output to be handed to easy.step.

    Returns:
      see step.__call__
    """

    assert "cmd" not in kwargs, r'keyword argument "cmd" cannot be specified'
    assert "stdin_data" not in kwargs, r'keyword argument "stdin_data" cannot be specified'

    if not self.has_downloaded_package():
      self.ensure_labpack()

    out = self.m.easy.step(
        name=kwargs.get("name", "labpack invocation"),
        cmd=[self.downloaded_executable_path],
        stdin_data=jsonify_labpack_input(labpack_input),
        **kwargs,
    )
    assert isinstance(out, StepData), "out unexpectedly has type {}".format(
        type(out))
    return out

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

    if dut_state != "needs_repair":  # pragma: nocover
      return dut_state  # pragma: nocover

    assert self.ensure_labpack().get("ok")  # pragma: nocover

    step_data = self.run_labpack(
        labpack_input=LabpackInput(
            unit_name=hostnames[0],
            task_name="post_test",
            caller="test_runner.py",
        ))  # pragma: nocover

    return self.convert_step_data_to_status(step_data, dut_state)
