# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for running recipes/support tools."""

from recipe_engine import recipe_api


class SupportApi(recipe_api.RecipeApi):
  """A module for support tool steps."""

  def call(self, tool, input_data, test_output_data=None, infra_step=True,
           timeout=None, add_json_log=True, name=None, **kwargs):
    """Run a tool from the support package.

    Args:
      tool (str): Tool name.
      input_data: Data to be passed as input to the tool (serialized to JSON).
      test_output_data (dict|list|Callable): Data to return in tests.
      infra_step (bool): Whether or not this is an infrastructure step.
      timeout (int): Timeout of the step in seconds.
      add_json_log (bool): Log the content of the output json.
      name (str): The step name to display, or None for default.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      Data passed as output from the tool (deserialized from JSON).
    """
    # Can't use gobin.call directly since we want to use stdout_json_step.
    support_cipd_path = self.m.gobin.ensure_package('support').removesuffix(
        '/support')

    step_name = name or tool
    return self.m.easy.stdout_json_step(step_name,
                                        [f'{support_cipd_path}/{tool}'],
                                        stdin_json=input_data,
                                        test_stdout=test_output_data,
                                        infra_step=infra_step, timeout=timeout,
                                        add_json_log=add_json_log, **kwargs)
